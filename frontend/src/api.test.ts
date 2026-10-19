import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError, CancelledError, describeError, type EventSourceLike } from "./api";

function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body),
                      { status, headers: { "Content-Type": "application/json" } });
}

describe("describeError", () => {
  it("handles the three FastAPI error shapes", () => {
    expect(describeError(409, { detail: "experiment is running" }).message).toBe("experiment is running");
    const e = describeError(404, { detail: { message: "unknown odour 'x'", suggestions: ["3-octanol"] } });
    expect(e.message).toBe("unknown odour 'x'");
    expect(e.suggestions).toEqual(["3-octanol"]);
    const v = describeError(422, { detail: [{ loc: ["body", "trials"], msg: "less than or equal to 20" }] });
    expect(v.message).toBe("trials: less than or equal to 20");
    expect(describeError(502, null).message).toBe("HTTP 502");
  });
});

describe("ApiClient", () => {
  it("builds spike URLs with repeated group parameters", async () => {
    const fetchFn = vi.fn(async (_url: string, _init?: RequestInit) => json(200, { neurons: [], times_ms: [] }));
    const api = new ApiClient("http://x", fetchFn);
    await api.spikes("a b", 0, 500, ["KC", "MBON"], 1000);
    const url = new URL(fetchFn.mock.calls[0]![0]);
    expect(url.pathname).toBe("/api/experiments/a%20b/spikes");
    expect(url.searchParams.getAll("group")).toEqual(["KC", "MBON"]);
    expect(url.searchParams.get("max_spikes")).toBe("1000");
  });

  it("sends the API key only when one is set, keeping other headers", async () => {
    const fetchFn = vi.fn(async (_url: string, _init?: RequestInit) => json(202, { id: "x" }));
    const api = new ApiClient("", fetchFn);
    const req = { cs_plus: "a", cs_minus: "b", odour_source: "random" as const, trials: 1, us: "shock" as const, seed: 1 };
    await api.submitConditioning(req);
    expect(new Headers(fetchFn.mock.calls[0]![1]!.headers).has("X-API-Key")).toBe(false);
    api.apiKey = "ff_secret";
    await api.submitConditioning(req);
    const headers = new Headers(fetchFn.mock.calls[1]![1]!.headers);
    expect(headers.get("X-API-Key")).toBe("ff_secret");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("posts JSON and throws ApiError on failure", async () => {
    const fetchFn = vi.fn(async (_url: string, _init?: RequestInit) => json(429, { detail: "all slots busy" }));
    const api = new ApiClient("", fetchFn);
    const req = { cs_plus: "a", cs_minus: "b", odour_source: "random" as const, trials: 1, us: "shock" as const, seed: 1 };
    await expect(api.submitConditioning(req)).rejects.toMatchObject({ status: 429, message: "all slots busy" });
    const init = fetchFn.mock.calls[0]![1]!;
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(req);
  });

  it("builds sweep requests and links", async () => {
    const fetchFn = vi.fn(async (_url: string, _init?: RequestInit) => json(200, { id: "s 1", status: "done" }));
    const api = new ApiClient("", fetchFn, null);
    await api.createSweep({ base: { cs_plus: "a", cs_minus: "b", odour_source: "random", trials: 1, us: "shock", seed: 1 },
                            parameter: "trials", values: [0, 1], repeats: 2 });
    expect(fetchFn.mock.calls[0]![0]).toBe("/api/sweeps");
    expect(JSON.parse(fetchFn.mock.calls[0]![1]!.body as string).values).toEqual([0, 1]);
    expect(api.sweepCsvUrl("s 1")).toBe("/api/sweeps/s%201/results.csv");
    await api.experiments(true);
    expect(fetchFn.mock.calls[1]![0]).toBe("/api/experiments?include_sweeps=true&limit=100");
    const updates: string[] = [];
    await api.waitForSweep("s 1", { onSweep: (d) => updates.push(d.status) });
    expect(updates).toEqual(["done"]);
  });

  it("returns undefined for 204", async () => {
    const api = new ApiClient("", async () => json(204, null));
    await expect(api.deleteExperiment("x")).resolves.toBeUndefined();
  });

  it("polls until done, and rejects when the experiment fails", async () => {
    const statuses = ["queued", "running", "done"];
    const updates: string[] = [];
    const api = new ApiClient("", async () => json(200, { id: "1", status: statuses.shift(), result: {} }), null);
    const d = await api.waitForExperiment("1", { intervalMs: 1, onUpdate: (x) => updates.push(x.status) });
    expect(d.status).toBe("done");
    expect(updates).toEqual(["queued", "running", "done"]);

    const failing = new ApiClient("", async () => json(200, { id: "1", status: "failed", error: "ValueError: bad" }), null);
    await expect(failing.waitForExperiment("1")).rejects.toBeInstanceOf(ApiError);
  });

  it("stops polling when aborted", async () => {
    const api = new ApiClient("", async () => json(200, { id: "1", status: "running" }), null);
    const controller = new AbortController();
    const done = api.waitForExperiment("1", { intervalMs: 10_000, signal: controller.signal });
    setTimeout(() => controller.abort(), 5);
    await expect(done).rejects.toMatchObject({ name: "AbortError" });
  });

  it("pages through lists with cursors, and builds cancel and export URLs", async () => {
    const fetchFn = vi.fn(async (_url: string, _init?: RequestInit) => json(200, { items: [], next_cursor: null }));
    const api = new ApiClient("", fetchFn, null);
    await api.experimentPage({ limit: 2, cursor: "abc" });
    expect(fetchFn.mock.calls[0]![0]).toBe("/api/experiments?limit=2&cursor=abc");
    await api.cancelExperiment("e 1");
    expect(fetchFn.mock.calls[1]![0]).toBe("/api/experiments/e%201/cancel");
    expect(fetchFn.mock.calls[1]![1]!.method).toBe("POST");
    await api.cancelSweep("s");
    expect(fetchFn.mock.calls[2]![0]).toBe("/api/sweeps/s/cancel");
    expect(api.exportUrls("e")).toEqual({ json: "/api/experiments/e/export.json",
      mbons: "/api/experiments/e/mbons.csv", spikes: "/api/experiments/e/spikes.csv" });
  });
});

/** A scripted EventSource: emits the given events on the next tick. */
class FakeSource implements EventSourceLike {
  static opened: FakeSource[] = [];
  readyState = 0;
  onerror: ((e: Event) => void) | null = null;
  closed = false;
  private listeners = new Map<string, ((e: MessageEvent) => void)[]>();

  constructor(readonly url: string, script: [string, unknown][] | "refused") {
    FakeSource.opened.push(this);
    setTimeout(() => {
      if (script === "refused") {
        this.readyState = 2;
        this.onerror?.(new Event("error"));
        return;
      }
      for (const [type, data] of script) {
        if (this.closed) return;
        for (const fn of this.listeners.get(type) ?? []) fn(new MessageEvent(type, { data: JSON.stringify(data) }));
      }
    }, 0);
  }

  addEventListener(type: string, fn: (e: MessageEvent) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }

  close(): void {
    this.closed = true;
    this.readyState = 2;
  }
}

describe("live events", () => {
  it("follows an experiment's events, then fetches the result", async () => {
    const fetchFn = vi.fn(async (_url: string) => json(200, { id: "1", status: "done", result: { ok: 1 } }));
    const api = new ApiClient("", fetchFn, (url) => new FakeSource(url, [
      ["update", { id: "1", status: "queued", progress: null }],
      ["update", { id: "1", status: "running", progress: { done: 1, total: 2 } }],
      ["update", { id: "1", status: "done", progress: { done: 2, total: 2 } }],
      ["end", {}],
    ]));
    const updates: string[] = [];
    const d = await api.waitForExperiment("1", { onUpdate: (s) => updates.push(s.status) });
    expect(updates).toEqual(["queued", "running", "done"]);
    expect(d.result).toEqual({ ok: 1 });
    expect(fetchFn).toHaveBeenCalledTimes(1);                   // no polling
    expect(FakeSource.opened.at(-1)!.url).toBe("/api/experiments/1/events");
    expect(FakeSource.opened.at(-1)!.closed).toBe(true);
  });

  it("rejects with CancelledError for a cancelled experiment", async () => {
    const api = new ApiClient("", async () => json(200, { id: "1", status: "cancelled", error: "cancelled while running" }),
      (url) => new FakeSource(url, [["update", { id: "1", status: "cancelled" }], ["end", {}]]));
    await expect(api.waitForExperiment("1")).rejects.toBeInstanceOf(CancelledError);
  });

  it("falls back to polling when the stream is refused", async () => {
    const statuses = ["running", "done"];
    const api = new ApiClient("", async () => json(200, { id: "1", status: statuses.shift(), result: {} }),
      (url) => new FakeSource(url, "refused"));
    const updates: string[] = [];
    const d = await api.waitForExperiment("1", { intervalMs: 1, onUpdate: (s) => updates.push(s.status) });
    expect(d.status).toBe("done");
    expect(updates).toEqual(["running", "done"]);
  });

  it("closes the stream when aborted", async () => {
    const api = new ApiClient("", async () => json(200, {}), (url) => new FakeSource(url, []));
    const controller = new AbortController();
    const done = api.waitForExperiment("1", { signal: controller.signal });
    controller.abort();
    await expect(done).rejects.toMatchObject({ name: "AbortError" });
    expect(FakeSource.opened.at(-1)!.closed).toBe(true);
  });

  it("follows a sweep until it ends", async () => {
    const api = new ApiClient("", async () => json(500, {}), (url) => new FakeSource(url, [
      ["update", { id: "s", status: "running" }], ["update", { id: "s", status: "done" }], ["end", {}]]));
    const seen: string[] = [];
    const d = await api.waitForSweep("s", { onSweep: (x) => seen.push(x.status) });
    expect(d.status).toBe("done");
    expect(seen).toEqual(["running", "done"]);
  });
});

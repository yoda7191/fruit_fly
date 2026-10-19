// api.ts — typed client for the fruit_fly backend.
//
// All paths are relative ("/api/..."): in development Vite proxies them to
// the backend, in production the frontend is served from the same origin.

import type {
  CancelResult,
  CircuitSummary,
  ConditioningRequest,
  ExperimentDetail,
  ExperimentSummary,
  Health,
  LesionOptions,
  NeuronTable,
  OdourList,
  ProtocolPreset,
  SpikeWindow,
  SweepDetail,
  SweepRequest,
  SweepSummary,
  NeuronActivity,
  NeuronConnections,
  NeuronDetail,
  BrainRegions,
  GroupConnection,
  OdourCatalogItem,
  OdourSimilarity,
  Page,
  SweepCancelResult,
} from "./types";

/** An HTTP error with the backend's explanation turned into readable text. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly suggestions: string[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * FastAPI error bodies come in three shapes:
 *   {"detail": "text"}
 *   {"detail": {"message": "...", "suggestions": [...]}}      (unknown odour)
 *   {"detail": [{"loc": [...], "msg": "..."}, ...]}           (validation)
 */
export function describeError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return new ApiError(status, detail);
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      const e = d as { loc?: unknown[]; msg?: string };
      const where = (e.loc ?? []).filter((p) => p !== "body").join(".");
      return where ? `${where}: ${e.msg ?? "invalid"}` : (e.msg ?? "invalid");
    });
    return new ApiError(status, parts.join("; ") || `HTTP ${status}`);
  }
  if (detail && typeof detail === "object") {
    const d = detail as { message?: string; suggestions?: string[] };
    return new ApiError(status, d.message ?? `HTTP ${status}`, d.suggestions ?? []);
  }
  return new ApiError(status, `HTTP ${status}`);
}

/** The experiment (or every experiment of a sweep) was cancelled. */
export class CancelledError extends Error {
  constructor(message = "cancelled") {
    super(message);
    this.name = "CancelledError";
  }
}

export interface WaitOptions {
  intervalMs?: number;                 // polling interval when live events aren't available
  signal?: AbortSignal;
  onUpdate?: (summary: ExperimentSummary) => void;
}

type FetchFn = (input: string, init?: RequestInit) => Promise<Response>;

/** The parts of the browser's EventSource used here (tests pass a fake). */
export interface EventSourceLike {
  readonly readyState: number;         // 2 = closed: the browser gave up reconnecting
  addEventListener(type: string, listener: (e: MessageEvent) => void): void;
  onerror: ((e: Event) => void) | null;
  close(): void;
}
export type EventSourceFactory = (url: string) => EventSourceLike;

const CLOSED = 2;

/** Live events unavailable (old server, proxy refusing streams): poll instead. */
class NoLiveEvents extends Error {}

export class ApiClient {
  private readonly fetchFn: FetchFn;
  private readonly eventSource: EventSourceFactory | null;
  /** Sent as X-API-Key when set (servers with FRUIT_FLY_REQUIRE_API_KEY=1). */
  apiKey: string | null = null;

  constructor(
    private readonly baseUrl = "",
    fetchFn?: FetchFn,
    eventSource?: EventSourceFactory | null,
  ) {
    this.fetchFn = fetchFn ?? ((input, init) => fetch(input, init));
    this.eventSource = eventSource !== undefined ? eventSource
      : typeof EventSource !== "undefined" ? (url) => new EventSource(url) : null;
  }

  /**
   * Follow a server-sent event stream: calls onUpdate with each `update`,
   * resolves with the last one on `end`. Rejects with NoLiveEvents if the
   * stream can't be opened (the caller then polls). Transient drops are left
   * to EventSource, which reconnects; the server resends the current state.
   */
  private follow<T>(path: string, onUpdate: (data: T) => void, signal?: AbortSignal): Promise<T> {
    return new Promise((resolve, reject) => {
      if (!this.eventSource) return reject(new NoLiveEvents());
      if (signal?.aborted) return reject(new DOMException("aborted", "AbortError"));
      const source = this.eventSource(this.baseUrl + path);
      let last: T | undefined;
      const finish = (fn: () => void) => {
        source.close();
        signal?.removeEventListener("abort", onAbort);
        fn();
      };
      const onAbort = () => finish(() => reject(new DOMException("aborted", "AbortError")));
      signal?.addEventListener("abort", onAbort, { once: true });
      source.addEventListener("update", (e) => {
        last = JSON.parse(e.data as string) as T;
        onUpdate(last);
      });
      source.addEventListener("end", () => finish(() =>
        last === undefined ? reject(new NoLiveEvents()) : resolve(last)));
      source.addEventListener("gone", () => finish(() => reject(new ApiError(404, "it was deleted"))));
      source.onerror = () => {
        if (source.readyState === CLOSED) finish(() => reject(new NoLiveEvents()));
      };
    });
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers);
    if (this.apiKey) headers.set("X-API-Key", this.apiKey);
    const res = await this.fetchFn(this.baseUrl + path, { ...init, headers });
    if (!res.ok) {
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        // non-JSON error body (e.g. proxy error page)
      }
      throw describeError(res.status, body);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  /** Raw bytes (the morphology file); `onProgress` gets the bytes received so far. */
  async binary(path: string, onProgress?: (bytes: number) => void, signal?: AbortSignal): Promise<ArrayBuffer> {
    const res = await this.fetchFn(this.baseUrl + path, { signal });
    if (!res.ok) throw describeError(res.status, await res.json().catch(() => null));
    if (!res.body || !onProgress) return res.arrayBuffer();
    const reader = res.body.getReader();
    const parts: Uint8Array[] = [];
    let size = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value);
      size += value.length;
      onProgress(size);
    }
    const out = new Uint8Array(size);
    let at = 0;
    for (const p of parts) {
      out.set(p, at);
      at += p.length;
    }
    return out.buffer;
  }

  health(): Promise<Health> {
    return this.request("/api/health");
  }

  neuron(index: number): Promise<NeuronDetail> {
    return this.request(`/api/circuit/neurons/${index}`);
  }

  neuronActivity(experimentId: string, index: number): Promise<NeuronActivity> {
    return this.request(`/api/experiments/${encodeURIComponent(experimentId)}/neurons/${index}`);
  }

  /** Every partner of one neuron with at least `minSynapses` synapses, strongest first. */
  connections(index: number, minSynapses = 1, limit = 200): Promise<NeuronConnections> {
    const q = new URLSearchParams({ min_synapses: String(minSynapses), limit: String(limit) });
    return this.request(`/api/circuit/neurons/${index}/connections?${q}`);
  }

  /** Synapses between every pair of neuron groups. */
  connectivity(): Promise<GroupConnection[]> {
    return this.request("/api/circuit/connectivity");
  }

  /** Brain region meshes (only for circuits in FlyWire space). */
  regions(): Promise<BrainRegions> {
    return this.request("/api/circuit/regions");
  }

  /** Every neuron's shape, binary: see morphology.ts. */
  morphology(onProgress?: (bytes: number) => void, signal?: AbortSignal): Promise<ArrayBuffer> {
    return this.binary("/api/circuit/morphology", onProgress, signal);
  }

  circuit(): Promise<CircuitSummary> {
    return this.request("/api/circuit");
  }

  neurons(): Promise<NeuronTable> {
    return this.request("/api/circuit/neurons");
  }

  protocols(): Promise<ProtocolPreset[]> {
    return this.request("/api/protocols");
  }

  lesionOptions(): Promise<LesionOptions> {
    return this.request("/api/circuit/lesion-options");
  }

  odours(search = "", limit = 50, offset = 0): Promise<OdourList> {
    const q = new URLSearchParams({ search, limit: String(limit), offset: String(offset) });
    return this.request(`/api/odours?${q}`);
  }

  /** Every odour with its chemical class and coverage. */
  async odourCatalog(): Promise<OdourCatalogItem[]> {
    return (await this.request<{ items: OdourCatalogItem[] }>("/api/odours/catalog")).items;
  }

  odourSimilarity(a: string, b: string): Promise<OdourSimilarity> {
    return this.request(`/api/odours/similarity?${new URLSearchParams({ a, b })}`);
  }

  submitConditioning(req: ConditioningRequest): Promise<ExperimentSummary> {
    return this.request("/api/experiments/conditioning", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
  }

  /** One page of stored experiments, newest first. */
  experimentPage(opts: { includeSweeps?: boolean; limit?: number; cursor?: string | null } = {}):
      Promise<Page<ExperimentSummary>> {
    const q = new URLSearchParams();
    if (opts.includeSweeps) q.set("include_sweeps", "true");
    if (opts.limit !== undefined) q.set("limit", String(opts.limit));
    if (opts.cursor) q.set("cursor", opts.cursor);
    return this.request(`/api/experiments${q.size ? `?${q}` : ""}`);
  }

  /** The newest stored experiments (first page). */
  async experiments(includeSweeps = false, limit = 100): Promise<ExperimentSummary[]> {
    return (await this.experimentPage({ includeSweeps, limit })).items;
  }

  cancelExperiment(id: string): Promise<CancelResult> {
    return this.request(`/api/experiments/${encodeURIComponent(id)}/cancel`, { method: "POST" });
  }

  /** Download links: the full result, the per-MBON table, every spike. */
  exportUrls(id: string): { json: string; mbons: string; spikes: string } {
    const base = `${this.baseUrl}/api/experiments/${encodeURIComponent(id)}`;
    return { json: `${base}/export.json`, mbons: `${base}/mbons.csv`, spikes: `${base}/spikes.csv` };
  }

  experiment(id: string): Promise<ExperimentDetail> {
    return this.request(`/api/experiments/${encodeURIComponent(id)}`);
  }

  spikes(id: string, t0Ms: number, t1Ms: number, groups?: string[],
         maxSpikes?: number, signal?: AbortSignal): Promise<SpikeWindow> {
    const q = new URLSearchParams({ t0_ms: String(t0Ms), t1_ms: String(t1Ms) });
    for (const g of groups ?? []) q.append("group", g);
    if (maxSpikes !== undefined) q.set("max_spikes", String(maxSpikes));
    return this.request(`/api/experiments/${encodeURIComponent(id)}/spikes?${q}`, { signal });
  }

  deleteExperiment(id: string): Promise<void> {
    return this.request(`/api/experiments/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  createSweep(req: SweepRequest): Promise<SweepSummary> {
    return this.request("/api/sweeps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
  }

  async sweeps(limit = 100): Promise<SweepSummary[]> {
    return (await this.request<Page<SweepSummary>>(`/api/sweeps?limit=${limit}`)).items;
  }

  cancelSweep(id: string): Promise<SweepCancelResult> {
    return this.request(`/api/sweeps/${encodeURIComponent(id)}/cancel`, { method: "POST" });
  }

  sweep(id: string): Promise<SweepDetail> {
    return this.request(`/api/sweeps/${encodeURIComponent(id)}`);
  }

  /** Link target for downloading a sweep's per-experiment CSV. */
  sweepCsvUrl(id: string): string {
    return `${this.baseUrl}/api/sweeps/${encodeURIComponent(id)}/results.csv`;
  }

  deleteSweep(id: string): Promise<void> {
    return this.request(`/api/sweeps/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  /** Follow a sweep (live events, else polling) until it is no longer running. */
  async waitForSweep(id: string, opts: WaitOptions & { onSweep?: (s: SweepDetail) => void } = {}): Promise<SweepDetail> {
    try {
      return await this.follow<SweepDetail>(`/api/sweeps/${encodeURIComponent(id)}/events`,
                                            (d) => opts.onSweep?.(d), opts.signal);
    } catch (err) {
      if (!(err instanceof NoLiveEvents)) throw err;
    }
    const interval = opts.intervalMs ?? 1000;
    for (;;) {
      if (opts.signal?.aborted) throw new DOMException("aborted", "AbortError");
      const detail = await this.sweep(id);
      opts.onSweep?.(detail);
      if (detail.status !== "running") return detail;
      await sleep(interval, opts.signal);
    }
  }

  /**
   * Follow an experiment until it finishes: live events when the server and
   * browser support them, polling otherwise. Resolves with the result on done;
   * rejects with ApiError on failed and CancelledError on cancelled.
   */
  async waitForExperiment(id: string, opts: WaitOptions = {}): Promise<ExperimentDetail> {
    try {
      await this.follow<ExperimentSummary>(`/api/experiments/${encodeURIComponent(id)}/events`,
                                           (s) => opts.onUpdate?.(s), opts.signal);
      return finished(await this.experiment(id));
    } catch (err) {
      if (!(err instanceof NoLiveEvents)) throw err;
    }
    const interval = opts.intervalMs ?? 500;
    for (;;) {
      if (opts.signal?.aborted) throw new DOMException("aborted", "AbortError");
      const detail = await this.experiment(id);
      opts.onUpdate?.(detail);
      if (detail.status !== "queued" && detail.status !== "running") return finished(detail);
      await sleep(interval, opts.signal);
    }
  }
}

function finished(detail: ExperimentDetail): ExperimentDetail {
  if (detail.status === "done") return detail;
  if (detail.status === "cancelled") throw new CancelledError(detail.error ?? "cancelled");
  throw new ApiError(500, detail.error ?? "experiment failed");
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("aborted", "AbortError"));
      },
      { once: true },
    );
  });
}
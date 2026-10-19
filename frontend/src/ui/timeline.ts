// timeline.ts — playback controls and the protocol track (odours, shocks, playhead).

import type { TimelineEntry } from "../types";
import { el } from "./dom";

export function entryAt(entries: TimelineEntry[], timeMs: number): TimelineEntry | null {
  return entries.find((e) => e.t_start_ms <= timeMs && timeMs < e.t_end_ms) ?? null;
}

/** When the last training presentation ends (null if there was no training). */
export function trainingEnd(entries: TimelineEntry[]): number | null {
  const ends = entries.filter((e) => e.phase === "training").map((e) => e.t_end_ms);
  return ends.length ? Math.max(...ends) : null;
}

export function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)} s`;
}

export function describeEntry(e: TimelineEntry | null): string {
  if (!e) return "rest";
  if (e.label === "US") return `${e.phase} \u00b7 ${e.us} alone`;
  const us = e.us === "none" ? "" : ` + ${e.us}`;
  return `${e.phase} \u00b7 ${e.label}${us}`;
}

export interface TimelineHandlers {
  onSeek: (timeMs: number) => void;
  onToggle: () => void;
  onSpeed: (speed: number) => void;
}

export const SPEEDS = [0.1, 0.25, 0.5, 1, 2, 4];

export class Timeline {
  private readonly playButton = el("button", { class: "play", text: "\u25b6" });
  private readonly speed = el("select", { title: "playback speed (simulated time per real time)" });
  private readonly clock = el("span", { class: "clock", text: "\u2014" });
  private readonly phase = el("span", { class: "phase", text: "" });
  private readonly blocks = el("div", { class: "blocks" });
  private readonly playhead = el("div", { class: "playhead" });
  private readonly track = el("div", { class: "track" }, [this.blocks, this.playhead]);
  private entries: TimelineEntry[] = [];
  private duration = 0;

  constructor(
    root: HTMLElement,
    private readonly handlers: TimelineHandlers,
  ) {
    for (const s of SPEEDS) {
      const option = el("option", { text: `${s}\u00d7` });
      option.value = String(s);
      option.selected = s === 1;
      this.speed.append(option);
    }
    this.playButton.addEventListener("click", () => this.handlers.onToggle());
    this.speed.addEventListener("change", () => this.handlers.onSpeed(Number(this.speed.value)));
    this.track.addEventListener("click", (event) => {
      if (this.duration <= 0) return;
      const rect = this.track.getBoundingClientRect();
      const fraction = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
      this.handlers.onSeek(Math.min(1, Math.max(0, fraction)) * this.duration);
    });
    root.replaceChildren(
      el("div", { class: "controls" }, [this.playButton, this.speed, this.clock, this.phase]),
      this.track,
    );
    this.clear();
  }

  setExperiment(entries: TimelineEntry[], durationMs: number): void {
    this.entries = entries;
    this.duration = durationMs;
    const pct = (ms: number) => `${(100 * ms) / durationMs}%`;
    const blocks = entries.map((e) => {
      const block = el("div", {
        class: `block phase-${e.phase} us-${e.us}`,
        title: `${describeEntry(e)} (${formatSeconds(e.t_start_ms)}\u2013${formatSeconds(e.t_end_ms)})`,
      });
      block.style.left = pct(e.t_start_ms);
      block.style.width = pct(e.t_end_ms - e.t_start_ms);
      return block;
    });
    // US windows as a strip along the bottom: shows timing, e.g. a shock before the odour
    const marks = entries.filter((e) => e.us !== "none" && e.us_start_ms !== null && e.us_end_ms !== null)
      .map((e) => {
        const mark = el("div", { class: `us-mark us-${e.us}`, title: `${e.us}` });
        mark.style.left = pct(e.us_start_ms!);
        mark.style.width = pct(e.us_end_ms! - e.us_start_ms!);
        return mark;
      });
    this.blocks.replaceChildren(...blocks, ...marks);

    this.setEnabled(true);
    this.setTime(0, { playing: false, buffering: false });
  }

  setTime(timeMs: number, state: { playing: boolean; buffering: boolean }): void {
    if (this.duration <= 0) return;
    this.playhead.style.left = `${(100 * timeMs) / this.duration}%`;
    this.clock.textContent = `${formatSeconds(timeMs)} / ${formatSeconds(this.duration)}`;
    this.phase.textContent = state.buffering ? "loading spikes\u2026" : describeEntry(entryAt(this.entries, timeMs));
    this.playButton.textContent = state.playing ? "\u23f8" : "\u25b6";
  }

  clear(): void {
    this.entries = [];
    this.duration = 0;
    this.blocks.replaceChildren();
    this.playhead.style.left = "0%";
    this.clock.textContent = "\u2014";
    this.phase.textContent = "run an experiment to play it back";
    this.setEnabled(false);
  }

  private setEnabled(enabled: boolean): void {
    this.playButton.disabled = !enabled;
    this.speed.disabled = !enabled;
    this.track.classList.toggle("disabled", !enabled);
  }
}
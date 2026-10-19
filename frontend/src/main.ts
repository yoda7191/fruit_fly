// main.ts — wires the API, the 3D viewer, playback and the panels together.

import "./style.css";
import { setupApiKey } from "./ui/apiKey";
import { renderNeuron } from "./ui/neuronPanel";
import { compareMenu, renderComparison } from "./ui/compare";

import { ActivityBuffer } from "./activity";
import { ApiClient, ApiError, CancelledError } from "./api";
import { SpikePlayer } from "./playback";
import type { ExperimentDetail, SweepDetail } from "./types";
import { byId } from "./ui/dom";
import { describeProgress, ExperimentForm } from "./ui/experimentForm";
import { renderHistory } from "./ui/history";
import { renderLegend } from "./ui/legend";
import { downloadLinks, renderResults } from "./ui/results";
import { METRIC_LABELS, renderSweep } from "./ui/sweepChart";
import { SweepPanel, sweepOutcome } from "./ui/sweepPanel";
import { Timeline } from "./ui/timeline";
import { groupCentres, groupLinks, groupPartners, groupRoles, neuronLinks, neuronRoles } from "./explorer";
import { boundsOf, frameFromBounds, neuronFrame } from "./geometry";
import { decodeMorphology } from "./morphology";
import type { BrainRegions, CircuitSummary, GroupConnection, NeuronConnections, NeuronTable } from "./types";
import { renderDisplayOptions, type DisplayOption } from "./ui/legend";
import { connectionControls, renderGroup } from "./ui/neuronPanel";
import { BrainViewer } from "./viewer";

/** Connections drawn per direction in the explorer (the panel says how many exist). */
const MAX_LINKS = 60;

const api = new ApiClient();

/** Show a cancel button that runs `cancel` once; errors go to `report`. */
function showCancel(button: HTMLButtonElement, cancel: () => Promise<void>,
                    report: (text: string, kind?: "info" | "error") => void): void {
  button.hidden = false;
  button.disabled = false;
  button.onclick = () => {
    button.disabled = true;
    report("Cancelling\u2026");
    cancel().catch((err: unknown) => {
      button.disabled = false;
      report(message(err), "error");
    });
  };
}

function message(err: unknown): string {
  if (err instanceof ApiError) {
    return err.suggestions.length
      ? `${err.message}. Did you mean: ${err.suggestions.join(", ")}?`
      : err.message;
  }
  return err instanceof Error ? err.message : String(err);
}

async function main(): Promise<void> {
  const banner = byId("banner", HTMLDivElement);
  let circuit: CircuitSummary, table: NeuronTable;
  try {
    let health;
    [circuit, table, health] = await Promise.all([api.circuit(), api.neurons(), api.health()]);
    setupApiKey(api, health.auth_required);
  } catch (err) {
    banner.textContent = `Cannot reach the backend (${message(err)}). ` +
      "Start it from the repository root with: uvicorn backend.app.main:app --reload";
    banner.hidden = false;
    return;
  }

  byId("circuit-info", HTMLParagraphElement).textContent =
    `${circuit.neurons.toLocaleString()} neurons \u00b7 ${circuit.fast_synapses.toLocaleString()} synapses \u00b7 ` +
    `${circuit.plastic_synapses.toLocaleString()} plastic`;

  // Brain regions fix the scene frame (the whole brain fills the view); without them
  // the neurons do. Both are in FlyWire coordinates when the circuit is real.
  const [regions, catalog] = await Promise.all([
    circuit.anatomy?.regions ? api.regions().catch(() => null) : Promise.resolve(null),
    circuit.odours_loaded ? api.odourCatalog().catch(() => []) : Promise.resolve([]),
  ]);
  const sceneFrame = regions?.regions.length ? regionFrame(regions) : neuronFrame(table);
  const viewer = new BrainViewer(byId("viewer", HTMLDivElement), table, sceneFrame);
  if (regions) viewer.setRegions(regions);
  const activity = new ActivityBuffer(table.count);
  renderLegend(byId("legend", HTMLDivElement), circuit.groups, (g, visible) => viewer.setGroupVisible(g, visible),
               (g) => void showGroup(g));
  byId("reset-view", HTMLButtonElement).addEventListener("click", () => viewer.resetView());

  // ---- what the 3D view draws; neuron shapes arrive later (a few MB)
  const viewerStatus = byId("viewer-status", HTMLParagraphElement);
  const displayRoot = byId("display-options", HTMLDivElement);
  const display: DisplayOption[] = regions ? [
    { label: "Brain regions", title: "FlyWire's neuropil outlines", checked: true,
      onChange: (on) => viewer.setRegionsVisible(on) },
    { label: "Region names", title: "names of the regions on the odour pathway", checked: true,
      onChange: (on) => viewer.setLabelsVisible(on) },
  ] : [];
  renderDisplayOptions(displayRoot, display);
  if (circuit.anatomy?.morphology) {
    viewerStatus.hidden = false;
    viewerStatus.textContent = "Loading neuron shapes\u2026";
    api.morphology((bytes) => {
      viewerStatus.textContent = `Loading neuron shapes\u2026 ${(bytes / 1e6).toFixed(1)} MB`;
    }).then((buffer) => {
      viewer.setMorphology(decodeMorphology(buffer));
      viewerStatus.hidden = true;
      display.push({ label: "Neuron shapes", title: "off: one dot per neuron (cell body)", checked: true,
                     onChange: (on) => viewer.setShapesVisible(on) });
      renderDisplayOptions(displayRoot, display);
    }).catch((err: unknown) => {
      viewerStatus.textContent = `Neuron shapes unavailable (${message(err)}); showing cell bodies.`;
      setTimeout(() => { viewerStatus.hidden = true; }, 6000);
    });
  }

  const results = byId("results", HTMLDivElement);
  const history = byId("history", HTMLSelectElement);
  const cancelButton = byId("cancel-button", HTMLButtonElement);
  const sweepCancel = byId("sweep-cancel", HTMLButtonElement);
  let player: SpikePlayer | null = null;
  let current: ExperimentDetail | null = null;
  // Learned weights are only known after training, so MBONs keep their
  // normal color during the pre-test and training phases of the replay.
  let learnedFrom: number | null = null;
  let showingLearned = false;
  let speed = 1;
  let polling: AbortController | null = null;

  const timeline = new Timeline(byId("timeline", HTMLDivElement), {
    onSeek: (t) => {
      if (!player) return;
      player.seek(t);
      activity.reset();
    },
    onToggle: () => player?.toggle(),
    onSpeed: (s) => {
      speed = s;
      if (player) player.speed = s;
    },
  });

  async function refreshHistory(): Promise<void> {
    try {
      renderHistory(history, await api.experiments(), current?.id ?? null);
    } catch {
      // the list is a convenience; ignore failures
    }
  }

  // Declared before use by load() so playback errors can be shown on the form.
  // Presets and lesion options are optional extras: the form works without them.
  const [presets, lesionOptions] = await Promise.all([
    api.protocols().catch(() => []),
    api.lesionOptions().catch(() => ({ groups: [], cell_types: [] })),
  ]);
  const form: ExperimentForm = new ExperimentForm(byId("experiment-form", HTMLFormElement), {
    odoursAvailable: circuit.odours_loaded,
    defaultGain: typeof circuit.default_params?.graded_gain === "number" ? circuit.default_params.graded_gain : undefined,
    presets,
    lesionOptions,
    catalog,
    similarity: async (a, b) => (await api.odourSimilarity(a, b)).similarity,
    onSubmit: async (req) => {
      polling?.abort();
      polling = new AbortController();
      form.setBusy(true);
      form.setStatus("Submitting\u2026");
      const started = performance.now();
      const elapsedS = () => (performance.now() - started) / 1000;
      try {
        const job = await api.submitConditioning(req);
        showCancel(cancelButton, () => api.cancelExperiment(job.id).then(() => undefined), form.setStatus.bind(form));
        const detail = await api.waitForExperiment(job.id, {
          signal: polling.signal,
          onUpdate: (d) => form.setStatus(describeProgress(d, elapsedS())),
        });
        // a stored identical experiment comes back finished at once
        form.setStatus(job.status === "done" ? "Identical experiment found; showing its stored result."
          : `Finished in ${Math.round(elapsedS())} s. Playing back.`);
        load(detail);
      } catch (err) {
        if (err instanceof CancelledError) form.setStatus("Cancelled.");
        else if ((err as Error).name !== "AbortError") form.setStatus(message(err), "error");
      } finally {
        cancelButton.hidden = true;
        form.setBusy(false);
        void refreshHistory();
      }
    },
  });

  // ---- connection explorer: click a neuron (or a group's name) to see what it connects to
  const neuronPanel = byId("neuron-panel", HTMLElement);
  const codexLinks = !circuit.circuit_dir.includes("synthetic");      // real FlyWire ids only
  let selected: number | null = null;
  let minSynapses = 3;
  let neuronRequest = 0;                       // ignore answers that arrive after a newer click
  let connectivity: GroupConnection[] | null = null;
  const anchor = (i: number) => viewer.anchor(i);

  function clearFocus(): void {
    viewer.setFocus(null);
    viewer.setLinks([]);
  }

  async function showNeuron(index: number | null): Promise<void> {
    selected = index;
    viewer.select(index);
    const ticket = ++neuronRequest;
    if (index === null) {
      neuronPanel.hidden = true;
      clearFocus();
      return;
    }
    let conns: NeuronConnections | "loading" = "loading";
    let detail: Awaited<ReturnType<typeof api.neuron>> | null = null;
    let act: Awaited<ReturnType<typeof api.neuronActivity>> | null | "loading" = null;
    const draw = () => {
      if (ticket !== neuronRequest || !detail) return;
      const extra = connectionControls(conns, minSynapses, MAX_LINKS, (n) => {
        minSynapses = n;
        void showNeuron(index);
      });
      renderNeuron(neuronPanel, detail, act, { codexLinks, onClose: () => void showNeuron(null), extra });
    };
    try {
      const exp = current?.result && current.status === "done" ? current : null;
      const connsRequest = api.connections(index, minSynapses).then((c) => {
        if (ticket !== neuronRequest) return;
        conns = c;
        viewer.setFocus(neuronRoles(index, c));
        viewer.setLinks(neuronLinks(index, c, anchor, MAX_LINKS));
        draw();
      });
      detail = await api.neuron(index);
      act = exp ? "loading" : null;
      draw();
      if (exp) {
        act = await api.neuronActivity(exp.id, index).catch(() => null);
        draw();
      }
      await connsRequest;
    } catch (err) {
      if (ticket === neuronRequest) {
        neuronPanel.replaceChildren(document.createTextNode(`Neuron ${index}: ${message(err)}`));
        neuronPanel.hidden = false;
      }
    }
  }

  async function showGroup(group: string): Promise<void> {
    selected = null;
    viewer.select(null);
    const ticket = ++neuronRequest;
    try {
      connectivity ??= await api.connectivity();
      if (ticket !== neuronRequest) return;
      viewer.setFocus(groupRoles(group, table.group, connectivity));
      viewer.setLinks(groupLinks(group, connectivity, groupCentres(table.group, anchor)));
      neuronPanel.classList.remove("right");
      renderGroup(neuronPanel, group, circuit.groups[group] ?? 0, groupPartners(group, connectivity),
                  () => void showNeuron(null));
    } catch (err) {
      form.setStatus(message(err), "error");
    }
  }

  viewer.onPick((index, side) => {
    neuronPanel.classList.toggle("right", side === "left");    // open away from the clicked neuron
    void showNeuron(index);
  });

  /** A's results, with a "Compare with…" menu of the other finished experiments. */
  function showResults(detail: ExperimentDetail): void {
    renderResults(results, detail);
    results.append(downloadLinks(api.exportUrls(detail.id)));
    void api.experiments().then((list) => {
      if (current?.id !== detail.id) return;                 // another experiment was opened meanwhile
      const menu = compareMenu(list, detail.id, (otherId) => {
        void api.experiment(otherId).then((other) => {
          if (current?.id === detail.id && other.result) {
            renderComparison(results, detail, other, () => showResults(detail));
          }
        }).catch((err) => form.setStatus(message(err), "error"));
      });
      if (menu) results.prepend(menu);
    }).catch(() => undefined);                               // the menu is optional
  }

  function load(detail: ExperimentDetail): void {
    const res = detail.result;
    if (!res) return;
    sweepPolling?.abort();          // the results panel now shows this experiment
    shownSweep = null;
    current = detail;
    player?.dispose();
    activity.reset();
    player = new SpikePlayer(
      res.duration_ms,
      (t0, t1, signal) => api.spikes(detail.id, t0, t1, undefined, 500_000, signal),
      { onError: (err) => form.setStatus(`Playback stopped: ${message(err)}`, "error") },
    );
    player.speed = speed;
    timeline.setExperiment(res.timeline, res.duration_ms);
    showResults(detail);
    // Learned weights are the final ones: show them from the "after" readout on
    // (for most protocols the end of training; for extinction, after extinction).
    learnedFrom = res.readout_after_ms;
    viewer.setSilenced(res.lesioned);
    showingLearned = false;
    viewer.setMbonWeights(null);
    if (selected !== null) void showNeuron(selected);   // its activity in the new experiment
    player.play();
  }

  // ---------------------------------------------------------------- sweeps
  let sweepPolling: AbortController | null = null;
  let shownSweep: SweepDetail | null = null;
  let sweepMetric = Object.keys(METRIC_LABELS)[0]!;

  function showSweep(detail: SweepDetail): void {
    shownSweep = detail;
    renderSweep(results, detail, sweepMetric, api.sweepCsvUrl(detail.id), (m) => {
      sweepMetric = m;
      if (shownSweep) showSweep(shownSweep);
    });
  }

  async function refreshSweeps(): Promise<void> {
    try {
      sweepPanel.setHistory(await api.sweeps(), shownSweep?.id ?? null);
    } catch {
      // convenience only
    }
  }

  async function followSweep(id: string): Promise<void> {
    sweepPolling?.abort();
    sweepPolling = new AbortController();
    sweepPanel.setBusy(true);
    showCancel(sweepCancel, async () => {
      const r = await api.cancelSweep(id);
      sweepPanel.setStatus(`Cancelling: ${r.cancelled} won't run, ${r.stopping} stopping\u2026`);
    }, sweepPanel.setStatus.bind(sweepPanel));
    try {
      const done = await api.waitForSweep(id, {
        signal: sweepPolling.signal,
        onSweep: (d) => {
          const finished = d.counts.done + d.counts.failed + (d.counts.cancelled ?? 0);
          sweepPanel.setStatus(`${finished} of ${d.total} experiments finished`);
          showSweep(d);
        },
      });
      const outcome = sweepOutcome(done);
      sweepPanel.setStatus(outcome.text, outcome.kind);
    } catch (err) {
      if ((err as Error).name !== "AbortError") sweepPanel.setStatus(message(err), "error");
    } finally {
      sweepCancel.hidden = true;
      sweepPanel.setBusy(false);
      void refreshSweeps();
    }
  }

  const sweepPanel = new SweepPanel({
    getBase: () => form.read(),
    onSubmit: async (req) => {
      sweepPanel.setStatus("Submitting\u2026");
      try {
        const created = await api.createSweep(req);
        await followSweep(created.id);
      } catch (err) {
        sweepPanel.setStatus(message(err), "error");
      }
    },
    onPick: (id) => void followSweep(id),
    lesionOptions,
  });
  void refreshSweeps();

  history.addEventListener("change", async () => {
    if (!history.value) return;
    try {
      const detail = await api.experiment(history.value);
      if (detail.result) load(detail);
    } catch (err) {
      form.setStatus(message(err), "error");
    }
  });
  void refreshHistory();

  window.addEventListener("keydown", (event) => {
    const target = event.target as HTMLElement | null;
    if (event.key === "Escape" && !target?.closest("input, select, textarea")) void showNeuron(null);
    if (event.code === "Space" && player && !target?.closest("input, select, textarea, button")) {
      event.preventDefault();
      player.toggle();
    }
  });

  let last = performance.now();
  const frame = (now: number) => {
    const dt = Math.min(now - last, 100);          // cap after tab switches
    last = now;
    if (player) {
      player.advance(dt, (neuron) => activity.spike(neuron));
      timeline.setTime(player.time, { playing: player.playing, buffering: player.playing && player.buffering });
      const learned = learnedFrom !== null && player.time >= learnedFrom;
      if (learned !== showingLearned && current?.result) {
        viewer.setMbonWeights(learned ? current.result.mbon_weights : null);
        showingLearned = learned;
      }
    }
    activity.decay(dt);
    viewer.update(activity.values);
    viewer.render();
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

/** The frame that fits the whole brain (all regions). */
function regionFrame(regions: BrainRegions) {
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  for (const r of regions.regions) {
    const b = boundsOf(r.vertices);
    for (let a = 0; a < 3; a++) {
      lo[a] = Math.min(lo[a]!, b.lo[a]!);
      hi[a] = Math.max(hi[a]!, b.hi[a]!);
    }
  }
  return frameFromBounds(lo, hi);
}

void main();
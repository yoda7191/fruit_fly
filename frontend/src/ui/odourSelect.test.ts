import { describe, expect, it, vi } from "vitest";

import { describeSimilarity, ODOUR_PAIRS } from "./experimentForm";
import { connectionControls, renderGroup } from "./neuronPanel";
import { coverageText, groupOdours, OdourSelect, type OdourOption } from "./odourSelect";

const ODOURS: OdourOption[] = [
  { name: "3-octanol", group: "alcohols", coverage: 0.57 },
  { name: "1-octanol", group: "alcohols", coverage: 0.69 },
  { name: "4-methylcyclohexanol", group: "alcohols", coverage: 0.45 },
  { name: "ethyl acetate", group: "esters", coverage: 0.94 },
  { name: "octyl acetate", group: "esters", coverage: 0.2 },
  { name: "mystery", group: "unclassified", coverage: 0.9 },
  { name: "hexanoic acid", group: "acids", coverage: 0.8 },
];

describe("odour menu content", () => {
  it("lists well-measured odours by class, best measured first, unclassified last", () => {
    const groups = groupOdours(ODOURS, "", true);
    expect(groups.map((g) => g.group)).toEqual(["alcohols", "acids", "esters", "unclassified"]);
    expect(groups[0]!.items.map((o) => o.name)).toEqual(["1-octanol", "3-octanol"]);   // 0.45 and 0.2 hidden
  });

  it("lists everything when asked", () => {
    expect(groupOdours(ODOURS, "", false).flatMap((g) => g.items)).toHaveLength(ODOURS.length);
    // the chosen odour is listed even when it is poorly measured
    expect(groupOdours(ODOURS, "", true, "Octyl Acetate").flatMap((g) => g.items.map((o) => o.name)))
      .toContain("octyl acetate");
  });

  it("searches every odour, names starting with the text first", () => {
    const groups = groupOdours(ODOURS, "oct", true);
    expect(groups.find((g) => g.group === "esters")!.items.map((o) => o.name)).toEqual(["octyl acetate"]);
    expect(groupOdours(ODOURS, "OCTANOL", true)[0]!.items.map((o) => o.name)).toEqual(["1-octanol", "3-octanol"]);
    expect(groupOdours(ODOURS, "zzz", false)).toEqual([]);
  });

  it("describes coverage", () => {
    expect(coverageText(0.574)).toBe("57% of receptors measured");
    expect(coverageText(null)).toBe("");
  });
});

describe("OdourSelect", () => {
  function setup() {
    document.body.innerHTML = `<div id="f"><input id="cs-plus" value="3-octanol"></div>`;
    const onPick = vi.fn();
    const select = new OdourSelect(document.getElementById("cs-plus") as HTMLInputElement, () => ODOURS, onPick);
    const menu = document.querySelector<HTMLElement>(".odour-menu")!;
    return { select, menu, onPick, input: select.input };
  }

  it("opens on focus with the well-measured odours and shows the chosen odour's class", () => {
    const { menu, input } = setup();
    expect(document.querySelector(".odour-meta")!.textContent).toBe("alcohols · 57% of receptors measured");
    expect(menu.hidden).toBe(true);
    input.dispatchEvent(new Event("focus"));
    expect(menu.hidden).toBe(false);
    expect(menu.querySelectorAll(".odour-option")).toHaveLength(5);
    expect(menu.querySelector(".odour-option.current")!.textContent).toContain("3-octanol");
    expect(menu.textContent).toContain("5 of 7");
    const well = menu.querySelector<HTMLInputElement>("input[type=checkbox]")!;
    well.click();
    expect(menu.querySelectorAll(".odour-option")).toHaveLength(7);
  });

  it("filters while typing and picks with the keyboard", () => {
    const { menu, input, onPick } = setup();
    const changed = vi.fn();
    input.addEventListener("change", changed);
    input.value = "acet";
    input.dispatchEvent(new Event("input"));
    expect([...menu.querySelectorAll(".odour-name")].map((n) => n.textContent)).toEqual(["ethyl acetate", "octyl acetate"]);
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown" }));
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown" }));
    const enter = new KeyboardEvent("keydown", { key: "Enter", cancelable: true });
    input.dispatchEvent(enter);
    expect(enter.defaultPrevented).toBe(true);                  // the form isn't submitted
    expect(input.value).toBe("octyl acetate");
    expect(onPick).toHaveBeenCalledWith("octyl acetate");
    expect(changed).toHaveBeenCalled();
    expect(menu.hidden).toBe(true);
    expect(document.querySelector(".odour-meta")!.classList.contains("warn")).toBe(true);   // 20% measured
  });

  it("picks by click, and corrects the case of a typed name", async () => {
    const { menu, input, select } = setup();
    input.dispatchEvent(new Event("focus"));
    (menu.querySelector<HTMLElement>(".odour-option")!).click();
    expect(select.value).toBe("1-octanol");
    input.value = "ETHYL ACETATE";
    input.dispatchEvent(new Event("blur"));
    await new Promise((r) => setTimeout(r, 150));
    expect(input.value).toBe("ethyl acetate");
    input.value = "not an odour";
    input.dispatchEvent(new Event("input"));
    expect(menu.textContent).toContain("No odour matches");
  });

  it("names a pair's similarity in plain words", () => {
    expect(describeSimilarity(0.91)).toBe("Receptor patterns very similar: hard to tell apart (correlation 0.91).");
    expect(describeSimilarity(-0.49)).toContain("very different");
    expect(describeSimilarity(-0.49)).toContain("−0.49");
    expect(describeSimilarity(null)).toContain("unknown");
    expect(ODOUR_PAIRS.map((p) => p.label)).toEqual(["Classic pair", "Similar pair", "Very different"]);
  });
});

describe("connection panels", () => {
  it("summarises what is drawn and reports the synapse threshold", () => {
    const onMin = vi.fn();
    const c = { index: 0, min_synapses: 3, total_inputs: 120, total_outputs: 1, inputs: new Array(120).fill(
      { index: 1, synapses: 5, sign: "excitatory" }), outputs: [{ index: 2, synapses: 4, sign: "excitatory" as const }],
      dopamine_to: [], dopamine_from: [7, 8] };
    const root = connectionControls(c, 3, 60, onMin);
    expect(root.textContent).toContain("strongest 60 of 120 inputs, 1 output, dopamine from 2 DANs");
    const slider = root.querySelector<HTMLInputElement>("input[type=range]")!;
    slider.value = "10";
    slider.dispatchEvent(new Event("change"));
    expect(onMin).toHaveBeenCalledWith(10);
    expect(connectionControls("loading", 3, 60, onMin).textContent).toContain("Loading connections");
  });

  it("lists a group's partner groups", () => {
    const root = document.createElement("aside");
    const onClose = vi.fn();
    renderGroup(root, "KC", 5177, {
      inputs: [{ pre: "ALPN", post: "KC", synapses: 329394, connections: 27848, sign: "excitatory" }],
      outputs: [{ pre: "DAN_PAM", post: "MBON", synapses: 0, connections: 1709, sign: "dopamine" }],
    }, onClose);
    expect(root.querySelector("h3")!.textContent).toBe("Kenyon cells");
    expect(root.textContent).toContain("5,177 neurons");
    expect(root.textContent).toContain("projection neurons");
    expect(root.textContent).toContain("1,709 pairs");
    root.querySelector<HTMLButtonElement>(".close")!.click();
    expect(onClose).toHaveBeenCalled();
  });
});

// odourSelect.ts — choosing an odour from a menu instead of typing its name.
//
// The odour's text field stays (typing filters the menu), and a menu opens under it:
// odours grouped by chemical class, each with a bar for how much of it DoOR measured.
// By default only well-measured odours are listed; typing searches all of them.

import { el } from "./dom";

export interface OdourOption {
  name: string;
  group: string;                  // chemical class, or "random patterns"
  coverage: number | null;        // share of receptors measured; null for random odours
}

/** Odours with at least this coverage count as well measured. Below it, most receptor
 *  responses are unknown and filled in as "no response" by the model. */
export const WELL_MEASURED = 0.5;

const LAST = ["other", "unclassified"];

/**
 * The menu's content: matching odours grouped by class. With text, every odour whose
 * name contains it (names starting with it first); without, all or only well-measured
 * ones (and the `current` odour, so it can be seen in the list). Classes with more odours come first, "other" and "unclassified" last; within
 * a class, best measured first.
 */
export function groupOdours(items: OdourOption[], text: string, wellOnly: boolean, current = ""):
    { group: string; items: OdourOption[] }[] {
  const q = text.trim().toLowerCase();
  const chosen = current.toLowerCase();
  const shown = items.filter((o) => q ? o.name.toLowerCase().includes(q)
                                      : !wellOnly || o.coverage === null || o.coverage >= WELL_MEASURED ||
                                        o.name.toLowerCase() === chosen);
  const groups = new Map<string, OdourOption[]>();
  for (const o of shown) {
    if (!groups.has(o.group)) groups.set(o.group, []);
    groups.get(o.group)!.push(o);
  }
  const starts = (o: OdourOption) => (q && o.name.toLowerCase().startsWith(q) ? 0 : 1);
  const rank = (g: string) => (LAST.includes(g) ? LAST.indexOf(g) + 1 : 0);
  return [...groups.entries()]
    .sort(([a, x], [b, y]) => rank(a) - rank(b) || y.length - x.length || a.localeCompare(b))
    .map(([group, list]) => ({
      group,
      items: list.sort((a, b) => starts(a) - starts(b) || (b.coverage ?? 0) - (a.coverage ?? 0) ||
                                  a.name.localeCompare(b.name)),
    }));
}

/** "57% measured" / "" for random odours. */
export function coverageText(coverage: number | null): string {
  return coverage === null ? "" : `${Math.round(coverage * 100)}% of receptors measured`;
}

export class OdourSelect {
  private readonly wrapper: HTMLDivElement;
  private readonly menu: HTMLDivElement;
  private readonly list: HTMLDivElement;
  private readonly meta: HTMLDivElement;
  private readonly wellOnly: HTMLInputElement;
  private readonly countText: HTMLSpanElement;
  private options: HTMLElement[] = [];        // rendered option rows, in order
  private active = -1;

  constructor(readonly input: HTMLInputElement, private readonly source: () => OdourOption[],
              private readonly onPick: (name: string) => void = () => {}) {
    this.wrapper = el("div", { class: "odour-select" });
    input.replaceWith(this.wrapper);
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("list");
    input.placeholder = "choose or type to search";

    this.wellOnly = el("input");
    this.wellOnly.type = "checkbox";
    this.wellOnly.checked = true;
    this.countText = el("span", { class: "muted small" });
    this.list = el("div", { class: "odour-list" });
    this.list.setAttribute("role", "listbox");
    this.menu = el("div", { class: "odour-menu" }, [
      el("div", { class: "odour-menu-head" }, [
        el("label", { class: "inline", title: `at least ${WELL_MEASURED * 100}% of receptors measured in DoOR` },
           [this.wellOnly, " well-measured only"]),
        this.countText,
      ]),
      this.list,
    ]);
    this.menu.hidden = true;
    this.meta = el("div", { class: "odour-meta muted small" });
    this.wrapper.append(el("div", { class: "odour-anchor" }, [input, this.menu]), this.meta);

    // keep focus in the field while the menu is clicked
    this.menu.addEventListener("mousedown", (e) => {
      if (e.target !== this.wellOnly) e.preventDefault();
    });
    this.wellOnly.addEventListener("change", () => {
      this.render();
      input.focus();
    });
    input.addEventListener("focus", () => this.open(true));
    input.addEventListener("click", () => this.open(true));
    input.addEventListener("input", () => this.open(false));
    input.addEventListener("blur", () => setTimeout(() => this.close(), 120));
    input.addEventListener("keydown", (e) => this.key(e));
    this.showMeta();
  }

  get value(): string {
    return this.input.value.trim();
  }

  set value(name: string) {
    this.input.value = name;
    this.showMeta();
  }

  /** Refresh after the odour list changed (e.g. another odour source). */
  refresh(): void {
    this.showMeta();
    if (!this.menu.hidden) this.render();
  }

  private open(showAll: boolean): void {
    this.menu.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
    this.render(showAll ? "" : this.input.value);
  }

  private close(): void {
    this.menu.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    // a typed name that matches an odour, in any case, becomes that odour's name
    const typed = this.value.toLowerCase();
    const match = this.source().find((o) => o.name.toLowerCase() === typed);
    if (match && match.name !== this.input.value) this.input.value = match.name;
    this.showMeta();
  }

  private pick(name: string): void {
    this.value = name;
    this.menu.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    this.input.dispatchEvent(new Event("change", { bubbles: true }));
    this.onPick(name);
  }

  private key(e: KeyboardEvent): void {
    if (this.menu.hidden && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      this.open(true);
      e.preventDefault();
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!this.options.length) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      this.setActive((this.active + step + this.options.length) % this.options.length);
    } else if (e.key === "Enter" && !this.menu.hidden) {
      e.preventDefault();                                   // don't submit the form
      const row = this.options[this.active] ?? (this.options.length === 1 ? this.options[0] : undefined);
      if (row?.dataset.name) this.pick(row.dataset.name);
    } else if (e.key === "Escape") {
      this.close();
    }
  }

  private setActive(k: number): void {
    this.options[this.active]?.classList.remove("active");
    this.active = k;
    const row = this.options[k];
    if (!row) return;
    row.classList.add("active");
    this.input.setAttribute("aria-activedescendant", row.id);
    row.scrollIntoView?.({ block: "nearest" });
  }

  private render(text = ""): void {
    const all = this.source();
    const groups = groupOdours(all, text, this.wellOnly.checked, this.value);
    const count = groups.reduce((s, g) => s + g.items.length, 0);
    this.countText.textContent = text ? `${count} matching` : `${count} of ${all.length}`;
    this.wellOnly.parentElement!.hidden = all.every((o) => o.coverage === null);
    this.options = [];
    this.active = -1;
    const current = this.value.toLowerCase();
    const rows = groups.flatMap(({ group, items }) => [
      el("div", { class: "odour-group", text: `${group} (${items.length})` }),
      ...items.map((o) => {
        const row = el("div", { class: "odour-option", title: coverageText(o.coverage) || o.name }, [
          el("span", { class: "odour-name", text: o.name }),
          o.coverage === null ? null
            : el("span", { class: "coverage", title: coverageText(o.coverage) },
                 [el("span", { style: `width:${Math.round(o.coverage * 100)}%` })]),
        ]);
        row.id = `${this.input.id || "odour"}-opt-${this.options.length}`;
        row.dataset.name = o.name;
        row.setAttribute("role", "option");
        if (o.name.toLowerCase() === current) row.classList.add("current");
        row.addEventListener("click", () => this.pick(o.name));
        this.options.push(row);
        return row;
      }),
    ]);
    this.list.replaceChildren(...(rows.length ? rows
      : [el("p", { class: "muted small", text: "No odour matches. DoOR names are in English, e.g. “ethyl acetate”." })]));
  }

  private showMeta(): void {
    const o = this.source().find((x) => x.name.toLowerCase() === this.value.toLowerCase());
    this.meta.textContent = o ? [o.group, coverageText(o.coverage)].filter(Boolean).join(" · ") : "";
    const few = !!o && o.coverage !== null && o.coverage < WELL_MEASURED;
    this.meta.classList.toggle("warn", few);
    this.meta.title = few ? "Fewer than half of the receptors were measured for this odour; the model treats "
      + "the unmeasured ones as not responding." : "";
  }
}

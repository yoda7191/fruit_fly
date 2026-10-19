// dom.ts — small DOM helpers. Text always goes through textContent, never
// innerHTML: odour names come from user input, and inserting them as HTML
// would allow script injection (XSS).

type Child = Node | string | null | undefined | false;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: { class?: string; text?: string; title?: string; style?: string } = {},
  children: Child[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (props.class) node.className = props.class;
  if (props.text !== undefined) node.textContent = props.text;
  if (props.title) node.title = props.title;
  if (props.style) node.setAttribute("style", props.style);
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c);
  }
  return node;
}

/** getElementById that checks the element exists and has the expected type. */
export function byId<T extends HTMLElement>(id: string, type: { new (): T }): T {
  const node = document.getElementById(id);
  if (!(node instanceof type)) throw new Error(`#${id} missing or not a ${type.name}`);
  return node;
}

const MINUS = "\u2212";

/** 0.12 -> "+12%", -0.62 -> "−62%", null -> "—". */
export function formatPercent(x: number | null | undefined, signed = true): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "\u2014";
  const pct = Math.round(x * 100);
  if (!signed) return `${pct}%`;
  if (pct > 0) return `+${pct}%`;
  if (pct < 0) return `${MINUS}${Math.abs(pct)}%`;
  return "0%";
}

export function formatNumber(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "\u2014";
  return x.toFixed(digits).replace("-", MINUS);
}
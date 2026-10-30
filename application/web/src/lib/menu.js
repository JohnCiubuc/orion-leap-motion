// Pure logic for the OrionDo menu editor: tree operations and wheel geometry. No Svelte here, so `node --test` loads it.
// A menu is a list of { label, action, args }; a submenu is { label, items: [...] } (no action). Operations take a
// `path` of indices from the root ([] is the root menu). Geometry follows the on-screen overlay (overlay_menu.py):
// slice 0 at the top, clockwise, equal slices, a small gap between them.

export const MAX_ITEMS = 12; // more slices than this are unreadable
export const MAX_DEPTH = 4; // submenu levels below the root the editor will build
// The pie's look, and the hue (degrees) of each skin's accent as shipped. Mirrors the skins in orion/menu_skins (HUE there);
// an unknown name draws with the first.
export const SKINS = [
  { id: "aurora", label: "Aurora", note: "Soft blue glass", hue: 218 },
  { id: "paper", label: "Paper", note: "Flat, high contrast", hue: 11 },
  { id: "reticle", label: "Reticle", note: "HUD linework", hue: 176 },
  { id: "halo", label: "Halo", note: "Thin ring, labels outside", hue: 96 },
  { id: "ember", label: "Ember", note: "Warm glow", hue: 25 },
  { id: "terminal", label: "Terminal", note: "Monospace", hue: 135 },
  { id: "orbit", label: "Orbit", note: "Arcs on a track", hue: 265 },
  { id: "frost", label: "Frost", note: "Pale glass", hue: 215 },
  { id: "compass", label: "Compass", note: "Bezel and needle", hue: 40 },
  { id: "neon", label: "Neon", note: "Glowing tubes", hue: 313 },
  { id: "petal", label: "Petal", note: "Soft petals", hue: 44 },
  { id: "constellation", label: "Constellation", note: "Stars and lines", hue: 223 },
  { id: "topographic", label: "Topographic", note: "Contour lines", hue: 135 },
  { id: "catppuccin", label: "Catppuccin", note: "Four flavours", palette: true }, // a fixed palette: flavour and accent instead of a hue
];
// Catppuccin's accents per flavour (orion/menu_skins/catppuccin.py has the full palette): what the accent swatches show.
export const ACCENTS = ["rosewater", "flamingo", "pink", "mauve", "red", "maroon", "peach", "yellow", "green", "teal", "sky", "sapphire", "blue", "lavender"];
export const FLAVORS = {
  latte: "dc8a78 dd7878 ea76cb 8839ef d20f39 e64553 fe640b df8e1d 40a02b 179299 04a5e5 209fb5 1e66f5 7287fd",
  frappe: "f2d5cf eebebe f4b8e4 ca9ee6 e78284 ea999c ef9f76 e5c890 a6d189 81c8be 99d1db 85c1dc 8caaee babbf1",
  macchiato: "f4dbd6 f0c6c6 f5bde6 c6a0f6 ed8796 ee99a0 f5a97f eed49f a6da95 8bd5ca 91d7e3 7dc4e4 8aadf4 b7bdf8",
  mocha: "f5e0dc f2cdcd f5c2e7 cba6f7 f38ba8 eba0ac fab387 f9e2af a6e3a1 94e2d5 89dceb 74c7ec 89b4fa b4befe",
};
export const GAP = (3 * Math.PI) / 180;

// ── Geometry (angles in radians, clockwise from the top; SVG y points down) ──

export const sliceCenter = (i, n) => (i * 2 * Math.PI) / n; // i and n may be fractional while animating

// Slice widths are proportional to each item's `weight` (default 1, clamped like oriondo.py _weights). The root centres
// the first item on the top. A submenu puts a free slot of weight 1 first, facing its parent (`back`, degrees clockwise
// from the top), and fills the rest clockwise from it. The overlay lays out by the same rule: oriondo.py slot_layout
// and menu_anim.py slot_layout.
export const MIN_WEIGHT = 0.25; // the smallest slice the editor's edge drag leaves; the engine accepts 0.1 to 4
export const weightOf = (item) => {
  const w = Number(item?.weight ?? 1);
  return Number.isFinite(w) ? Math.min(Math.max(w, 0.1), 4) : 1;
};

/** [{ center, span }] in degrees for the children (not the free slot). `wrap: false` keeps the centres increasing. */
export function slotSpans(weights, back = null, wrap = true) {
  const ws = back == null ? weights : [1, ...weights];
  const total = ws.reduce((a, b) => a + b, 0);
  const sizes = ws.map((w) => (360 * w) / total);
  let centre = back ?? 0;
  const out = sizes.map((size, k) => {
    if (k) centre += (sizes[k - 1] + size) / 2;
    return { center: wrap ? centre % 360 : centre, span: size };
  });
  return back == null ? out : out.slice(1);
}
export const slotAngles = (n, back = null) => slotSpans(Array(n).fill(1), back).map((s) => s.center);
export const slotLayout = (n, back = null) => (back == null ? { slots: n, offset: 0 } : { slots: n + 1, offset: 1 });
/** Centre of slot `i` of `slots`, rotated by `rotate` radians (the back angle, for a submenu). */
export const slotCenter = (i, slots, rotate = 0) => sliceCenter(i, slots) + rotate;

const point = (r, a, cx, cy) => `${(cx + r * Math.sin(a)).toFixed(3)} ${(cy - r * Math.cos(a)).toFixed(3)}`;

/** A slice of `span` radians around `c` (radians clockwise from the top). */
export function wedgePath(c, span, rIn, rOut, cx = 0, cy = 0) {
  const half = Math.max(span / 2 - GAP / 2, 0.01);
  const large = 2 * half > Math.PI ? 1 : 0; // a lone slice spans more than half the ring
  return `M ${point(rOut, c - half, cx, cy)} A ${rOut} ${rOut} 0 ${large} 1 ${point(rOut, c + half, cx, cy)} `
    + `L ${point(rIn, c + half, cx, cy)} A ${rIn} ${rIn} 0 ${large} 0 ${point(rIn, c - half, cx, cy)} Z`;
}

export const arcPath = (i, n, rIn, rOut, cx = 0, cy = 0, rotate = 0) =>
  wedgePath(slotCenter(i, n, rotate), (2 * Math.PI) / n, rIn, rOut, cx, cy);

/** Centre (radians) of fractional slot `p`, gliding between the centres of `lay` (slotSpans in radians, unwrapped). */
export function centerAt(p, lay) {
  const k = Math.min(Math.max(Math.floor(p), 0), lay.length - 1);
  const next = k + 1 < lay.length ? lay[k + 1].center - lay[k].center : lay[k].span;
  return lay[k].center + (p - k) * next;
}

/** Inverse of centerAt: the fractional slot whose centre is at `angle` (radians clockwise from the top). */
export function posAt(angle, lay) {
  const TAU = 2 * Math.PI, start = lay[0].center - lay[0].span / 2;
  const a = start + ((((angle - start) % TAU) + TAU) % TAU);
  let k = 0;
  while (k + 1 < lay.length && lay[k + 1].center <= a) k++;
  const next = k + 1 < lay.length ? lay[k + 1].center - lay[k].center : lay[k].span;
  return k + (a - lay[k].center) / next;
}

const angleOf = (x, y) => (Math.atan2(x, -y) + 2 * Math.PI) % (2 * Math.PI);

export function sliceAt(x, y, n, rIn) {
  if (Math.hypot(x, y) < rIn) return null;
  const w = (2 * Math.PI) / n;
  return Math.floor((angleOf(x, y) + w / 2) / w) % n;
}

/** The slot a dragged slice is over; near the hub (or the back gap) the angle is meaningless, so it keeps where it was. */
export function dragSlot(x, y, n, rIn, prev, back = null, weights = Array(n).fill(1)) {
  if (Math.hypot(x, y) < rIn) return prev;
  const deg = (Math.atan2(x, -y) * 180) / Math.PI;
  const gap = back == null ? [] : [{ center: back, span: 360 / (weights.reduce((a, b) => a + b, 0) + 1) }];
  const slots = [...gap, ...slotSpans(weights, back)];
  const miss = ({ center, span }) => Math.abs(((deg - center + 540) % 360) - 180) - span / 2; // degrees outside the slot
  const best = slots.reduce((m, s, k) => (miss(s) < miss(slots[m]) ? k : m), 0);
  return best < gap.length ? prev : best - gap.length;
}

// ── Resizing: dragging the border between two slices ──

/** Borders that can be dragged, as [a, b] slice pairs: neighbours, and the last with the first at the root. The free slot of a submenu is fixed. */
export const edges = (n, back = null) => [
  ...Array.from({ length: Math.max(n - 1, 0) }, (_, i) => [i, i + 1]),
  ...(back == null && n > 1 ? [[n - 1, 0]] : []),
];

/** The border after slice `a`, in radians (`lay` as in centerAt). */
export const edgeAngle = (lay, a) => lay[a].center + lay[a].span / 2;

/** New weights [wa, wb] when the border between a and b is dragged to `angle`; together they keep their sum, so no other slice moves. */
export function edgeWeights(lay, weights, a, b, angle) {
  const TAU = 2 * Math.PI, start = lay[a].center - lay[a].span / 2, width = lay[a].span + lay[b].span;
  const rel = (((angle - start) % TAU) + TAU) % TAU;
  const sum = weights[a] + weights[b], lo = Math.min(MIN_WEIGHT, sum / 2) / sum;
  const frac = rel > width ? (rel - width < TAU - rel ? 1 : 0) : rel / width; // past the pair: stick to the nearer end
  const wa = Math.round(sum * Math.min(Math.max(frac, lo), 1 - lo) * 100) / 100;
  return [wa, Math.round((sum - wa) * 100) / 100];
}

// ── Tree operations ──

export function listAt(items, path) {
  let list = items;
  for (const i of path) list = list?.[i]?.items;
  return list;
}

export function addItem(items, path, item, at) {
  let list = items;
  for (const i of path) {
    if (!list?.[i]) return false;
    list = list[i].items ??= [];
  }
  if (list.length >= MAX_ITEMS) return false;
  list.splice(at ?? list.length, 0, item);
  return true;
}

export const removeItem = (items, path, index) => listAt(items, path)?.splice(index, 1);

export function moveItem(items, path, from, to) {
  const list = listAt(items, path);
  if (list) list.splice(to, 0, ...list.splice(from, 1));
}

export function blankItem(items, path) {
  const used = new Set((listAt(items, path) ?? []).map((i) => String(i.label)));
  let n = 1;
  while (used.has(String(n))) n++;
  return { label: String(n), action: "input.keys", args: {} };
}

// ── Submenus ──

export const isSubmenu = (item) => Array.isArray(item?.items);
export const hasChildren = (item) => isSubmenu(item) && item.items.length > 0;

export function toSubmenu(item) {
  delete item.action;
  delete item.args;
  item.items = [];
}

export function toAction(item) {
  delete item.items;
  item.action = "";
  item.args = {};
}

/** A submenu can be created at `path` (the list being edited) while it stays within the depth limit. */
export const canNest = (path) => path.length < MAX_DEPTH;

/** The longest prefix of `path` where every step is a submenu: a removed or converted item drops back toward the root. */
export function clampPath(items, path) {
  const out = [];
  let list = items;
  for (const i of path) {
    if (!isSubmenu(list?.[i])) break;
    out.push(i);
    list = list[i].items;
  }
  return out;
}

export function crumbs(items, path) {
  const out = [{ label: "Root", path: [] }];
  let list = items;
  const valid = clampPath(items, path);
  valid.forEach((i, k) => {
    out.push({ label: String(list[i].label ?? ""), path: valid.slice(0, k + 1) });
    list = list[i].items;
  });
  return out;
}

/** Back angle (degrees) of the submenu opened from child `index` of a list whose own back angle is `back`. */
export const backAngleFor = (index, n, back = null, weights = Array(n).fill(1)) => (slotSpans(weights, back)[index].center + 180) % 360;

/** Back angle of the list at `path` (null at the root). */
export function backAt(items, path) {
  let list = items, back = null;
  for (const i of path) {
    back = backAngleFor(i, list.length, back, list.map(weightOf));
    list = list[i].items;
  }
  return back;
}

// ── Selection bookkeeping ──

export function selectionAfterMove(sel, from, to) {
  if (sel === from) return to;
  if (from < to && sel > from && sel <= to) return sel - 1;
  if (from > to && sel >= to && sel < from) return sel + 1;
  return sel;
}

/** `count` is the list length after the removal. */
export function selectionAfterRemove(sel, index, count) {
  if (count === 0 || sel < 0) return -1;
  if (sel > index) return sel - 1;
  return Math.min(sel, count - 1);
}

// ── Labels ──

export function fitLabel(label, n) {
  const max = n <= 4 ? 10 : n <= 8 ? 6 : 4;
  const chars = [...String(label ?? "")]; // a hand-edited `label = 1` is a number
  if (!chars.length) return "·";
  return chars.length > max ? chars.slice(0, max - 1).join("") + "…" : chars.join("");
}

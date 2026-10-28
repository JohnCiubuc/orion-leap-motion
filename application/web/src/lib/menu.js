// Pure logic for the OrionDo menu editor: tree operations and wheel geometry. No Svelte here, so `node --test` loads it.
// A menu is a list of { label, action, args }; a future submenu is an `items` list inside an item. Operations take a
// `path` of indices from the root ([] is the root menu). Geometry follows the on-screen overlay (overlay_menu.py):
// slice 0 at the top, clockwise, equal slices, a small gap between them.

export const MAX_ITEMS = 12; // more slices than this are unreadable
export const GAP = (3 * Math.PI) / 180;

// ── Geometry (angles in radians, clockwise from the top; SVG y points down) ──

export const sliceCenter = (i, n) => (i * 2 * Math.PI) / n; // i and n may be fractional while animating

const point = (r, a, cx, cy) => `${(cx + r * Math.sin(a)).toFixed(3)} ${(cy - r * Math.cos(a)).toFixed(3)}`;

export function arcPath(i, n, rIn, rOut, cx = 0, cy = 0) {
  const half = Math.max(Math.PI / n - GAP / 2, 0.01);
  const c = sliceCenter(i, n);
  const large = 2 * half > Math.PI ? 1 : 0; // only a lone slice spans more than half the ring
  return `M ${point(rOut, c - half, cx, cy)} A ${rOut} ${rOut} 0 ${large} 1 ${point(rOut, c + half, cx, cy)} `
    + `L ${point(rIn, c + half, cx, cy)} A ${rIn} ${rIn} 0 ${large} 0 ${point(rIn, c - half, cx, cy)} Z`;
}

const angleOf = (x, y) => (Math.atan2(x, -y) + 2 * Math.PI) % (2 * Math.PI);

export function sliceAt(x, y, n, rIn) {
  if (Math.hypot(x, y) < rIn) return null;
  const w = (2 * Math.PI) / n;
  return Math.floor((angleOf(x, y) + w / 2) / w) % n;
}

/** The slot a dragged slice is over; near the hub the angle is noise, so it keeps where it was. */
export const dragSlot = (x, y, n, rIn, prev) => sliceAt(x, y, n, rIn) ?? prev;

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
  const used = new Set((listAt(items, path) ?? []).map((i) => i.label));
  let n = 1;
  while (used.has(String(n))) n++;
  return { label: String(n), action: "input.keys", args: {} };
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
  const chars = [...label];
  if (!chars.length) return "·";
  return chars.length > max ? chars.slice(0, max - 1).join("") + "…" : label;
}

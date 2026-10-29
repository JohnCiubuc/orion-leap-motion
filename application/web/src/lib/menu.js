// Pure logic for the OrionDo menu editor: tree operations and wheel geometry. No Svelte here, so `node --test` loads it.
// A menu is a list of { label, action, args }; a submenu is { label, items: [...] } (no action). Operations take a
// `path` of indices from the root ([] is the root menu). Geometry follows the on-screen overlay (overlay_menu.py):
// slice 0 at the top, clockwise, equal slices, a small gap between them.

export const MAX_ITEMS = 12; // more slices than this are unreadable
export const MAX_DEPTH = 4; // submenu levels below the root the editor will build
export const GAP = (3 * Math.PI) / 180;

// ── Geometry (angles in radians, clockwise from the top; SVG y points down) ──

export const sliceCenter = (i, n) => (i * 2 * Math.PI) / n; // i and n may be fractional while animating

// A submenu keeps the slot facing its parent free: n children use n + 1 slots, the gap at `back` (degrees clockwise
// from the top) and the children filling the rest clockwise from it. The root has no gap. This is overlay layout:
// oriondo.py slot_angles and menu_anim.py slice_angles use the same rule.
export const slotAngles = (n, back = null) =>
  Array.from({ length: n }, (_, i) => (back == null ? (i * 360) / n : (back + ((i + 1) * 360) / (n + 1)) % 360));
export const slotLayout = (n, back = null) => (back == null ? { slots: n, offset: 0 } : { slots: n + 1, offset: 1 });
/** Centre of slot `i` of `slots`, rotated by `rotate` radians (the back angle, for a submenu). */
export const slotCenter = (i, slots, rotate = 0) => sliceCenter(i, slots) + rotate;

const point = (r, a, cx, cy) => `${(cx + r * Math.sin(a)).toFixed(3)} ${(cy - r * Math.cos(a)).toFixed(3)}`;

export function arcPath(i, n, rIn, rOut, cx = 0, cy = 0, rotate = 0) {
  const half = Math.max(Math.PI / n - GAP / 2, 0.01);
  const c = slotCenter(i, n, rotate);
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

/** The slot a dragged slice is over; near the hub (or the back gap) the angle is meaningless, so it keeps where it was. */
export function dragSlot(x, y, n, rIn, prev, back = null) {
  if (back == null) return sliceAt(x, y, n, rIn) ?? prev;
  if (Math.hypot(x, y) < rIn) return prev;
  const w = (2 * Math.PI) / (n + 1);
  const slot = Math.floor(((angleOf(x, y) - (back * Math.PI) / 180 + 2 * Math.PI) % (2 * Math.PI) + w / 2) / w) % (n + 1);
  return slot === 0 ? prev : slot - 1;
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

/** Back angle (degrees) of the submenu opened from child `index` of a list of `n` whose own back angle is `back`. */
export const backAngleFor = (index, n, back = null) => (slotAngles(n, back)[index] + 180) % 360;

/** Back angle of the list at `path` (null at the root). */
export function backAt(items, path) {
  let list = items, back = null;
  for (const i of path) {
    back = backAngleFor(i, list.length, back);
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

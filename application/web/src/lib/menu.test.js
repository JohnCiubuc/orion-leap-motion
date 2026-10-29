import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MAX_ITEMS, GAP, sliceCenter, arcPath, sliceAt, dragSlot, listAt, addItem, removeItem, moveItem, blankItem,
  selectionAfterMove, selectionAfterRemove, fitLabel,
  MAX_DEPTH, slotAngles, slotLayout, slotCenter, isSubmenu, hasChildren, toSubmenu, toAction, canNest, clampPath, crumbs,
  backAt, backAngleFor, slotSpans, weightOf, centerAt, posAt, wedgePath, edges, edgeAngle, edgeWeights, SKINS,
} from "./menu.js";

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} !≈ ${b}`);
const items = (...labels) => labels.map((label) => ({ label, action: "input.keys", args: {} }));
const labels = (list) => list.map((i) => i.label);
const at = (deg, r = 100) => [r * Math.sin((deg * Math.PI) / 180), -r * Math.cos((deg * Math.PI) / 180)]; // SVG: y down

test("sliceCenter puts slice 0 at the top and spaces slices evenly", () => {
  assert.equal(sliceCenter(0, 4), 0);
  near(sliceCenter(1, 4), Math.PI / 2);
  near(sliceCenter(3, 4), (3 * Math.PI) / 2);
  for (let i = 1; i < 12; i++) near(sliceCenter(i, 12) - sliceCenter(i - 1, 12), (2 * Math.PI) / 12);
  assert.equal(sliceCenter(0, 1), 0);
  near(sliceCenter(0.5, 4), Math.PI / 4);
});

test("arcPath starts at the outer edge of the slice's first side", () => {
  const path = arcPath(1, 4, 60, 160);
  const [, x, y] = path.match(/^M\s*(-?[\d.]+)[ ,](-?[\d.]+)/);
  const theta = sliceCenter(1, 4) - (Math.PI / 4 - GAP / 2);
  near(+x, 160 * Math.sin(theta), 2e-3);
  near(+y, -160 * Math.cos(theta), 2e-3);
  assert.ok(path.trimEnd().endsWith("Z"));
  const flag = (p) => p.match(/A\s*\S+\s+\S+\s+0\s+(\d)\s+1/)[1];
  assert.equal(flag(arcPath(0, 1, 60, 160)), "1"); // one slice is nearly the whole ring
  assert.equal(flag(arcPath(0, 2, 60, 160)), "0");
  const moved = arcPath(1, 4, 60, 160, 10, 20).match(/^M\s*(-?[\d.]+)[ ,](-?[\d.]+)/);
  near(+moved[1], +x + 10, 2e-3);
  near(+moved[2], +y + 20, 2e-3);
});

test("sliceAt maps points to slices and the hub to null", () => {
  assert.equal(sliceAt(0, -100, 4, 20), 0);
  assert.equal(sliceAt(100, 0, 4, 20), 1);
  assert.equal(sliceAt(0, 100, 4, 20), 2);
  assert.equal(sliceAt(-100, 0, 4, 20), 3);
  assert.equal(sliceAt(3, 3, 4, 20), null);
  assert.equal(sliceAt(...at(44), 4, 20), 0);
  assert.equal(sliceAt(...at(46), 4, 20), 1);
  assert.equal(sliceAt(...at(359), 4, 20), 0); // wraps past the top
});

test("dragSlot keeps the previous slot inside the hub", () => {
  assert.equal(dragSlot(2, 2, 4, 20, 3), 3);
  assert.equal(dragSlot(100, 0, 4, 20, 3), sliceAt(100, 0, 4, 20));
});

test("listAt walks a path of indices", () => {
  const root = [{ label: "a" }, { label: "b", items: items("x", "y") }];
  assert.equal(listAt(root, []), root);
  assert.equal(listAt(root, [1]), root[1].items);
  assert.equal(listAt(root, [0]), undefined);
  assert.equal(listAt(root, [5]), undefined);
});

test("addItem inserts, caps at 12, and creates nested lists", () => {
  const list = items("1", "2", "3");
  assert.equal(addItem(list, [], items("n")[0]), true);
  assert.deepEqual(labels(list), ["1", "2", "3", "n"]);
  addItem(list, [], items("m")[0], 1);
  assert.deepEqual(labels(list), ["1", "m", "2", "3", "n"]);
  const full = items(...Array.from({ length: MAX_ITEMS }, (_, i) => String(i)));
  assert.equal(addItem(full, [], items("x")[0]), false);
  assert.equal(full.length, MAX_ITEMS);
  const tree = items("a", "b");
  assert.equal(addItem(tree, [1], items("x")[0]), true);
  assert.deepEqual(labels(tree[1].items), ["x"]);
});

test("removeItem and moveItem work on the root and on a nested path", () => {
  const list = items("a", "b", "c", "d");
  removeItem(list, [], 1);
  assert.deepEqual(labels(list), ["a", "c", "d"]);
  const four = items("a", "b", "c", "d");
  moveItem(four, [], 0, 2);
  assert.deepEqual(labels(four), ["b", "c", "a", "d"]);
  const back = items("a", "b", "c", "d");
  moveItem(back, [], 3, 0);
  assert.deepEqual(labels(back), ["d", "a", "b", "c"]);
  const tree = [{ label: "p", items: items("a", "b", "c") }];
  moveItem(tree, [0], 0, 2);
  removeItem(tree, [0], 0);
  assert.deepEqual(labels(tree[0].items), ["c", "a"]);
});

test("blankItem numbers new slices", () => {
  assert.deepEqual(blankItem(items("1", "2", "3", "4"), []), { label: "5", action: "input.keys", args: {} });
  assert.equal(blankItem(items("1", "3"), []).label, "2");
  assert.equal(blankItem([], []).label, "1");
});

test("selection follows a moved slice and clamps after removal", () => {
  assert.equal(selectionAfterMove(0, 0, 2), 2);
  assert.equal(selectionAfterMove(1, 0, 2), 0); // a neighbour shifts down
  assert.equal(selectionAfterMove(3, 0, 2), 3);
  assert.equal(selectionAfterMove(2, 3, 0), 3); // moving down the list shifts it up
  assert.equal(selectionAfterRemove(2, 2, 3), 2); // removed the last selected one: clamp to the new last
  assert.equal(selectionAfterRemove(0, 2, 3), 0);
  assert.equal(selectionAfterRemove(0, 0, 0), -1);
  assert.equal(selectionAfterRemove(3, 1, 3), 2);
  assert.equal(selectionAfterRemove(-1, 1, 3), -1);
});

test("fitLabel shortens to the slice size", () => {
  const four = fitLabel("Screenshot area", 4);
  assert.equal(four.length, 10);
  assert.ok(four.endsWith("…"));
  const twelve = fitLabel("Screenshot", 12);
  assert.equal(twelve.length, 4);
  assert.ok(twelve.endsWith("…"));
  assert.equal(fitLabel("Mute", 4), "Mute");
  assert.equal(fitLabel("", 4), "·");
});

test("labels that are not strings (a hand-edited label = 1) do not crash", () => {
  assert.equal(fitLabel(1, 4), "1");
  assert.equal(fitLabel(null, 4), "·");
  assert.equal(fitLabel(undefined, 12), "·");
  assert.equal(blankItem([{ label: 1 }, { label: 2 }], []).label, "3");
});

// ── Submenus ──

test("slotAngles matches the overlay's layout table", () => {
  assert.deepEqual(slotAngles(4), [0, 90, 180, 270]);
  assert.deepEqual(slotAngles(3, 180), [270, 0, 90]);
  assert.deepEqual(slotAngles(2, 90), [210, 330]);
  assert.deepEqual(slotAngles(1, 0), [180]);
});

test("slotLayout and slotCenter place children after the back gap", () => {
  assert.deepEqual(slotLayout(3), { slots: 3, offset: 0 });
  assert.deepEqual(slotLayout(3, 180), { slots: 4, offset: 1 });
  near(slotCenter(0, 3), 0);
  const { slots, offset } = slotLayout(3, 180);
  near(slotCenter(1 + offset, slots, Math.PI) % (2 * Math.PI), 0, 1e-9); // the middle child points straight up
});

test("backAngleFor and backAt follow the path down", () => {
  const tree = [{ label: "S", items: [{ label: "a" }, { label: "b", items: [{ label: "x" }] }, { label: "c" }] }, { label: "leaf" }];
  assert.equal(backAngleFor(0, 2), 180);
  assert.equal(backAt(tree, []), null);
  assert.equal(backAt(tree, [0]), 180);
  assert.equal(backAt(tree, [0, 1]), 180); // the middle child sits at 0°
  assert.equal(backAt(tree, [0, 0]), 90); // the first at 270°
});

test("item type conversions", () => {
  const item = { label: "x", action: "input.keys", args: { combo: "1" } };
  assert.equal(isSubmenu(item), false);
  toSubmenu(item);
  assert.deepEqual(item, { label: "x", items: [] });
  assert.equal(isSubmenu(item), true);
  assert.equal(hasChildren(item), false);
  item.items.push({ label: "k" });
  assert.equal(hasChildren(item), true);
  toAction(item);
  assert.deepEqual(item, { label: "x", action: "", args: {} });
});

test("clampPath keeps the valid prefix; crumbs name each step", () => {
  const tree = [{ label: "S", items: [{ label: "T", items: [{ label: "z" }] }, { label: "leaf" }] }, { label: "x" }];
  assert.deepEqual(clampPath(tree, [0, 0]), [0, 0]);
  assert.deepEqual(clampPath(tree, [0, 1]), [0]); // a leaf is not a level
  assert.deepEqual(clampPath(tree, [1]), []);
  assert.deepEqual(clampPath(tree, [5, 0]), []);
  assert.deepEqual(clampPath([], [0]), []);
  assert.deepEqual(crumbs(tree, [0, 0]), [{ label: "Root", path: [] }, { label: "S", path: [0] }, { label: "T", path: [0, 0] }]);
  assert.deepEqual(crumbs(tree, [9]), [{ label: "Root", path: [] }]);
});

test("canNest stops at the depth limit and nested lists still cap at 12", () => {
  assert.equal(MAX_DEPTH, 4);
  assert.equal(canNest([]), true);
  assert.equal(canNest([0, 0, 0]), true);
  assert.equal(canNest([0, 0, 0, 0]), false);
  const tree = [{ label: "S", items: items(...Array.from({ length: 12 }, (_, i) => String(i))) }];
  assert.equal(addItem(tree, [0], items("x")[0]), false);
  assert.equal(addItem(tree, [], items("y")[0]), true);
});

test("dragSlot works inside a submenu: children skip the back gap", () => {
  // three children, back at 180°: children at 270°, 0°, 90°; the gap faces down
  assert.equal(dragSlot(...at(0), 3, 30, 1, 180), 1);
  assert.equal(dragSlot(...at(90), 3, 30, 0, 180), 2);
  assert.equal(dragSlot(...at(270), 3, 30, 2, 180), 0);
  assert.equal(dragSlot(...at(180), 3, 30, 2, 180), 2); // over the gap: keeps where it was
  assert.equal(dragSlot(0, 0, 3, 30, 1, 180), 1); // inside the hub too
  assert.equal(dragSlot(...at(120), 4, 30, 0), 1); // the root behaves as before
});

test("slotSpans matches oriondo.py slot_layout", () => {
  const flat = (l) => l.flatMap((s) => [s.center, s.span]);
  const close = (got, want) => got.forEach((v, k) => near(v, want[k], 1e-9));
  close(flat(slotSpans([2, 1, 1])), [0, 180, 135, 90, 225, 90]); // the first item stays centred on the top
  close(flat(slotSpans([1, 0.5], 180)), [324, 144, 72, 72]); // the free slot (180°, 144°) is not listed
});

test("weightOf clamps and ignores junk", () => {
  assert.equal(weightOf({}), 1);
  assert.equal(weightOf({ weight: 0.5 }), 0.5);
  assert.equal(weightOf({ weight: 99 }), 4);
  assert.equal(weightOf({ weight: 0 }), 0.1);
  assert.equal(weightOf({ weight: "x" }), 1);
});

test("dragSlot and backAngleFor follow weights", () => {
  const w = [1, 0.25, 1]; // widths 160, 40, 160: a -80…80, b 80…120, c 120…280
  assert.equal(dragSlot(...at(100), 3, 20, 0, null, w), 1);
  assert.equal(dragSlot(...at(70), 3, 20, 2, null, w), 0);
  assert.equal(dragSlot(...at(200), 3, 20, 0, null, w), 2);
  assert.equal(backAngleFor(1, 3, null, w), 280); // b sits at 100°
});

test("centerAt and posAt are inverses, and wedgePath uses the slice's own width", () => {
  const lay = slotSpans([1, 0.25, 1], null, false).map(({ center, span }) => ({ center: (center * Math.PI) / 180, span: (span * Math.PI) / 180 }));
  near(centerAt(1, lay), lay[1].center);
  near(centerAt(0.5, lay), (lay[0].center + lay[1].center) / 2);
  for (const p of [0, 0.4, 1, 1.7, 2]) near(posAt(centerAt(p, lay), lay), p, 1e-9);
  assert.notEqual(wedgePath(0, 1, 60, 160), wedgePath(0, 2, 60, 160));
});

test("edges: neighbours, plus the wrap border at the root only", () => {
  assert.deepEqual(edges(3), [[0, 1], [1, 2], [2, 0]]);
  assert.deepEqual(edges(3, 180), [[0, 1], [1, 2]]);
  assert.deepEqual(edges(1), []);
});

test("edgeWeights moves the border under the pointer and keeps the pair's sum", () => {
  const w = [1, 1, 1, 1];
  const lay = slotSpans(w, null, false).map(({ center, span }) => ({ center: (center * Math.PI) / 180, span: (span * Math.PI) / 180 }));
  const rad = (d) => (d * Math.PI) / 180;
  near(edgeAngle(lay, 0), rad(45));
  assert.deepEqual(edgeWeights(lay, w, 0, 1, rad(45)), [1, 1]); // where it already is
  assert.deepEqual(edgeWeights(lay, w, 0, 1, rad(90)), [1.5, 0.5]); // pulled toward slice 1
  assert.deepEqual(edgeWeights(lay, w, 0, 1, rad(-55)), [0.25, 1.75]); // slice 0 cannot shrink below the minimum
  assert.deepEqual(edgeWeights(lay, w, 3, 0, rad(-30)), [1.17, 0.83]); // the wrap border between the last slice and the first
  assert.deepEqual(edgeWeights(lay, w, 0, 1, rad(250)), [0.25, 1.75]); // far past the pair: sticks to the nearer end
});

test("SKINS lists unique ids with a hue", () => {
  assert.equal(new Set(SKINS.map((s) => s.id)).size, SKINS.length);
  assert.ok(SKINS.every((s) => s.hue >= 0 && s.hue < 360));
});

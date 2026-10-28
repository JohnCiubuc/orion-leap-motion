import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MAX_ITEMS, GAP, sliceCenter, arcPath, sliceAt, dragSlot, listAt, addItem, removeItem, moveItem, blankItem,
  selectionAfterMove, selectionAfterRemove, fitLabel,
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

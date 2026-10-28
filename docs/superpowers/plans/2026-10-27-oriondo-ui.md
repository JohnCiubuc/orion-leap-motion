# OrionDo UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new OrionDo page in the Orion web UI: a live wheel editor (select, drag-reorder, add, remove) with an inspector for the selected slice and a configurator for the menu's tunables.

**Architecture:** All menu logic and geometry live in a pure ES module (`lib/menu.js`, tested with `node --test`). `MenuWheel.svelte` is a presentational SVG component driven by props. `ItemInspector.svelte` reuses `ArgsEditor`. The page edits `orion.draft.gestures.oriondo` through the existing draft → unsaved-bar → `save_config` flow, so no engine change is needed.

**Tech Stack:** Svelte 5 (runes, `Tween` from `svelte/motion`), Vite, `@lucide/svelte`, Node's built-in test runner. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-27-oriondo-ui-design.md` (engine side: `docs/superpowers/specs/2026-10-27-oriondo-design.md`).

Deltas from the spec: `slotAfterDrag(angle, n)` becomes `dragSlot(x, y, n, rIn, prev)` (it must also hold the previous slot while the pointer is inside the hub); `menu.js` gains `selectionAfterMove`, `selectionAfterRemove` and `fitLabel` (selection bookkeeping and label fitting need tests too); the page offers "Load the default menu" when a config has no OrionDo section.

All paths are relative to `application/web/` unless they start with `application/` or `docs/`. Branch: `oriondo-ui`.

## Global Constraints

- Menu data is `gestures.oriondo.items` = `[{label, action, args}]`; list order is position; a future submenu is an `items` list inside an item. Every tree operation takes a `path` (list of indices; `[]` = root). The UI passes only `[]` today.
- `MAX_ITEMS = 12`; slice 0 at the top, clockwise, N slices 360/N° apart, `GAP = 3°` between slices (same as `overlay_menu.py`).
- Nav entry **OrionDo** (lucide `Orbit`) between Gestures and Bindings; inspector panel about 340 px wide; layout stacks on narrow windows.
- New slice: `{label: <smallest unused positive integer as string>, action: "input.keys", args: {}}`, inserted after the selected slice (or at the end).
- Re-layout ease about 200 ms; reduced motion is already honoured by `theme.css`.
- Keyboard: Arrows move selection, Alt+Arrow reorders, Delete removes, Enter focuses the inspector.
- Reuse existing pieces: `orion`, `send`, `actionMeta` (`lib/link.svelte.js`), `ArgsEditor`, `Switch`, the `theme.css` tokens, scoped `<style>` blocks, Svelte 5 runes style (`$state`, `$derived`, `$props`). No new dependencies, no engine changes, no refactoring of `Gestures.svelte`.
- Edits go through `orion.draft`; never write config directly.

## Review Focus

1. **Config without an `oriondo` section** (an older `config.toml`, as the user's was before this feature): the page shows an empty menu with a "Load the default menu" action instead of failing. First edit creates the section. *(Task 2 check)*
2. **Selection after remove/reorder:** the selection follows the moved slice and clamps after a removal (never points past the end). *(Task 1 tests)*
3. **Dragging through the hub:** while the pointer is inside the hub the dragged slice keeps its previous slot instead of jumping. *(Task 1 tests)*
4. **Long labels and many slices:** labels are shortened to fit their slice (with an ellipsis) and the full label stays in a tooltip. *(Task 1 tests)*
5. **An action the engine doesn't know** (a plugin not loaded): the action dropdown keeps showing that value; saving never silently swaps it for the first option. *(Task 3 check)*

---

### Task 1: Menu logic module

**Files:**
- Create: `src/lib/menu.js`
- Test: `src/lib/menu.test.js`
- Modify: `package.json` (add script `"test": "node --test"`)

**Interfaces:**
- Produces (all exported from `src/lib/menu.js`, plain ES module, no Svelte imports):
  - `MAX_ITEMS = 12`, `GAP` (radians, 3°)
  - `sliceCenter(i, n) -> number` radians clockwise from the top; `i` may be fractional (animation)
  - `arcPath(i, n, rIn, rOut, cx = 0, cy = 0) -> string`: SVG path of slice `i` (fractional `i` and `n` allowed), half-width `π/n − GAP/2` (at least 0.01), `large-arc` flag set when `2·half > π` (only n = 1)
  - `sliceAt(x, y, n, rIn) -> number | null`: x, y relative to the wheel centre with y pointing down (SVG); `null` inside `rIn`
  - `dragSlot(x, y, n, rIn, prev) -> number`: `sliceAt(...)`, or `prev` while inside the hub
  - `listAt(items, path) -> array | undefined`
  - `addItem(items, path, item, at?) -> boolean`: inserts (default end), creates a missing `items` list on the parent for a nested path, returns `false` without mutating at `MAX_ITEMS`
  - `removeItem(items, path, index)`, `moveItem(items, path, from, to)`: mutate in place; `moveItem` has `splice` semantics (remove at `from`, insert at `to`)
  - `blankItem(items, path) -> {label, action, args}`
  - `selectionAfterMove(sel, from, to) -> number`, `selectionAfterRemove(sel, index, count) -> number` (count is the length after removal; `-1` when empty)
  - `fitLabel(label, n) -> string`: at most 10 characters for n ≤ 4, 6 for n ≤ 8, 4 otherwise, shortened with `…`

- [ ] **Step 1: Write the failing tests** in `src/lib/menu.test.js` (`node:test` + `node:assert/strict`). Names and key assertions:
  - `sliceCenter puts slice 0 at the top and spaces slices evenly`: `sliceCenter(0,4) === 0`, `sliceCenter(1,4)` ≈ `π/2`, `sliceCenter(3,4)` ≈ `3π/2`; for n = 12 every neighbour differs by `2π/12`; `sliceCenter(0,1) === 0`; fractional `sliceCenter(0.5,4)` ≈ `π/4`.
  - `arcPath starts at the outer edge of the slice's first side`: parse the first `M x y` of `arcPath(1, 4, 60, 160)` and assert it equals the polar point `(160, sliceCenter(1,4) − (π/4 − GAP/2))` converted to x = r·sin(θ), y = −r·cos(θ), to 1e-6; the string ends with `Z`; `arcPath(0, 1, 60, 160)` contains the large-arc flag `1` and `arcPath(0, 2, 60, 160)` contains `0` for it; `cx, cy` offsets shift the first point.
  - `sliceAt maps points to slices and the hub to null` (n = 4, rIn = 20): `(0,-100) → 0`, `(100,0) → 1`, `(0,100) → 2`, `(-100,0) → 3`, `(3,3) → null`; a point at 44° from the top → 0 and at 46° → 1; at 359° → 0 (wrap).
  - `dragSlot keeps the previous slot inside the hub` (Review Focus 3): `dragSlot(2, 2, 4, 20, 3) === 3`; outside the hub it equals `sliceAt`.
  - `listAt`: `[]` returns the root array; `[1]` returns `items[1].items`; a missing path returns `undefined`.
  - `addItem inserts, caps at 12, and creates nested lists`: default appends and returns `true`; with `at = 1` inserts there; at 12 items returns `false` and the array length stays 12; `addItem(items, [1], x)` creates `items[1].items = [x]`.
  - `removeItem and moveItem`: removing index 1 from `[a,b,c,d]` gives `[a,c,d]`; `moveItem` 0→2 gives `[b,c,a,d]` and 3→0 gives `[d,a,b,c]`; both work on a nested path.
  - `blankItem numbers new slices`: labels `["1","2","3","4"]` → `"5"`; `["1","3"]` → `"2"`; `[]` → `"1"`; result is `{label, action: "input.keys", args: {}}`.
  - `selection follows a moved slice and clamps after removal` (Review Focus 2): `selectionAfterMove(0, 0, 2) === 2`; `selectionAfterMove(1, 0, 2) === 0` (neighbour shifts down); `selectionAfterMove(3, 0, 2) === 3`; `selectionAfterRemove(2, 2, 3) === 2` (clamped to last); `selectionAfterRemove(0, 2, 3) === 0`; `selectionAfterRemove(0, 0, 0) === -1`; `selectionAfterRemove(3, 1, 3) === 2` (selected index shifts down).
  - `fitLabel shortens to the slice size` (Review Focus 4): `fitLabel("Screenshot area", 4)` → 10 chars ending `…`; `fitLabel("Screenshot", 12)` → 4 chars ending `…`; short labels unchanged; empty string → `"·"`.

- [ ] **Step 2: Run to verify failure:** `cd application/web && node --test` → FAIL (`Cannot find module '…/menu.js'` / import error).

- [ ] **Step 3: Implement `src/lib/menu.js`** with the signatures above. Use one angle helper (`angleOf(x, y) = atan2(x, −y)` normalised to `[0, 2π)`) for `sliceAt`; slice index is `floor((θ + w/2) / w) % n` with `w = 2π/n`. Add the `"test": "node --test"` script to `package.json` (a script only, no dependency). Keep comments to the why (the shared geometry rules with `overlay_menu.py`).

- [ ] **Step 4: Run to verify pass:** `npm test` → all pass.

- [ ] **Step 5: Commit**

```bash
git add application/web/package.json application/web/src/lib/menu.js application/web/src/lib/menu.test.js
git commit -m "feat: pure menu logic and geometry for the OrionDo editor"
```

---

### Task 2: OrionDo page with the wheel

**Files:**
- Create: `src/components/MenuWheel.svelte`, `src/views/OrionDo.svelte`
- Modify: `src/App.svelte` (import the view, add the nav entry between Gestures and Bindings with the `Orbit` icon)

**Interfaces:**
- Consumes: everything from `src/lib/menu.js` (Task 1); `orion`, `actionMeta` from `src/lib/link.svelte.js`.
- Produces:
  - `MenuWheel.svelte` props: `items` (array of `{label, action, args}`), `selected` (index or −1), `onselect(i)`, `onmove(from, to)`, `onadd()`, `onremove(i)`. It holds no menu data.
  - `OrionDo.svelte` (the page) owns `sel` (selected index) and the `path` (`[]`). Task 3 adds the inspector and settings into its right-hand column via two marked slots: `<!-- inspector -->` and `<!-- settings -->`.

Verified by building and by screenshots (the wheel is visual); the logic it relies on is covered by Task 1's tests.

- [ ] **Step 1: Add the nav entry and the page shell.** `App.svelte`: import `OrionDo from "./views/OrionDo.svelte"` and `Orbit` from lucide; add `{ id: "oriondo", label: "OrionDo", icon: Orbit, view: OrionDo }` after Gestures. `OrionDo.svelte`: header (title, one-line explanation, an enable `Switch` bound to `orion.draft.gestures.oriondo.enabled`, default on), the two-column grid (wheel panel and a 340 px right column; stacked below ~900 px). Items come from `orion.draft?.gestures?.oriondo?.items ?? []`; a `conf()` helper creates the `oriondo` section on first edit (as `conf()` in `Gestures.svelte` does) and `list()` creates `items`. If `orion.gestures` has no gesture named `oriondo`, show "This version of Orion has no OrionDo." and nothing else.

- [ ] **Step 2: Implement `MenuWheel.svelte`** (SVG, `viewBox` centred on 0,0, `rIn` 60, `rOut` 160, hub radius 34; palette from the `theme.css` tokens, slice fill `--nebula`, selected `--rigel` outline and glow, hover lifts the slice a few px outward):
  - Each slice is a focusable `<g role="button" tabindex>` with `aria-label="Slice {i+1}: {label}"` and a `<title>` tooltip with the full label and action; text is `fitLabel(label, n)`.
  - Click selects. Keyboard: Arrow keys move selection (wrapping), Alt+Arrow calls `onmove`, Delete calls `onremove`, Enter dispatches focus to the inspector (the page listens via a callback prop `onenter`).
  - Layout animation: one `Tween` for the fractional slice count `n` and one `Tween` per slice for its fractional slot (keyed by an id kept in a `WeakMap` per item object, as `Bindings.svelte` does for row ids), duration 200 ms, `cubicOut`; `arcPath` receives the animated values. A newly added slice fades in.
  - Drag-reorder: `pointerdown` on a slice starts tracking; moving more than 6 px starts a drag (a shorter press stays a click). While dragging, the pointer angle (relative to the SVG centre via `getBoundingClientRect`) drives the dragged slice's slot, using `dragSlot` with `prev` as its current slot, and the others' slots shift to make room; `pointerup` calls `onmove(from, to)` once and Escape cancels. Use pointer capture so leaving the SVG does not drop the drag.
  - Empty state: centred text "Add your first slice" plus a note that an empty menu never opens. A slice whose action is unknown (`actionMeta(item.action)` missing) shows a small warning dot.
  - An **Add slice** button below the wheel calls `onadd()`; it is disabled with a hint at `MAX_ITEMS`.

- [ ] **Step 3: Wire the page to the wheel.**
  - `onadd`: `addItem(list(), [], blankItem(list(), []), sel + 1 or end)`; select the new slice.
  - `onremove(i)`: `removeItem(list(), [], i)`, then `sel = selectionAfterRemove(sel, i, list().length)`.
  - `onmove(from, to)`: `moveItem(list(), [], from, to)`, then `sel = selectionAfterMove(sel, from, to)`.
  - When `items` is empty and `orion.gestureDefaults.oriondo?.items` exists, show a **Load the default menu** button that copies those items into the draft (Review Focus 1).

- [ ] **Step 4: Verify the build:** `cd application/web && npm run build` → ends with `✓ built in …`, no errors; `npm test` still passes.

- [ ] **Step 5: Verify visually.** Run a separate demo instance (`~/.local/bin/orion-renewal --demo`, which is dry-run and uses its own port), open the OrionDo page from the nav rail, and capture only that window with `grim -g` using its geometry from `hyprctl clients -j` (class `orion-renewal`). Check: 4 slices with labels 1–4 at top/right/bottom/left; the page loads with the shipped menu; an old config without an `oriondo` section shows the empty state and **Load the default menu**. Keyboard and drag behaviour cannot be driven from here, so list them as "for the user to try" in the hand-off.

- [ ] **Step 6: Commit**

```bash
git add application/web/src/components/MenuWheel.svelte application/web/src/views/OrionDo.svelte application/web/src/App.svelte
git commit -m "feat: OrionDo page with an interactive menu wheel"
```

---

### Task 3: Inspector and configurator

**Files:**
- Create: `src/components/ItemInspector.svelte`
- Modify: `src/views/OrionDo.svelte` (fill the `<!-- inspector -->` and `<!-- settings -->` slots), `application/README.md` (one line under the OrionDo section: it can be edited on the OrionDo page)

**Interfaces:**
- Consumes: `MenuWheel` and the page state from Task 2; `ArgsEditor` (prop `item`); `orion`, `send`, `actionMeta`.
- Produces: `ItemInspector.svelte` props: `item` (the selected `{label, action, args}`, or `undefined`), `onremove()`, `inputref` (bindable, the label field, so the wheel's Enter can focus it).

- [ ] **Step 1: Implement `ItemInspector.svelte`:** nothing selected → "Select a slice to edit it." Otherwise a label text field; an action `<select>` over `orion.actions` that also lists the item's current action when the engine doesn't know it (Review Focus 5), with changing the action resetting `args` to `{}` as `Bindings.svelte`'s `setAction` does; the action's doc line or, when unknown, "Unknown action — is its plugin loaded?"; `<ArgsEditor {item} />`; a **Test** button (`send("test_action", { action, args: $state.snapshot(item.args ?? {}) })`) and a **Remove** button (`danger`).

- [ ] **Step 2: Implement the settings block in `OrionDo.svelte`.** Params come from `orion.gestures.find(g => g.name === "oriondo").params`: `trigger` as a dropdown (its range entry is a choice list), `deadzone` and `pull` as range sliders with the live value and a help line each, and an **Advanced** disclosure (collapsed by default) with `lost`, `cooldown`, `tap_trigger`, `tap_still`. Values read `orion.draft.gestures.oriondo?.[k] ?? param default`; edits write `conf()[k]`. Help text: deadzone "Distance (mm) from the centre before a slice is hovered."; pull "Distance (mm) to pull out to fire the hovered slice."; lost "Seconds without the hand before the menu closes."; cooldown "Pause (s) after the menu closes before it can reopen."; tap_trigger and tap_still reuse the Gestures page's wording. Use the same slider markup and step rule as `Gestures.svelte` (duplicated on purpose, see the spec).

- [ ] **Step 3: Resets.** **Reset settings** sets each param key present in `orion.gestureDefaults.oriondo` to its shipped value and deletes the others from the draft (so the engine default applies); **Reset menu** replaces `items` with a `structuredClone` of the shipped items. Both only change the draft; the save bar applies them.

- [ ] **Step 4: Verify the build:** `cd application/web && npm run build` → `✓ built in …`; `npm test` passes.

- [ ] **Step 5: Verify visually with the demo instance** (as in Task 2): select-by-click is not drivable from here, so check the default state (nothing selected → hint), the settings block with its sliders and the Advanced disclosure, and an item temporarily set to an unknown action in the draft (via a hand-edited copy of the config, in a temp `XDG_CONFIG_HOME` used only for this demo run) showing the warning and keeping the unknown value in the dropdown. Confirm saving a changed `pull` writes `pull = …` under `[gestures.oriondo]` in that temp config and leaves the items intact.

- [ ] **Step 6: Run both suites:** `cd application/web && npm test` and `cd application && python -m pytest tests/test_core.py -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add application/web/src application/README.md
git commit -m "feat: OrionDo inspector and settings configurator"
```

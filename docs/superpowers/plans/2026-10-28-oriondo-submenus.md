# OrionDo Submenus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kando-style submenus for OrionDo (travelling pie, ghost parent, pull toward it to go back) with a modern, skinnable overlay and an editor that can build them.

**Architecture:** The gesture keeps a level stack and emits `enter`/`back` events; the engine mirrors them to the overlay as ops. `MenuAnim` stays a pure, skin-neutral model that emits angles/scales/ghosts/pan as plain numbers; skins in `orion/menu_skins/` turn that view into cairo drawing. The web editor edits the same `items` tree through a `path`.

**Tech Stack:** Python 3.14 (gesture, engine, pure animation), cairo + GTK4 layer-shell in the overlay process (system Python), Svelte 5 + Node test runner for the editor.

**Spec:** `docs/superpowers/specs/2026-10-28-oriondo-submenus-design.md`

## Global Constraints

- Work on branch `oriondo-submenus`; commit per task; never merge or push unless the user asks.
- Angles are **degrees clockwise from the top** in events/config-facing code, **radians clockwise from the top** in `MenuView`. Screen offsets in the view are `(x right, y down)` in *travel units* (1.0 = one ring radius; the skin multiplies by its pixel distance, about 120).
- **Layout rule (Python and JS must agree).** Root: n slots, child i centred at `i·360/n`. Submenu with n children, back angle b: n+1 slots of `360/(n+1)`, the back gap at b, child i centred at `b + (i+1)·360/(n+1)`. Parity table: n=3, b=180 → children at 270, 0, 90; n=2, b=90 → children at 210, 330; n=1, b=0 → child at 180.
- Entering from the slice centred at angle θ gives the submenu `back = (θ + 180) mod 360`.
- Hover value for the back gap is `-1`; `None` still means centre.
- Limits: `MAX_ITEMS = 12` per level, 4 levels deep in the editor only; the engine accepts any depth.
- An item with an `items` key is a submenu even if it also has `action`. Empty or non-list `items` → inert item (pulling does nothing, menu stays open).
- The overlay runs as a script under the system Python from `orion/`; files in `orion/menu_skins/` use only **relative imports and no `orion.*` imports**, and `menu_anim.py` imports nothing from orion. Skins must not import `menu_anim`; their motion tuning is a plain dict `MOTION`.
- Keep `MenuAnim.open(labels, now)` working as-is (new `subs` is an optional keyword) so the existing animation tests stay valid.
- Existing suites stay green: `cd application && python -m pytest tests -q` (176 at start) and `cd application/web && npm test` (11 at start).
- Constants that need eyes/hands are module constants with a `shortcut:` comment (limit + when to retune).

## Review Focus

- Entering a submenu while the fingertip sits at the rim never fires a child or goes back at once (origin re-anchors, nothing hovered), and tremor at the new centre does not tap-close.
- Ragged configs never crash the engine or gesture: item with both `action` and `items`, `items` not a list, empty submenu, numeric labels, nesting deeper than 4.
- Losing the hand inside a submenu closes the whole menu after `lost`; a hand returning far away does not fire or go back.
- Overlay: an unknown skin name, or a skin that raises while drawing, falls back or hides the window; it never leaves a click-eating surface up.
- Editor: Submenu→Action with children asks first; deleting the last child keeps the path valid; a path that no longer exists (discarded draft, reset to defaults) falls back to the root.

---

### Task 1: Gesture: levels, layout, enter/back

**Files:**
- Modify: `application/orion/gestures/oriondo.py`
- Test: `application/tests/test_core.py` (OrionDo section, after the existing `test_oriondo_*`; reuse `menu`, `feed`, `polar`, `index_hand`, `opened`, `key_events`, `last`)

**Interfaces:**
- Produces: events (name `"oriondo"`):
  - `begin` value `{"labels": [str], "subs": [bool], "skin": str}`
  - `update` value `{"x","y","hover","pull"}` where `hover` may be `-1`
  - `enter` value `{"labels","subs","back": float,"depth": int,"parent": str}` (depth ≥ 1)
  - `back` value `{"labels","subs","back": float|None,"depth": int,"away": float}` (`away` = the direction pulled, i.e. the left level's back angle)
  - `fire` value `{"index","item"}` unchanged; `end` unchanged.
- `OrionDo.skin: str` read from the `skin` override (default `"aurora"`), kept by `reset()` like `items`.
- Helper `slot_angles(n: int, back: float | None) -> list[float]` (module level; degrees; parity table above) used by the gesture and importable by tests.

- [ ] **Step 1: Failing tests** (menus built with `menu(items_list)`; a submenu item is `{"label": "S", "items": menu_items(3)}`):
  - `test_slot_angles_layout`: the three parity-table cases plus root `slot_angles(4, None) == [0, 90, 180, 270]`.
  - `test_oriondo_enter_submenu_instead_of_firing`: root `[S, leaf]`, pull `polar(0, 36)` → events include `enter` with `labels == ["1","2","3"]`, `back == 180`, `depth == 1`, `parent == "S"`, and **no** `fire`/`end`.
  - `test_oriondo_enter_reanchors_and_cannot_refire`: right after `enter`, holding the same fingertip for 30 frames at 100 fps yields only `update`s with `hover is None` (origin re-anchored; no tap-close).
  - `test_oriondo_submenu_child_hovers_by_its_angle_and_fires`: after entering at the top, moving +40 mm along `slot_angles(3,180)[1]` (0° → straight up) and pulling fires child `"2"` with `fire.index == 1` and then `end`.
  - `test_oriondo_back_gap_hover_and_back`: after entering, moving toward 180° reports `hover == -1`; pulling there emits `back` with `depth == 0`, `back is None`, `away == 180`, `labels == root labels`; menu stays open; no `fire`.
  - `test_oriondo_back_to_nested_parent`: two levels deep, one `back` returns to depth 1 with the middle level's `back` angle.
  - `test_oriondo_empty_or_malformed_submenu_is_inert`: `{"label":"E","items":[]}` and `{"label":"M","items":"x"}` pulled to `pull` → no `fire`, no `enter`, no `end`; a following leaf still fires. Item with both `action` and non-empty `items` enters.
  - `test_oriondo_lost_hand_inside_submenu_closes_everything`: after `enter`, 1.6 s of no hand → `end` with `"lost"`.
  - `test_oriondo_centre_tap_inside_submenu_closes_everything`: reuse the existing tap helper shape → `end` with `"tap"`.
  - `test_oriondo_returning_far_away_in_a_submenu_does_not_back_or_fire`: >0.15 s out of view, back at 42 mm toward the back gap → `hover is None`, no `back`.
- [ ] **Step 2:** Run `python -m pytest tests/test_core.py -q -k "oriondo or slot_angles"`; expect the new tests to fail.
- [ ] **Step 3: Implement.** `menu["stack"]` holds one dict per level below the current (`{"items","back","parent"}`); the current level is `menu["items"]`/`menu["back"]`. Generalise `_sector` to slots: `slot = round(((angle - (back or 0)) % 360) / (360/slots)) % slots`, hover = slot − 1 for submenus (so the gap is −1), slot for the root; keep the 4° hysteresis against `current`. On `r >= pull` with a hover: back gap → pop and emit `back`; submenu item → push and emit `enter`; leaf → `fire` as today. Both `enter` and `back` set `origin` to the current tip, `hover = None`, `tap = FingerMotion()`, `seen = frame.t`. Pass `subs` (`isinstance(item.get("items"), list)`) in `begin`/`enter`/`back`. `progress` and the update value use the level's own geometry unchanged.
- [ ] **Step 4:** Run the OrionDo tests and the whole suite; all pass.
- [ ] **Step 5: Commit** `feat: OrionDo submenus in the gesture`.

### Task 2: Engine protocol and skin name

**Files:**
- Modify: `application/orion/engine.py` (`_oriondo`), `application/orion/default.toml` (`skin = "aurora"` under `[gestures.oriondo]`)
- Test: `application/tests/test_core.py` (use `_menu_engine`, `_menu_frames`, `_op_names`)

**Interfaces:**
- Consumes: Task 1 events.
- Produces: overlay ops (dicts sent via `overlay.menu`): `{"op":"open","labels","subs","skin"}`, `{"op":"enter","labels","subs","back","depth","parent"}`, `{"op":"back","labels","subs","back","depth","away"}`, `update`/`fire`/`close` unchanged.

- [ ] **Step 1: Failing tests:** `test_engine_forwards_enter_and_back_ops` (a two-level menu driven through frames records `["open","enter","back","close"...]` order via `_op_names` and the `enter` op carries `back == 180`); `test_open_op_carries_skin_and_subs` (default config → `skin == "aurora"`, `subs` all False); `test_default_config_names_the_aurora_skin`. A submenu pull must not run any action (`e.ran` stays empty).
- [ ] **Step 2:** Run; expect failures. Also run the existing `test_engine_forwards_menu_and_runs_item_action`; if it compares whole `open` dicts, extend its expectation with `subs`/`skin` rather than loosening it.
- [ ] **Step 3: Implement** the op mapping in `_oriondo` (phases `begin/enter/back/update/fire/end`); `_menu_open = ev.phase != "end"` stays.
- [ ] **Step 4:** Whole suite green. **Step 5: Commit** `feat: OrionDo submenu ops and skin name`.

### Task 3: Animation model: levels, back gap, ghosts, travel

**Files:**
- Modify: `application/orion/menu_anim.py`
- Test: `application/tests/test_core.py` (animation section; existing tests there must keep passing unchanged)

**Interfaces:**
- Produces (pure Python, bare-importable):
  - `class Spring` with `__init__(self, value=0.0, stiffness=260.0, damping=22.0)`, `target`, `step(dt)`, `snap(value)`; semi-implicit Euler in sub-steps ≤ 4 ms; underdamped (ζ≈0.68).
  - `MenuAnim(reduced_motion=False, travel_time=0.18)`:
    - `open(labels, now, subs=None)`; `enter(labels, now, back, parent, subs=None)`; `back(labels, now, back, away, subs=None)` (angles in degrees, `back` may be None); `update(x, y, hover, pull, now)` (hover may be −1); `fire(index, now)`; `close(now)`; `step(now) -> MenuView`.
  - `SliceView` gains `angle: float` (rad) and `sub: bool`; `MenuView` keeps `visible/slices/marker/arc/hover` and gains `slots: int`, `back: BackView | None` (`angle`, `lift`, `glow`, `stretch`), `ghosts: list[GhostView]` (`x, y` travel units relative to the current centre, `alpha`, `label`, `lift`), `pan: tuple[float, float]` (where the current centre sits relative to the window centre, travel units), `pulse: float` (0..1 ring progress, restarts on enter/back), `leaving: list[Layer]` (`Layer`: `center` (x, y) relative to the window centre, `slices`, `slots`, `leave` 0..1, `picked: int | None`).
- Ghosts: ancestor k's offset is the cumulative sum of unit vectors `(sin b, −cos b)` of the levels' back angles; at most 2, alphas 0.6 and 0.3, label = that ancestor's parent label.

- [ ] **Step 1: Failing tests** (fake clock):
  - angles: root 4 slices → `[0, π/2, π, 3π/2]` (rad); submenu n=3, b=180° → `[3π/2, 0, π/2]`; `view.slots == 4`; `view.back.angle == π`.
  - `enter` → within 0.02 s `view.pan` has length ≈ 1.0 in the pulled direction (for `back=180` pan ≈ (0, −1) in x-right/y-down units); `pan` settles to (0,0) within 0.6 s and overshoots slightly at least once (underdamped); the old level appears in `view.leaving` with `picked` set and `leave` rising to 1 by 0.25 s, then is dropped; new slices bloom from scale 0 with the existing stagger.
  - `ghosts`: after one `enter` → one ghost at `(0, 1)` (toward the parent for `back=180` in y-down units: `(sin π, −cos π) = (0, 1)`), alpha 0.6, label = parent; after two → two ghosts with alphas 0.6/0.3; after `back` once → one ghost.
  - `back` mirrors travel: pan starts toward the parent and settles to 0; the child layer leaves; parent slices bloom again.
  - hover −1 lifts `view.back.lift` (not any slice) and `view.hover == -1`; `pulse` jumps to ~0 on enter/back and reaches 1 within 0.4 s.
  - reversal mid-travel (`enter` then `back` 0.05 s later) keeps `pan` continuous (no jump greater than 0.3 between consecutive 10 ms steps).
  - `reduced_motion=True`: after `enter`, `pan == (0, 0)` and new slices at scale 1 within 0.05 s, `leaving == []`.
  - existing animation tests unchanged and passing.
- [ ] **Step 2:** Run; expect failures. **Step 3: Implement** (levels list inside `MenuAnim`; pan = two `Spring`s; pulse and back-gap lift via time and the existing exponential follow). Existing hover/stretch/marker keep their exponential follow and bloom keeps `ease_out_back` — only travel, ghosts and pulse use the underdamped `Spring`.
- [ ] **Step 4:** Whole suite green. **Step 5: Commit** `feat: skin-neutral submenu animation model`.

### Task 4: Skins: package, registry and "aurora"

**Files:**
- Create: `application/orion/menu_skins/__init__.py`, `application/orion/menu_skins/aurora.py`, `application/tests/test_menu_skins.py`
- Modify: none outside these.

**Interfaces:**
- `menu_skins.skin(name)` decorator registering a class; `menu_skins.get_skin(name: str)` → instance (unknown name or empty → the default `"aurora"`); `menu_skins.names() -> list[str]`.
- Skin class contract: attribute `MOTION: dict` (kwargs for `MenuAnim`, may be `{}`); method `draw(cr, view, w, h, labels_font="Sora")` where `view` is a `MenuView`. The skin owns its pixel constants (ring radii, travel distance ≈ 120 px, window padding), never imports `menu_anim`/`orion`, and uses only cairo calls on `cr`.

- [ ] **Step 1: Failing tests** (`pytest.importorskip("cairo")`; `cairo.ImageSurface(FORMAT_ARGB32, 560, 560)`):
  - `get_skin("nope")` is the aurora instance; `names()` contains `"aurora"`.
  - `test_aurora_draws_every_phase`: drive a real `MenuAnim` through open → hover → enter → back → fire → close at 16 ms steps and `draw` each step without raising; the surface is non-empty once the pie has bloomed and fully transparent after close.
  - `test_skin_modules_have_no_orion_imports`: reading the source files, none contains `import orion`, `from orion`, or `menu_anim`.
  - `test_render_frames_to_png` writes a contact sheet (root idle, hover, mid-travel at 0.06 s, settled submenu, hovering the back gap, two levels deep, fire flash) to `$ORION_RENDER_DIR` if set (skipped otherwise). Used for review by eye.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3: Implement** the registry and `aurora` per the spec: radial-gradient glass slices with a thin inner highlight, layered soft hover glow, faint shadow ring, springy lift/stretch, picked-slice swell into the new hub with the other slices collapsing inward, children springing out from the hub, ghost hubs with labels and a self-drawing connector line, ghost warming/growing under back-gap hover with the pull arc along the connector, pulse ring on enter/back, bright flash on fire, labels crossfading with slice alpha. Pie geometry defaults: `R_IN 70`, `R_OUT 170`, `R_PULL 230`, `GAP 3°`, window 560 px (as today).
- [ ] **Step 4:** Render the contact sheet (`ORION_RENDER_DIR=<scratchpad>`), look at the PNGs, and iterate on the look until it reads as modern and clean (spacing, contrast, glow restraint, ghost legibility). Record the final spring numbers.
- [ ] **Step 5:** Whole suite green. **Step 6: Commit** `feat: menu skins with the aurora default`.

### Task 5: Overlay window uses skins

**Files:**
- Create: `application/orion/menu_ctl.py`
- Modify: `application/orion/overlay_menu.py`, `application/orion/overlay_gtk.py` (docstring of ops; pass `reduced_motion` from the config message), `application/orion/default.toml` (`[overlay] reduced_motion = false`)
- Test: `application/tests/test_menu_skins.py` (window logic that does not need GTK)

**Interfaces:**
- Consumes: `MenuAnim`, `get_skin`.
- `MenuWindow.handle(msg)` handles ops `open|enter|back|update|fire|close`; `open` selects the skin by `msg.get("skin")`, builds `MenuAnim(reduced_motion=…, **skin.MOTION)`. `_draw` becomes `skin.draw(cr, view, w, h)` wrapped in try/except: any exception hides the window (`broken` semantics like click-through failure) and logs once.
- New `application/orion/menu_ctl.py`: `class MenuController(anim_factory, get_skin, reduced_motion=False)` with no imports of its own (dependencies injected, so it works both bare-imported in the overlay and as `orion.menu_ctl` in tests). It holds `anim`, `skin`, `broken`; methods `handle(msg, now)` (ops `open|enter|back|update|fire|close`), `view(now)` and `draw(cr, w, h)` (catches skin exceptions → `broken = True`, view hidden). `MenuWindow` becomes placement, click-through, tick and unmap around a controller.

- [ ] **Step 1: Failing tests** for the GTK-free controller: unknown skin → aurora; `enter`/`back` ops reach the anim (view `pan` non-zero after `enter`); a skin whose `draw` raises marks the controller broken and `visible` false; reduced-motion flag reaches the anim.
- [ ] **Step 2:** Run; fail. **Step 3:** Implement; remove the drawing code now living in `aurora.py`; keep placement, click-through, tick, unmap-when-collapsed.
- [ ] **Step 4:** Whole suite green. **Step 5:** Smoke: start the real overlay (`orion-renewal --demo` on the user's Hyprland session) only if the user is present; otherwise note it as the manual check. **Step 6: Commit** `feat: overlay draws through skins`.

### Task 6: Editor logic (pure JS)

**Files:**
- Modify: `application/web/src/lib/menu.js`
- Test: `application/web/src/lib/menu.test.js`

**Interfaces:**
- `MAX_DEPTH = 4`.
- `slotAngles(n, back = null) -> number[]` (degrees; same parity table as Python) and `slotLayout(n, back = null) -> { slots, offset }` for drawing the wheel with `arcPath` (extend `arcPath`/`sliceCenter` callers via `sliceCenter(i + offset, slots)` rotated by `back`; add optional `rotate` radians to `arcPath(i, n, rIn, rOut, cx, cy, rotate = 0)` and `sliceCenter`-style helper `slotCenter(i, slots, rotate)`).
- `isSubmenu(item) -> boolean` (`Array.isArray(item.items)`), `toSubmenu(item) -> void` (removes `action`/`args`, sets `items: []`), `toAction(item) -> void` (removes `items`, sets `action: ""`, `args: {}`), `hasChildren(item)`.
- `clampPath(items, path) -> number[]` (longest valid prefix where every step is a submenu), `crumbs(items, path) -> [{label, path}]` starting with `{label: "Root", path: []}`, `backAngleFor(parentSliceIndex, parentSlots, parentRotate) -> degrees` (θ + 180 mod 360).
- Existing exports unchanged.

- [ ] **Step 1: Failing tests:** `slotAngles` parity table (all four cases from Global Constraints); `clampPath` on a removed branch; `crumbs` labels and paths; `toSubmenu`/`toAction` shapes; `addItem` into a nested path still caps at 12; `sliceAt`/`dragSlot` unaffected for the root.
- [ ] **Step 2:** `cd application/web && npm test`; fail. **Step 3:** implement. **Step 4:** pass. **Step 5: Commit** `feat: submenu logic for the OrionDo editor`.

### Task 7: Editor UI

**Files:**
- Modify: `application/web/src/components/MenuWheel.svelte`, `application/web/src/components/ItemInspector.svelte`, `application/web/src/views/OrionDo.svelte`
- Create: `application/web/src/components/Breadcrumb.svelte`

**Interfaces:**
- Consumes: Task 6 helpers.
- `MenuWheel` props: existing plus `back = null` (degrees; null at root), `parentLabel = ""`, `onopen(i)` (descend), `onup()` (ascend). At depth ≥ 1 it draws the back gap as a ghost-parent hub with `parentLabel` at the back angle, uses `slotLayout`, and submenu slices carry a chevron. Double-click and `Enter` on a submenu slice call `onopen`; `Escape`/`Backspace` with nothing selected call `onup` (Backspace still deletes a selected slice, as today).
- `OrionDo.svelte` owns `path = $state([])` and derives `items` at the path (`listAt`), `back` from the path, and clamps with `clampPath` whenever the draft changes. `sel` resets on path change. Add/remove/move use the current path.
- `ItemInspector`: an *Action / Submenu* segmented toggle at the top; Submenu hides action/args and shows "N items · Open" with the Open button; switching a submenu that has children to Action uses `confirm()`; the warning dot also appears for an empty submenu ("Empty submenu: pulling it does nothing").

- [ ] **Step 1:** Implement the pieces above; keep the existing keyboard, drag and reduced-motion behaviour.
- [ ] **Step 2:** `npm test` and `npm run build` pass.
- [ ] **Step 3: Verify in a real browser** with the headless-Chromium DevTools approach used for the first OrionDo UI (demo engine, `XDG_CONFIG_HOME` pointing at a temp copy of the user's config; never click Test): create a submenu from the inspector, open it by double-click, check breadcrumb and the back-gap ghost, add children, go up with Esc and via the breadcrumb, reset to defaults while inside a submenu (path falls back to root), save, and confirm the saved TOML nests `items` correctly.
- [ ] **Step 4: Commit** `feat: OrionDo submenu editor`.

### Task 8: Docs and notes

**Files:**
- Modify: `README.md` (short OrionDo submenu paragraph if the README documents OrionDo; otherwise skip), `CLAUDE.md` (where-things-live: submenus, skins; roadmap item 6 → submenus done; skins how-to: add `orion/menu_skins/<name>.py` with `@skin("<name>")`, `MOTION`, `draw`; set `skin = "<name>"`)

- [ ] **Step 1:** Update the notes. **Step 2:** Full test runs (Python and JS) and `npm run build`. **Step 3: Commit** `docs: OrionDo submenus and skins`.

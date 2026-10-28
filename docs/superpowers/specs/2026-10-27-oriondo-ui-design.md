# OrionDo UI — menu editor and configurator

Date: 2026-10-27 · Branch: oriondo-ui · Status: design, awaiting review
Builds on: `2026-10-27-oriondo-design.md` (the engine side, shipped).

## Goal

A page in the Orion web UI to edit the OrionDo radial menu and tune how it behaves, without touching
`config.toml`. A Kando-style editor: a live wheel you click, drag and extend, with an inspector for the selected
slice. Built so submenus, app launching and macros can be added later without reworking the page.

## Non-goals (this iteration)

Engine-side submenus, app-launch and macro actions; editing nested menus in the UI (the structure supports it, the
UI shows the root level only); a "preview on the real screen" button; themes; importing/exporting menus.

## Findings that shape the design

- The Gestures page lists only the five built-in families (`FAMILIES` in `Gestures.svelte`), so OrionDo (family
  `oriondo`) never appears there. It needs its own page.
- Everything editable already flows through `orion.draft` → unsaved-changes bar → `save_config` → live reload
  (`Engine.reload_config` rebuilds gestures). No new engine command is needed.
- The engine already sends everything the page needs in `state`: gesture metadata (`trigger` choices, ranges and
  defaults for the tunables), `gesture_defaults` (from `default.toml`, including the shipped items), and the action
  list with arguments and docs. `test_action` already runs one action.
- Items are `{label, action, args}`, the same shape as a binding, so the existing `ArgsEditor` edits them.
- `orion/web` is a git-ignored build output; `application/setup.sh` runs `npm run build`.

## Page and navigation

- New nav entry **OrionDo** (lucide `Orbit`) between Gestures and Bindings in `App.svelte`'s `VIEWS`.
- Header with the title, a one-line explanation, and an on/off switch bound to `gestures.oriondo.enabled`
  (default on, as for every gesture).
- Two columns: the **wheel** panel (flexible) and, beside it, the **inspector** panel (about 340 px) with the
  **settings** configurator below it. Narrow windows stack them.
- All edits mutate `orion.draft.gestures.oriondo` (created on first edit, as `Gestures.svelte`'s `conf()` does), so
  the existing save bar saves and live-reloads the menu.

## Data model and logic (`web/src/lib/menu.js`)

A plain ES module (no Svelte runes) so `node --test` can load it.

- Menu data is `gestures.oriondo.items`: `[{label, action, args}]`. A submenu later is an `items` list inside an
  item (the engine's `default.toml` comment already describes list order and nesting this way).
- Every tree operation takes a `path`, a list of indices from the root (`[]` is the root menu, `[2]` is the
  submenu of item 2). Functions, all non-mutating or clearly mutating as noted:
  - `listAt(items, path) -> array | undefined`
  - `addItem(items, path, item, at?)`, `removeItem(items, path, index)`, `moveItem(items, path, from, to)` — mutate
    in place (the caller passes the reactive draft).
  - `blankItem(items, path) -> {label, action: "input.keys", args: {}}`; the label is the next unused number
    string; `args` start empty and `ArgsEditor` shows the action's defaults.
  - `MAX_ITEMS = 12`: `addItem` refuses to go past it (returns `false`), because slices become unreadable.
- Geometry matches the on-screen overlay (`overlay_menu.py`): slice 0 at the top, going clockwise, N slices spaced
  360/N° apart, a 3° gap between slices.
  - `sliceCenter(i, n) -> radians` (0 at the top, clockwise)
  - `arcPath(i, n, rIn, rOut) -> string` (an SVG path for one ring segment)
  - `sliceAt(x, y, n, rIn) -> index | null` (null inside the hub radius), used for drag-and-drop landing
  - `slotAfterDrag(angle, n) -> index` (the slot a dragged slice lands in)

## The wheel (`components/MenuWheel.svelte`, SVG)

Props: `items`, `selected` (index or -1), `onselect(i)`, `onmove(from, to)`, `onadd()`, `onremove(i)`. It holds no
menu data of its own.

- Looks like the on-screen pie: the same palette as the overlay (`--nebula`/`--rigel` tokens), ring segments with
  centered labels, a hub in the middle. The selected slice has an accent outline and a soft glow; hover lifts a
  slice slightly.
- **Select:** click or tap a slice.
- **Reorder:** drag a slice around the wheel. It follows the pointer angle and, on release, lands in the nearest
  slot; the others glide into their new positions. A short press without movement is a click, not a drag.
- **Add / remove:** the wheel re-lays out with an ease of about 200 ms (Svelte `Tween` on each slice's angles).
  Reduced-motion is honored by the global `prefers-reduced-motion` rule in `theme.css`.
- **Keyboard:** each slice is focusable (`role="button"`, label "Slice 2: 2"). Arrow Left/Right (or Up/Down) moves
  the selection, Alt+Arrow reorders (same convention as the Bindings page), Delete removes, Enter moves focus to the
  inspector.
- **States:** an empty menu shows "Add your first slice" and a note that an empty menu never opens; a slice whose
  action is unknown or missing shows a small warning dot with a tooltip.
- An **Add slice** button sits under the wheel (disabled with a hint at 12). A new slice is inserted after the
  selected one, or at the end when none is selected, and becomes selected.

## Inspector and configurator

**Inspector** (`components/ItemInspector.svelte`), for the selected slice:
- Label text field, an action dropdown listing every registered action (`orion.actions`), the existing
  `ArgsEditor` for its arguments, the action's one-line doc (or the "Unknown action, is its plugin loaded?"
  warning, as on Bindings), a **Test** button (`send("test_action", …)`, as on Bindings) and **Remove**.
- Changing the action resets its arguments to the new action's defaults (as Bindings does).
- Nothing selected: "Select a slice to edit it."

**Settings** (in `views/OrionDo.svelte`):
- `trigger` as a dropdown (choices from the engine's gesture metadata), `deadzone` and `pull` as sliders with help
  text, and an **Advanced** disclosure with `lost`, `cooldown`, `tap_trigger` and `tap_still`. Ranges, defaults and
  choices come from `orion.gestures.find(g => g.name === "oriondo").params`, so they cannot drift from the engine.
- **Reset to defaults** (settings only) and **Reset menu** (items only), both from `orion.gestureDefaults.oriondo`,
  taking effect on save like the Gestures page's reset.
- The small slider markup is duplicated from `Gestures.svelte` instead of refactoring that page (surgical
  changes); extracting a shared param control is a noted follow-up.

## Extension points (not built, kept possible)

- **New actions** (launch application, key macros) appear in the action dropdown automatically; their arguments
  render through `ArgsEditor`.
- **Richer arguments:** `ArgsEditor` falls back to a text field for unknown argument shapes. A macro step list would
  be a new argument editor chosen per action; nothing in the page assumes arguments are flat strings.
- **Submenus:** items with their own `items` are already legal in `menu.js` via `path`. The page would add a
  `path` state, an "Open submenu" action in the inspector and a breadcrumb above the wheel, and the wheel would
  draw a `›` badge on items that have children. None of this requires changing `MenuWheel`'s props except adding
  the badge flag.

## Error handling

- Unsaved edits use the existing draft/dirty/save-bar flow, including "Discard".
- A save the engine rejects shows through the existing error banner.
- Items with a blank label render a "·" placeholder and are allowed; the engine accepts any label string.
- If the engine has no `oriondo` gesture (an older engine), the page shows "This version of Orion has no OrionDo."
  instead of failing.

## Testing

- `web/src/lib/menu.test.js`, run with `node --test` (a `"test": "node --test"` script in `package.json`; no new
  dependency). Covers: geometry for N = 1, 2, 3, 4, 6 and 12 (slice 0 at the top, clockwise, equal spacing, gap),
  `sliceAt` at slice borders and inside the hub, `slotAfterDrag`, add/remove/move on the root and on a nested path,
  `blankItem` numbering with existing labels, and the 12-item cap.
- `npm run build` must succeed.
- The page itself is checked by running Orion and taking screenshots (empty menu, 4 slices, selected slice,
  12 slices, unknown action warning). Drag-and-drop feel can only be judged by hand with a mouse.

## Open risks

- Svelte `Tween` over per-slice angles during drag and relayout needs to stay smooth with 12 slices; if it
  stutters, fall back to CSS transforms on rotated `<g>` elements.
- The pie geometry exists in two places (overlay cairo, editor SVG). `menu.js` documents the shared rules; a drift
  would only change the editor's look, not behavior.
- Narrow window layout has not been designed in detail beyond stacking the two panels.

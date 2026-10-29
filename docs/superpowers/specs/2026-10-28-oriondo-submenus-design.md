# OrionDo submenus: design

Date: 2026-10-28. Status: design approved in chat, spec awaiting review.

## Goal
Submenus for OrionDo that feel like Kando's: the pie travels to where a submenu item was chosen, the parent stays behind as a ghost, and you go back by pulling toward it. The look is modern and the drawing is **skinnable**, so other animation styles can be added later without touching the model, engine or overlay window.

## Background (what exists)
- `gestures/oriondo.py`: state machine, one level. Events `begin/update/fire/end`. The marker is relative to an origin (the fingertip at open). `REANCHOR = 0.15` s out of view re-anchors it.
- `engine.py` `_oriondo` mirrors events to the overlay as ops `open/update/fire/close`; a fired item runs its action.
- `menu_anim.py` (pure animation model, bare-imported by the overlay script) and `overlay_menu.py` (GTK/cairo pie window, `SIZE = 560`, `R_IN 70`, `R_OUT 170`, `R_PULL 230`).
- Web: `lib/menu.js` (tree ops with a `path`, geometry), `MenuWheel.svelte`, `ItemInspector.svelte`, `OrionDo.svelte`.
- Config items are `{label, action, args}`; an `items` list inside an item was reserved for submenus.

## Behaviour
- An item with an `items` list is a **submenu**: it needs only a `label`, no action.
- **Enter.** Pulling a submenu item to `pull` does not fire. The marker re-anchors at the current fingertip with nothing hovered (so it cannot fire at once), and the children appear around the new centre.
- **Layout.** A submenu with n children has n+1 equal slots. Slot 0 is the **back gap**, facing the parent. The children fill slots 1…n clockwise from it. The root has n slots starting at the top, no back gap.
- **Back.** Pulling toward the back gap pops one level and the pie travels back to the parent. The back gap is drawn as the ghost parent, not as a slice. Engine sends `hover = -1` for it.
- **Close.** A centre tap or losing the hand for 1.5 s closes the whole menu. A leaf pull fires its action and closes. Not allowed any more (paused, exclusive mode, overlay gone) still closes without firing.
- **Empty submenu** (`items` missing or empty): inert item. Pulling it does nothing and does not close the menu.
- **Limits.** 12 items per level (`MAX_ITEMS`), 4 levels deep in the editor. The engine does not enforce depth.

## Engine and protocol
- Gesture state gains a path stack (per level: items list, back angle, picked index, origin).
- New events: `enter {labels, back, depth, parent}` and `back {labels, back, depth}`; `update` hover may be `-1`; `fire` keeps `{index, item}`.
- Engine mirrors them to the overlay as ops `enter` / `back`; the `open` op carries `skin` (name from `[gestures.oriondo] skin`, default `"aurora"`).
- `fire` of a leaf at any depth runs its action exactly as today.

## Animation model (skin-neutral)
`MenuAnim` keeps a level stack (labels, back angle, parent label) and emits plain numbers only:
- per slice: angle, scale, alpha, lift, stretch, glow, flash;
- `back`: angle and lift/glow of the back gap; `ghosts`: up to 2 ancestors with offset, alpha, label; `pan`: current travel offset; `pulse`: enter/back ring progress; marker, pull arc, hover.
Ops `open/enter/back/update/fire/close`; all times are supplied by the caller (fake clocks in tests). Springs (damped, slight overshoot) drive hover, pan, bloom, ghosts and stay smooth when reversed mid-motion. A `reduced_motion` flag makes transitions near-instant.

## Skins
- `orion/menu_skins/`: one file per skin, registering by name (`@skin("aurora")`); a skin provides `draw(cr, view, w, h)` and a small timing/spring object. The registry module is GTK-free (cairo only inside draw), so the engine can list names. Unknown name → default skin.
- `overlay_menu.py` keeps only the window, tick and placement, and delegates drawing to the active skin. Constants of the current look move into the default skin.
- **Default skin "aurora":** shared-element transition (the picked slice swells into the new hub; other slices collapse inward; children spring out of the hub along their angles; the old hub eases back as a ghost, its connecting line drawing itself in); radial-gradient glass slices, thin inner highlight, layered soft glow on hover, faint shadow ring; the ghost parent warms and grows as you lean toward it and the pull arc fills along the connector; a pulse ring on enter/back and a bright flash on a fired leaf; labels crossfade and scale with their slice. Travel is one ring radius (about 120 px) over about 0.18 s. Up to two ancestors are drawn, fading with depth, inside the existing 560 px window.

## Editor (web UI)
- Inspector: *Action / Submenu* toggle. Switching to Submenu drops action/args and starts `items: []`; switching back with children asks for confirmation.
- `MenuWheel` takes a `path`; breadcrumb above it (`Root › Anki › Rating`), each part clickable. Double-click / `Enter` / an Open button descends; `Esc` / `Backspace` / breadcrumb goes up. Submenu slices carry a chevron.
- At depth ≥ 1 the preview uses the overlay's layout: n+1 slots, back gap drawn as the ghost parent, first child just clockwise of it. `lib/menu.js` gets the slot-layout function; Python and JS share one angle table in their tests.
- An empty submenu shows a warning dot (pulling it does nothing). No skin selector in the UI until a second skin exists.

## Testing
- Python: gesture (enter/back, re-anchor with no instant fire, back gap hover, empty submenu inert, centre tap and hand loss close everything at depth, not-allowed close, fire at depth runs the right item); animation with a fake clock (angles, ghosts, pan, reversal mid-travel, reduced motion); skin registry fallback; the existing 176 tests stay green.
- Rendering: skins draw through plain cairo, so a test renders frames to PNG off-screen (no GTK, no Hyprland). Used for review by eye, and as a smoke test that every skin draws every phase without raising.
- JS: slot-layout parity table, path and breadcrumb operations, type-switch behaviour.
- By the user on the real overlay: the feel of travel, back-pull and timing.

## Out of scope
Hover-to-open, a skin selector UI, extra skins, drag-and-drop between levels, launch-app and macro actions (still on the roadmap), the OrionDo pending UI/engine minors.

## Open items for the plan
- Whether `menu_skins/` is importable by bare name in the overlay process (it runs `overlay_gtk.py` as a script from the `orion/` directory) or needs `sys.path` set there.
- Spring parameters and the `reduced_motion` source (system setting or config key): decide while looking at rendered frames.
- Exact travel distance if it clips at the 560 px window with two ancestors at long back angles.

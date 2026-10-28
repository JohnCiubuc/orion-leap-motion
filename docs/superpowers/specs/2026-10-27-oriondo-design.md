# OrionDo — finger-driven radial menu

Date: 2026-10-27 · Branch: precision-lock · Status: design, awaiting review

## Goal

A minimal Kando-style pie menu driven by the fingertip. A hand pose opens a radial menu centered on the
focused monitor. The index fingertip steers a marker inside the pie, separate from the OS cursor. An item fires
only when the finger is *pulled* outward past an activation distance, never by a tap. A tap at the center
closes the menu. First use: four items that press `1`, `2`, `3`, `4` via uinput, in an order the user chooses.

Later (out of scope now, but the structure must not block them): submenus, launching applications, macros.

## Non-goals (this iteration)

Submenus, themes, multiple menus, per-item angles, mouse/keyboard selection, icons beyond a text label.

## Interaction

All geometry is in millimetres of fingertip travel; the overlay maps it to pixels.

1. **Open.** The `trigger` pose (default `peace`, its own hold time) begins. The index fingertip's (x, y) at that
   moment is the origin, so the marker starts dead center. Depth (z) is ignored. The menu stays open after the
   pose is dropped.
2. **Marker.** `m = tip_xy − origin` (Leap +y is up). Sent to the overlay divided by `pull`, so `1.0` is the
   activation ring.
3. **Hover.** With `r = |m|`: `r < deadzone` is the center, nothing selected. Otherwise the angle selects the slice
   (clockwise from the top; N items are 360/N° apart). Slice borders have a few degrees of hysteresis.
4. **Pull and fire.** `progress = clamp((r − deadzone) / (pull − deadzone))`. When `r ≥ pull` the hovered item
   fires and the menu closes. Hovering alone never fires.
5. **Center tap.** A fingertip tap (existing `FingerMotion`, index tip relative to palm) while `r < deadzone`
   closes the menu without firing. A tap dips the tip ~5–10 mm, well under `pull`, so a tap can never fire an
   item and the marker needs no freezing.
6. **Hand lost** for more than `lost` seconds closes the menu.
7. **Re-arm.** After any close, the trigger pose must end and `cooldown` seconds pass before it can open again.

The opening hand's side is the one tracked until close.

## Architecture

| Unit | Responsibility |
|---|---|
| `gestures/oriondo.py` (new) | `OrionDo(Gesture)`, family `"oriondo"`. Owns the state machine. Wraps the registered trigger pose (`REGISTRY[trigger]`) to detect the open. Emits `begin` (open), `update` (marker + hover + pull), `fire` (item index), `end` (reason: `fired` / `tap` / `lost`). |
| `engine.py` | In `on_frame`, handles `oriondo` events: forwards them to the overlay, and on `fire` submits the item's `action` + `args` to the existing `Executor` (skipped when `dry_run`). Does not open while paused or while an exclusive mode is on; in that case it resets the gesture. |
| `overlay.py` (`OverlayHost`) | `menu(msg)` sends JSON lines to the overlay process; `update` messages throttled to ~60 Hz. Adds `oriondo` to `QUIET` so no gesture cards are shown. |
| `overlay_menu.py` (new, GTK side) | The pie surface and all animation. Imported by `overlay_gtk.py`, which routes `{"type": "menu", …}` messages to it. |
| `default.toml` | `[gestures.oriondo]` params and `[[gestures.oriondo.items]]`. |

The engine sends state, not pixels. The overlay owns every easing curve, so motion stays smooth despite uneven
frame timing.

### Gesture registration

`OrionDo` is a plain `Gesture` subclass added to `load_builtins`. Declared `params` (shown as sliders or a dropdown
in the UI):

| Param | Default | Meaning |
|---|---|---|
| `trigger` | `peace` | dropdown of pose names |
| `deadzone` | 8 mm | center radius |
| `pull` | 35 mm | activation distance |
| `lost` | 1.5 s | hand-loss timeout |
| `cooldown` | 0.6 s | pause before re-opening |
| `tap_trigger`, `tap_still` | as the desktop pointer | `FingerMotion` thresholds |

`items` is not a slider param. The generic override filter drops undeclared keys, so `OrionDo.__init__` reads
`items` from its overrides directly, and `reset()` is overridden to keep it (the base `reset` re-runs `__init__`
from `self.p` only).

### Config

```toml
[gestures.oriondo]
trigger = "peace"

[[gestures.oriondo.items]]   # clockwise from the top; list order sets position
label = "1"
action = "input.keys"
args = { combo = "1" }
# "2" → right, "3" → bottom, "4" → left
```

Equal spacing is guaranteed because position comes only from list order. A submenu later is an `items` list inside
an item, which is why the menu is a tree from the start. Launching an app or macro later is just a different
`action`. `Config` already round-trips nested arrays of tables.

### Future UI editing (design constraint, UI itself out of scope)

The Orion web UI will later edit the items. The design keeps that cheap:

- Items are plain data (`label`, `action`, `args`), the same shape as a binding, so the existing `ArgsEditor`
  and the action metadata already in `engine.state()` (names, default args, `choices`) can drive an item editor.
- A UI save goes through `reload_config`, which rebuilds the gestures, so an edited menu applies live.
- List order *is* position, so an editor must preserve and reorder the array. Nothing may depend on an item id
  or on the array being sorted by anything else.
- No item data is cached outside the config (the gesture re-reads `items` on every rebuild).

## Overlay and animation

A full-monitor transparent layer-shell surface on the focused monitor, click-through (empty input region), same
setup as the precision ring, with the pie centered. Redraws at 60 fps only while open or animating, then unmaps.
Rendering is cairo (the ring probe showed the cairo renderer is the cheapest at 4K).

- **Open:** bloom. Slices scale and fade in staggered ~25 ms apart with a slight overshoot ease. Close plays it
  in reverse.
- **Hover:** the hovered slice lifts outward and brightens with a soft glow; the previous slice settles back.
- **Pull:** the slice stretches toward the activation ring and an arc fills with `progress`.
- **Marker:** a dot with a faint trail, exponentially smoothed to hide tracking jitter.
- **Fire:** the slice flashes, then the pie collapses to the center.

Overlay messages: `open {items: [labels]}`, `update {x, y, hover, pull}`, `fire {index}`, `close {reason}`.

## Failure handling

- No overlay (non-Wayland or `gtk4-layer-shell` missing): the menu would be invisible, so `OrionDo` does not open,
  and the existing overlay status in Settings explains why.
- Unknown or failing action: reported through the existing executor error path (`emit("error", …)`).
- Overlay process dies mid-menu: the gesture times out through `lost` or a tap; no input is grabbed, so nothing can
  lock the user out.
- No items configured: the gesture never opens.

## Testing

Unit tests in `tests/test_core.py` with synthetic hand frames:

- Open on the trigger pose; origin is the fingertip at that moment.
- Hover picks the right sector at each of the 4 angles and with other N (3, 6).
- Hysteresis: no flicker at a slice border.
- No fire below `pull`; fire exactly at `pull`; the correct item fires.
- Center tap closes without firing; the same tap with `r ≥ deadzone` does not close.
- A tap-sized dip (≤10 mm) never fires.
- Hand loss beyond `lost` closes; shorter loss does not.
- Re-arm needs the pose to end plus `cooldown`.
- Engine: `fire` submits the item's action; `dry_run` and paused/exclusive-mode suppress it.

Overlay visuals are verified by running the app and capturing a screenshot. They aren't unit-tested.

## Open risks

- 60 fps with the animated pie at 4K on the cairo renderer is unmeasured. Damage clipping to the pie's bounding
  box is the fallback.
- The peace pose is bound to right-click in the mouse modes. OrionDo is suppressed there (exclusive modes), so the
  two don't collide, but a non-exclusive mode binding `peace` would also fire.
- The index fingertip is steady only while the other fingers stay put. Changing the hand shape from peace to a
  pointing index may shift the tip a few mm. The origin is therefore taken at open, and a settle delay before
  accepting fire is a tuning option if it proves a problem.

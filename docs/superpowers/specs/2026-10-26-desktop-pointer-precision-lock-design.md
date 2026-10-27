# Desktop pointer: precision lock

Status: design approved in conversation, awaiting spec review. Replaces the continuous-offset model in
`DesktopPointer` (`application/orion/gestures/twohand.py`).

## Goals (from the user)

1. **Edges.** Reaching the limits of the sensor's view puts the cursor on the matching edge or corner of the
   desktop. The hand never has to leave the view to hit an edge.
2. **Fine control.** Over a target, larger hand motions give small cursor motions, so the user lands on small
   targets (4K display) without over- or undershooting.
3. **Steady palm.** A resting palm gives a steady cursor. A little jitter is acceptable.
4. **Taps.** A tap moves the palm; Orion must recognise that and keep the cursor where it was.
5. **Predictable.** (From feedback on the previous design.) The same hand position gives the same cursor
   position unless a mode the user can see says otherwise.

## Model

Two modes per hand, plus a short glide.

**Pipeline.** Palm position (`track`) → One Euro filter (`steady`, `responsive`, unchanged) → `p` (mm, clipped to the
view limits). `speed` is the filter's own velocity estimate. `A(p)` is the existing linear mapping from the view
(`view_width`, `view_top`, `coverage`, `bottom`) to (u, v) in 0…1.

**Coarse mode (default).** cursor = `A(p)`. Stateless: the same `p` gives the same cursor, and the limits of the
view map to the screen edges and corners.

**Precision mode.** Entered when `speed < enter_speed` for `dwell` seconds and the hand is farther than `edge` mm
from every view limit.
- Anchor: `h0 = p`, cursor `c` stays where it is (no jump).
- Each frame: `c += gain(r) · (p' − p'_prev)`, where `p'` is `p` after the rest latch (hand movements under `rest` mm
  are ignored; beyond it the latch trails the hand by `rest`) and `r = |p − h0|`.
- `gain(r) = precision + (1 − precision) · min(r / radius, 1)²`: `precision` (≈ 0.2) near the anchor, rising to 1 at
  `radius`, so drifting out of the zone never stalls or jumps the cursor.
- `c` is clipped to the view limits' screen box.

**Leaving precision.** On `speed > exit_speed`, or when the hand comes within `edge` mm of a view limit, the mode
returns to coarse. The leftover `off = c − A(p)` decays exponentially with time constant `glide / 3`
(≈ 95 % gone in `glide` seconds), so the cursor glides onto the hand without a snap. Edge zones therefore always
end at exactly `A(p)`, which is on the screen edge.

Known cost: in precision the cursor may be up to roughly `(1 − precision) · radius` mm of hand travel away from
`A(p)` (≈ 15–20 mm, a few hundred px on 4K) until the next fast move. Targets inside the edge zone are coarser.

## Taps

Detector (shared with the air-mouse `pointer` gesture, extracted from `Pointer._damp` into one helper): a fingertip
moves ≥ `tap_trigger` mm against the palm within 0.12 s, and the palm was slower than `tap_still` mm/s at the
start of that window. Never triggers above 250 mm/s.

In `desktop_pointer` a detected tap:
1. **Rewinds** `c` to its value from just before the window (a short history of cursor positions, ~0.2 s), undoing
   the palm's dip.
2. **Holds** the cursor (`Δ = 0`) for `tap_hold` seconds after the finger stops.
3. If in coarse mode, enters precision first, so the hold and the later relative steps cannot lag or jump.

`desktop_pointer` stops using `tap_damp`; the air-mouse `pointer` keeps its current damping.

## Precision ring (visual cue, optional)

A thin ring around the cursor shows precision mode.
- **Setting:** `[overlay] precision_ring = true` (Settings → Overlay, a toggle). When false, the engine never
  sends ring messages and nothing is drawn.
- **Animation:** entering precision, the ring zooms **out-to-in**: from ~44 px to ~20 px radius while fading in
  (≈ 160 ms, ease-out). Leaving, it plays the reverse (in-to-out, fading out, ≈ 120 ms). Moving it never animates.
- **Wiring:** `DesktopPointer` exposes which hands are in precision. After each frame the engine tells
  `OverlayHost` when that changes (`{"type": "ring", "on": bool}`), as it already does for `config`.
- **Drawing:** `overlay_gtk.py` follows the cursor while the ring is visible by polling Hyprland's cursor position
  (≤ 60 Hz, only while shown), so it is correct regardless of the `display` argument or monitor layout.
- **Risk:** the existing overlay is a corner text card; a click-through surface that tracks the cursor across
  monitors is new. The first plan task is a throwaway probe of the layer-shell approach (small moving surface vs a
  per-monitor full-screen surface) before building on it.

## Settings

| Kept | `track`, `steady`, `responsive`, `max_grab`, `view_width`, `view_top`, `coverage`, `bottom`, `tap_trigger`, `tap_still` |
|---|---|
| New | `precision` 0.2, `dwell` 0.10 s, `enter_speed` 40 mm/s, `exit_speed` 150 mm/s, `radius` 25 mm, `edge` 20 mm, `rest` 0.2 mm, `glide` 0.12 s, `tap_hold` 0.30 s |
| Removed | `fine`, `fine_speed`, `reach` (and the old `edge`, `rest` meanings) |
| Overlay | `precision_ring` (bool, default true) |

`default.toml` and the code defaults are updated together. Existing user values for removed keys are ignored. The
view geometry keeps the user's tuned values (251 × 351, `bottom` 150) as defaults. The new numbers are starting
points to be tuned on recorded data.

## Testing

Unit (synthetic hands, `tests/test_core.py`):
- Coarse is stateless: the same `p` after any history gives the same (u, v); the view limits give exactly 0 or 1.
- From any slow history, walking to a limit ends exactly on the screen edge (edge zone forces coarse + glide).
- Precision gain: slow movement moves the cursor ≈ `precision` × as far; at `radius` the gain is 1.
- Exit glide: the cursor never moves more than a fixed bound per frame while converging, and converges to `A(p)`.
- Rest latch: tremor under `rest` leaves the cursor unchanged.
- Tap: palm dip + finger motion from rest leaves the cursor within a small tolerance; a moving hand is unaffected.
- Ring: engine sends `on`/`off` only on mode change; sends nothing when `precision_ring` is false.

Replay tool (`scripts/pointer_replay.py`, new): feeds an `.orec` recording through the pointer and prints jitter at
rest (px RMS), max per-frame cursor jump, edge coverage, tap displacement. The user records short sessions
(pointing at targets, resting, tapping, sweeping to the corners) to tune the starting numbers.

## Out of scope

Wrist-tilt fine control; changing the air-mouse `pointer` gesture; any ring styling beyond size, fade and the
zoom animation; per-profile precision settings.

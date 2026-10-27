# Desktop Pointer Precision Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `DesktopPointer`'s continuous-offset model with a coarse/precision-lock model, a tap rewind-and-hold, and an optional animated precision ring.

**Architecture:** Pure cursor logic lives in a new `PrecisionLock` class (no hand types, unit-testable with numpy). `DesktopPointer` feeds it the filtered palm position, speed and a tap flag from a new `FingerMotion` detector (extracted from `Pointer._damp`, which the air-mouse keeps using). The engine tells `OverlayHost` when precision starts or ends; `overlay_gtk.py` draws and animates the ring.

**Tech Stack:** Python 3.14, numpy, pytest; GTK4 + gtk4-layer-shell (system Python) for the ring; Svelte 5 for Settings.

**Spec:** `docs/superpowers/specs/2026-10-26-desktop-pointer-precision-lock-design.md`

## Global Constraints

- Run tests from `application/`: `python -m pytest tests -q` (68 pass before this plan starts).
- `Pointer` (air mouse) keeps `tap_damp`, `tap_trigger` (mm), `tap_still` (mm/s) and its current behavior.
- Defaults: `precision` 0.2, `dwell` 0.10 s, `enter_speed` 40 mm/s, `exit_speed` 150 mm/s, `radius` 25 mm, `edge` 20 mm, `rest` 0.2 mm, `glide` 0.12 s, `tap_hold` 0.30 s; view geometry stays `view_width` 251, `view_top` 351, `coverage` 0.85, `bottom` 150.
- Removed from `desktop_pointer`: `fine`, `fine_speed`, `reach`, `tap_damp`. Config files still carrying them must load without error (ignored).
- Overlay setting: `[overlay] precision_ring = true`.
- Ring animation: enter zooms out-to-in 44 → 20 px radius with fade-in, 160 ms ease-out; leave plays reverse with fade-out, 120 ms; cursor movement never animates it.
- Match surrounding style: terse comments that say why, `shortcut:` comments for known limits.
- Commit steps below apply only if the user wants commits; otherwise skip them. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- Hand disappears or `grab` closes mid-precision, then returns → fresh state, no stale anchor or glide (Task 3 test).
- A user config still containing `fine`/`reach`/`fine_speed`/`tap_damp` for `desktop_pointer` → loads, no crash (Task 3 test).
- Degenerate geometry (`view_top ≤ bottom`, `coverage` tiny) → no division by zero, output stays in 0…1 (Task 3 test).
- Duplicate or out-of-order frame timestamps (`dt ≤ 0`) → no NaN, no jump (Task 2 test).
- Not under Hyprland, or overlay disabled/unavailable, with `precision_ring = true` → nothing raised, no ring (Tasks 4 and 5).

## File Structure

- Create `application/orion/gestures/fingers.py`: `FingerMotion`, tap detector shared by both pointers.
- Create `application/orion/gestures/precision.py`: `PrecisionLock`, the cursor state machine.
- Modify `application/orion/gestures/twohand.py`: `Pointer` uses `FingerMotion`; `DesktopPointer` rewritten on `PrecisionLock`.
- Modify `application/orion/engine.py`, `application/orion/overlay.py`: ring signalling.
- Modify `application/orion/overlay_gtk.py`: ring window, cursor polling, animation.
- Modify `application/orion/default.toml`, `application/web/src/views/Settings.svelte`, `application/web/src/views/Gestures.svelte` (help text only), `application/README.md`.
- Create `scripts/pointer_replay.py`: offline metrics over an `.orec` recording.
- Tests: `application/tests/test_core.py` (add; replace the old fine-offset tests).

---

### Task 1: Extract the tap detector

**Files:**
- Create: `application/orion/gestures/fingers.py`
- Modify: `application/orion/gestures/twohand.py` (`Pointer._damp`)
- Test: `application/tests/test_core.py`

**Interfaces:**
- Produces: `class FingerMotion` with `__init__(self, window: float = 0.12, hand_max: float = 250.0)` and `update(self, t: float, tips_rel_palm: np.ndarray, speed: float, trigger: float, still: float) -> bool`. Returns True on frames where a fingertip has moved ≥ `trigger` mm (relative to the palm, over the last `window` s) and the palm speed at the start of that window was < `still` mm/s; always False while `speed > hand_max`. `reset()` clears history. One instance per hand side.
- Consumes: nothing.

- [ ] **Step 1: Write failing tests** `test_finger_motion_flags_a_tap_from_rest`, `test_finger_motion_ignores_a_moving_palm`, `test_finger_motion_ignores_small_noise`:

```python
def _tips(dy):  # five fingertips; the index drops by dy mm relative to the palm
    t = np.zeros((5, 3)); t[1, 1] = -dy; return t

def test_finger_motion_flags_a_tap_from_rest():
    f = FingerMotion()
    assert not any(f.update(i / 115, _tips(0), 5.0, 5, 60) for i in range(10))
    assert any(f.update((10 + i) / 115, _tips(i * 1.5), 10.0, 5, 60) for i in range(8))

def test_finger_motion_ignores_a_moving_palm():
    f = FingerMotion()
    assert not any(f.update(i / 115, _tips(i * 1.5), 200.0, 5, 60) for i in range(20))  # palm 200 mm/s ≥ still

def test_finger_motion_ignores_small_noise():
    f = FingerMotion(); rng = np.random.default_rng(0)
    assert not any(f.update(i / 115, _tips(rng.normal(0, 0.3)), 3.0, 5, 60) for i in range(200))
```

- [ ] **Step 2: Run** `python -m pytest tests/test_core.py -k finger_motion -v` → FAIL (`FingerMotion` undefined).
- [ ] **Step 3: Implement** `FingerMotion` in `fingers.py` using a deque of `(t, tips, speed)` trimmed to `window`; compare newest vs oldest tips (max over fingers of the norm of the difference) and gate on the oldest entry's speed. Then change `Pointer._damp` to call it (one `FingerMotion` per side in `self.damped`), keeping `TAP_HOLD`/`TAP_RELEASE`/`tap_damp` behavior and removing the `TAP_WINDOW`/`TAP_HAND_MAX` class constants it replaces.
- [ ] **Step 4: Run** `python -m pytest tests -q` → all pass (existing air-mouse tap tests included).
- [ ] **Step 5: Commit** `refactor: extract FingerMotion tap detector`.

---

### Task 2: PrecisionLock state machine

**Files:**
- Create: `application/orion/gestures/precision.py`
- Test: `application/tests/test_core.py`

**Interfaces:**
- Produces: `class PrecisionLock` with `__init__(self, cfg: dict)` (keys `precision, dwell, enter_speed, exit_speed, radius, edge, rest, glide, tap_hold`), `step(self, t: float, p: np.ndarray, speed: float, tap: bool, lo: np.ndarray, hi: np.ndarray) -> np.ndarray` returning the cursor in mm (same space as `p`, always inside `lo…hi`), and property `precise: bool`. `p` is the filtered palm (mm); `lo`/`hi` are the view limits.
- Consumes: nothing.

Algorithm (not determined by the signature). Per call: `dt = clamp(t − t_prev, 1e-3, 0.1)`; `room = min((p−lo).min(), (hi−p).min())`. Keep a rest latch `lp` (holds until `|p−lp| > rest`, then trails by `rest`) and a ~0.25 s history of `(t, cursor)`.
- Tap rising edge (`tap` and not previously tapping): cursor = history entry from ≈0.15 s ago; `hold_until = t + tap_hold`; if coarse, enter precision.
- Coarse: track how long `speed < enter_speed and room > edge` has held; at `dwell` enter precision (`anchor = p`, `lp = p`, cursor unchanged). Otherwise cursor = `p + (cursor − p)·exp(−3·dt/glide)`.
- Precision: leave (back to coarse, cursor unchanged so the glide takes over) if `speed > exit_speed` or `room ≤ edge`. Else `cursor += gain(r)·(lp − lp_prev)`, zero while `t < hold_until`, with `r = |p − anchor|` and `gain(r) = precision + (1 − precision)·min(r/radius, 1)²`.
- Finally clip the cursor to `lo…hi`.

- [ ] **Step 1: Write failing tests** with a helper `run(lock, xs, speeds, t0=0.0, dt=1/115)`:
  - `test_coarse_is_stateless`: fast walk (speed 300) to x=40 ends at x=40; a second lock reaching 40 by a different fast path ends at the same value (±1e-9).
  - `test_precision_scales_slow_motion`: after 0.2 s still, a 10 mm slow move (speed 20) moves the cursor `10·precision ± 0.5` mm.
  - `test_gain_reaches_one_at_radius`: past `radius` mm of slow travel, per-frame cursor step equals the hand step (±1e-6).
  - `test_fast_move_glides_to_the_hand`: after building an offset, speed 300 jumps: cursor converges to `p` within `glide + 0.05` s and no per-frame move exceeds the offset size.
  - `test_edge_walk_always_reaches_the_limit`: slow walk at 20 mm/s to `x = hi[0]` ends with `cursor[0] == hi[0]` (exact), from a start inside precision.
  - `test_rest_latch_ignores_tremor`: ±0.1 mm noise inside precision leaves the cursor unchanged (±1e-9).
  - `test_tap_rewinds_and_holds`: still hand; palm dips 5 mm over 8 frames with `tap=True` from frame 3; cursor within 0.5 mm of its pre-dip value and stays for `tap_hold`, then follows again at `precision` gain.
  - `test_duplicate_timestamps_do_not_blow_up`: two calls with identical `t` return finite values.
- [ ] **Step 2: Run** `-k "coarse_is or precision_ or gain_ or glides or edge_walk or rest_latch or tap_rewinds or duplicate"` → FAIL (import error).
- [ ] **Step 3: Implement** `PrecisionLock` per the algorithm above in `precision.py` (numpy only, no engine imports).
- [ ] **Step 4: Run** the same selection → PASS; then `python -m pytest tests -q` → all pass.
- [ ] **Step 5: Commit** `feat: PrecisionLock cursor state machine`.

---

### Task 3: Rewrite DesktopPointer on PrecisionLock

**Files:**
- Modify: `application/orion/gestures/twohand.py` (`DesktopPointer`)
- Modify: `application/orion/default.toml` (`[gestures.desktop_pointer]`), `application/web/src/views/Gestures.svelte` (`HELP` entries), `application/README.md`
- Test: `application/tests/test_core.py` (delete `test_desktop_pointer_slow_motion_is_scaled_down`, `test_desktop_pointer_fast_sweep_clears_the_offset_and_edges_always_reach`, `test_desktop_pointer_rest_latch_ignores_tremor`, and the `_desktop*` helpers they use; keep the mapping, margin and fist tests)

**Interfaces:**
- Consumes: `PrecisionLock` (Task 2), `FingerMotion` (Task 1).
- Produces: `DesktopPointer.params` = `Pointer.params` minus `tap_damp`, plus `view_width, view_top, coverage, bottom` (existing defaults) and `precision, dwell, enter_speed, exit_speed, radius, edge, rest, glide, tap_hold` (Global Constraints values, with sensible min/max ranges); attribute `precise: set[str]` of hand sides currently in precision. `check(h, p)` still returns the (u, v) array clipped to 0…1, or `None` when `grab ≥ max_grab`.

- [ ] **Step 1: Write failing tests**
  - `test_desktop_pointer_walk_to_each_limit_hits_the_screen_edge`: for left/right/top limits, slow walk (22 mm/s) ends with u or v exactly 0 or 1.
  - `test_desktop_pointer_precise_set_tracks_the_mode`: still hand for 0.3 s → `"right" in g.precise`; fast sweep → empty.
  - `test_desktop_pointer_tap_from_rest_keeps_the_cursor`: hand rests 0.5 s, then the palm dips 5 mm while the index curls (use `extended=set(FINGERS) - {"index"}`); max |Δu| after the dip < 1 mm / `view_width`.
  - `test_desktop_pointer_resets_when_the_hand_returns`: hand vanishes for 1 s mid-precision and returns elsewhere → first value equals the plain mapping of the new position.
  - `test_desktop_pointer_ignores_removed_settings`: `REGISTRY["desktop_pointer"]({"fine": 0.5, "reach": 10, "fine_speed": 5, "tap_damp": 1})` runs frames without error.
  - `test_desktop_pointer_degenerate_geometry_stays_in_range`: `view_top=151, bottom=150, coverage=0.5` → every value within 0…1 and finite.
- [ ] **Step 2: Run** `-k desktop_pointer` → new tests FAIL.
- [ ] **Step 3: Implement.** In `DesktopPointer.check`: keep the existing filtering/`fresh` handling; per side keep a `PrecisionLock` (rebuilt on `fresh`, config from `p`) and a `FingerMotion`; compute `lo/hi` from the view params as the current code does, `speed` from `self.filters[h.side].dx`, `tap` from `FingerMotion.update(...)` using `tap_trigger`/`tap_still`; return `PrecisionLock.step(...)` mapped to (u, v) and clipped. Do not call `Pointer._damp` (override so it is skipped). Maintain `self.precise`; clear a side's entry when its state ends. Guard `top − bottom` and `half` against ≤ 0. Remove `tap_damp` from `params`; unknown config keys are already ignored by `Gesture`.
- [ ] **Step 4: Update defaults and docs.** `default.toml`: replace the `fine…responsive` lines under `[gestures.desktop_pointer]` with the new keys and one-line comments. `Gestures.svelte` `HELP`: add one-line explanations for `precision`, `dwell`, `enter_speed`, `exit_speed`, `radius`, `edge`, `rest`, `glide`, `tap_hold`, `tap_trigger`, `tap_still`. `README.md`: replace the desktop-pointer tuning text. Run `npm --prefix web run build --silent` from `application/`.
- [ ] **Step 5: Run** `python -m pytest tests -q` → all pass.
- [ ] **Step 6: Commit** `feat: desktop pointer precision lock`.

---

### Task 4: Ring signalling (engine → overlay host) and setting

**Files:**
- Modify: `application/orion/engine.py` (`on_frame`), `application/orion/overlay.py`, `application/orion/default.toml` (`[overlay]`), `application/web/src/views/Settings.svelte`
- Test: `application/tests/test_core.py`

**Interfaces:**
- Consumes: `DesktopPointer.precise` (Task 3).
- Produces: `OverlayHost.ring(self, on: bool)`: sends `{"type": "ring", "on": on}` only when `cfg.get("precision_ring", True)` is true and the process is running; `configure` also forwards `precision_ring` in its `config` message. `Engine._sync_ring()` called at the end of `on_frame`: compares `any(g.precise for g in self.gestures if g.name == "desktop_pointer")` with `self._ring` and calls `self.overlay.ring(...)` only on change. Setting `[overlay] precision_ring = true` in `default.toml`.

- [ ] **Step 1: Write failing tests** with a fake overlay object recording `ring(on)` calls assigned to `engine.overlay`:
  - `test_engine_signals_ring_only_on_change`: still hand then sweep through `engine.on_frame` → calls `[True, False]`.
  - `test_overlay_host_ring_respects_the_setting`: `OverlayHost` with `cfg={"precision_ring": False}` and a stub `send` records nothing; with `True` records `{"type": "ring", "on": True}`.
  - `test_ring_without_overlay_is_a_noop`: `engine.overlay = None` → `on_frame` runs without error.
- [ ] **Step 2: Run** `-k ring` → FAIL.
- [ ] **Step 3: Implement** the signatures above; add the `precision_ring` toggle beside "Show overlay" in `Settings.svelte` (`<Switch bind:checked={o.precision_ring} label="Precision ring" />`) with a one-line description; rebuild the web UI. When the setting turns off while the ring is visible, `configure` must send `{"type": "ring", "on": false}`.
- [ ] **Step 4: Run** `python -m pytest tests -q` → all pass.
- [ ] **Step 5: Commit** `feat: precision ring signalling and setting`.

---

### Task 5: Draw and animate the ring

**Files:**
- Modify: `application/orion/overlay_gtk.py`

**Interfaces:**
- Consumes: messages `{"type": "ring", "on": bool}` and `config` with `precision_ring`, `opacity` (Task 4).
- Produces: a ring drawn around the cursor with the animation from Global Constraints. No Python-side API.

This task is verified by hand (GTK/Wayland); run it only on the user's Hyprland session.

- [ ] **Step 1: Probe (throwaway, in the scratchpad dir, not committed).** Confirm a transparent, click-through, full-monitor layer-shell `Gtk.DrawingArea` can draw a ring at Hyprland's `j/cursorpos` (minus the monitor's `x`, `y`), redrawn on a 16 ms timer, and that clicks pass through. Expected: ring tracks the cursor, input unaffected, CPU low at 4K. If the full-monitor surface is too heavy, fall back to a small (96 px) surface moved with anchor + margins; record the choice in a code comment.
- [ ] **Step 2: Implement** in `Overlay`: second layer-shell window (namespace `orion-ring`, overlay layer, no keyboard, empty input region, anchored to all edges of the focused monitor); `handle` for `ring` and `precision_ring` in `config`; a cursor poll via a new `cursor_position()` helper next to `focused_connector()` (returns `None` on any error, never raises); a 16 ms animation timer that runs only while the ring is visible or animating; ease-out cubic over 160 ms (44 → 20 px, alpha 0 → 1) when on and 120 ms (20 → 44 px, alpha 1 → 0) when off; then unmap. A repeated `on` while already on does not restart the animation; if the cursor moves to another monitor, remap onto it (re-check the focused connector about every 250 ms).
- [ ] **Step 3: Verify by hand.** With Orion running: hold still → ring zooms in; sweep → ring zooms out and disappears; Settings toggle off → no ring and no leftover surface (`hyprctl layers | grep orion-ring`); cursor crossing monitors keeps the ring on the right one; with Hyprland unreachable, no traceback.
- [ ] **Step 4: Commit** `feat: animated precision ring overlay`.

---

### Task 6: Replay metrics tool

**Files:**
- Create: `scripts/pointer_replay.py`
- Test: `application/tests/test_core.py`

**Interfaces:**
- Consumes: `orion.sources.from_dict`/`to_dict`, `Frame`, `REGISTRY["desktop_pointer"]`.
- Produces: `metrics(frames: list[Frame], overrides: dict | None = None) -> dict` with keys `rest_jitter_px` (RMS cursor change per frame over frames where palm speed < 20 mm/s, for a 3840×2160 screen), `max_jump_px` (largest per-frame cursor move), `reached_edges` (bool per `left/right/top/bottom` whose extreme u/v hit 0 or 1), and a CLI `python scripts/pointer_replay.py FILE.orec [key=value ...]` printing it as JSON.

- [ ] **Step 1: Write failing test** `test_pointer_replay_metrics_on_a_synthetic_recording`: build frames with `make_hand` (rest, then a sweep to the left limit), call `metrics`, assert `rest_jitter_px < 1`, `reached_edges["left"] is True`, `max_jump_px` finite.
- [ ] **Step 2: Run** → FAIL (module not importable).
- [ ] **Step 3: Implement** `metrics` and the CLI (gzip lines → `from_dict`, as `ReplaySource.run` does).
- [ ] **Step 4: Run** `python -m pytest tests -q` → all pass; run the CLI on one of the user's real recordings if one exists in `~/.local/share/orion-renewal/recordings/`.
- [ ] **Step 5: Commit** `feat: pointer replay metrics`.

---

## Self-review

- **Spec coverage:** model and modes (Task 2, 3); leaving/glide (2); steady palm (2); taps incl. shared detector and air-mouse unchanged (1, 2, 3); ring setting, animation, wiring, drawing, risk probe (4, 5); settings table, defaults, removed keys (3); unit tests and replay tool (2, 3, 6).
- **Type consistency:** `FingerMotion.update(...)-> bool` (Task 1) is the `tap` input of `PrecisionLock.step` (Task 2) used in Task 3; `DesktopPointer.precise` (Task 3) is what `Engine._sync_ring` reads (Task 4); the `ring` message shape matches between `OverlayHost.ring` (4) and `Overlay.handle` (5).
- **Out of scope per spec:** wrist-tilt fine control, air-mouse changes, ring styling, per-profile precision settings.

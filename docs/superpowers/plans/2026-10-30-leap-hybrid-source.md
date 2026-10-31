# Leap Hybrid Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `leap_hybrid` source: the Leap supplies the body (position, motion, palm plane, hand identity, and all of OrionDo's input), MediaPipe supplies the fingers, and the Leap's own fingers are the fallback.

**Architecture:** `LeapHybridSource` subclasses `LeapMediaPipeSource`, whose worker now stores its newest hand instead of emitting frames. Each Leap tracking event is merged with that hand by a stateful `Merger` and emitted as one frame whose new `leap` field holds the untouched Leap frame; the engine hands that field to OrionDo and the merged frame to every other gesture.

**Tech Stack:** Python 3.14 (`.venv`), numpy, the `leap_mp` pipeline (MediaPipe on the GPU), Svelte 5 UI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-30-leap-hybrid-source-design.md`

## Global Constraints

- New source name `leap_hybrid`; the Leap (`leap`), MediaPipe (`leap_mp`) and webcam sources behave exactly as before (their tests pass unchanged, apart from the palm-up guard in Task 1).
- `max_age` 0.12 s; thumb extended at `thumb_out` 45 mm with hysteresis (on at 48, off below 40); palm-up guard: `normal[1] > 0.3`. One hand: a second Leap hand passes through unchanged.
- Merged hand keeps the Leap's `id`, `side`, `confidence`, `palm`, `stable`, `velocity`, `normal`, `direction`; takes MediaPipe's finger joints (rotated into the Leap's palm frame, then placed at the Leap's palm), `extended` (thumb by the lateral rule), `pinch` and `grab`.
- `Frame.leap` is set only by the hybrid; OrionDo is the only gesture that reads it.
- Tests: from `application/`, `../.venv/bin/python -m pytest tests -q` (baseline now 282 passed, 42 skipped). A real MediaPipe landmarker must be `close()`d in any test that creates one, or pytest cannot exit.
- Every commit message ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- MediaPipe stale, absent or raising: the Leap hand passes through and a frame still goes out for every Leap event. (Tasks 3, 4)
- Two Leap hands: only the one whose side matches MediaPipe's is merged; the other is untouched. (Tasks 3, 4)
- OrionDo gets the Leap frame with the same filtered sides the merged frame has, or its menu would look for the wrong hand. (Task 2)
- Palm up: touch poses silent, but open palm, OK and fist still fire. (Task 1)
- A degenerate MediaPipe hand (zero-length direction or normal) produces no NaN joints. (Task 3)

---

### Task 0: Commit the pending work

**Files:** everything uncommitted (thumbs_up removal, hybrid spec and plan, the script's new phases).

- [ ] **Step 1:** Stage `application/`, `README.md`, `CLAUDE.md` and `scripts/`; commit them as `feat: remove the thumbs_up gesture; calibration script covers palm-up, end-on and flat finger phases`.
- [ ] **Step 2:** Commit `docs/superpowers/` as `docs: Leap hybrid source spec and plan`.
- [ ] **Step 3:** `git status --short` shows nothing but ignored files; `../.venv/bin/python -m pytest tests -q` → 282 passed, 42 skipped.

---

### Task 1: Palm-up guard on touch poses

**Files:**
- Modify: `application/orion/gestures/fingers.py` (`thumb_touch`)
- Test: `application/tests/test_core.py`

**Interfaces:**
- Produces: `PALM_UP = 0.3` in `fingers.py`; `thumb_touch(h)` returns `None` when `h.normal[1] > PALM_UP`.

- [ ] **Step 1: Write the failing tests** `test_palm_up_touches_are_ignored` and `test_palm_sideways_still_touches`: with `with_thumb_at(make_hand(normal=(0, 1, 0)), "pinky")`, `thumb_contact(hand) == "pinky"` but `thumb_touch(hand) is None` and `run(REGISTRY["touch_pinky"](), hold(hand)) == []`; with `normal=(1, 0, 0)` the same hand gives `thumb_touch == "pinky"`. Also assert an upward-facing open hand (`make_hand(normal=(0, 1, 0))`) still fires `open_palm` and an upward fist fires `fist`.
- [ ] **Step 2:** Run `../.venv/bin/python -m pytest tests/test_core.py -q -k "palm_up or palm_sideways"`. Expected: the first FAILS (touch fires palm-up).
- [ ] **Step 3: Implement** the guard inside `thumb_touch` with a one-line comment (the palm hides the fingers from the camera).
- [ ] **Step 4:** Run the whole suite. Expected: all pass (the recorded touch fixtures are palm down).
- [ ] **Step 5: Commit** `feat: touch poses ignore a palm-up hand`.

---

### Task 2: `Frame.leap` and OrionDo on the Leap frame

**Files:**
- Modify: `application/orion/frame.py` (`Frame`), `application/orion/engine.py` (`on_frame`)
- Test: `application/tests/test_core.py`

**Interfaces:**
- Produces: `Frame.leap: Frame | None = None` (last field). `Engine.on_frame` gives the gesture named `"oriondo"` `frame.leap` (when set) and every other gesture `frame`; the Leap frame's hands get the sides the `Handedness` filter chose, matched by hand `id`.

- [ ] **Step 1: Write the failing test** `test_oriondo_gets_the_leap_frame_with_filtered_sides` (tmp config, `Engine(Config(path), dry_run=True)`, `engine.gestures = [Spy("oriondo"), Spy("swipe")]` where `Spy.update(frame)` records the frame and returns `()`): `leap_hand = make_hand("right")`, `merged = dataclasses.replace(leap_hand, pinch=0.9)`, frame `Frame(t=1.0, hands=(merged,), source="leap_hybrid", leap=Frame(t=1.0, hands=(leap_hand,)))`. After `engine.on_frame(frame)`: the oriondo spy saw `pinch == leap_hand.pinch`, the swipe spy saw `pinch == 0.9`, and both saw `side == "left"` (the filter's preferred hand), plus `Frame(t=0).leap is None`.
- [ ] **Step 2:** Run it. Expected: FAIL (`Frame` has no `leap`).
- [ ] **Step 3: Implement** the field and the routing in `on_frame` (a small helper that copies sides by id from the filtered frame onto `frame.leap`).
- [ ] **Step 4:** Run the whole suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat: Frame.leap carries the Leap's own frame; OrionDo reads it`.

---

### Task 3: `Merger`

**Files:**
- Create: `application/orion/leap_hybrid.py`
- Create: `application/tests/test_leap_hybrid.py`

**Interfaces:**
- Consumes: `Hand`, `Finger` from `orion.frame`; `make_hand` from `orion.sim` (tests).
- Produces: `Merger(cfg: dict)` with `cfg` keys `max_age`, `thumb_out`; `Merger.__call__(leap: Hand, mp: Hand | None, age: float) -> Hand`. Returns `leap` itself (same object) when `mp` is `None`, `age > max_age`, or `mp.side != leap.side`. Otherwise a copy of `leap` per the Global Constraints. (The spec names a function; hysteresis needs state, so it is a callable object.)
- Produces: `thumb_lateral(hand: Hand) -> float`: the thumb tip's signed offset from `hand.palm` in mm across the image plane (Leap x, z) along the unit vector from the pinky knuckle (`fingers[4].joints[1]`) to the index knuckle (`fingers[1].joints[1]`).

- [ ] **Step 1: Write the failing tests** in `tests/test_leap_hybrid.py` (helper `skewed(hand, degrees=20, shift=(50, 0, 0))` returns a copy with every joint offset from the palm rotated about the z axis and the palm, `normal` and `direction` rotated and shifted likewise):
  - `test_merge_keeps_the_leap_body_and_undoes_the_skew`: `mp = skewed(leap)` with the index finger's `extended` flipped; the merged hand's `palm`, `stable`, `velocity`, `normal`, `direction`, `side`, `id`, `confidence` equal the Leap's; every finger's joints match the Leap hand's within 1e-3; `extended` for index to pinky equals `mp`'s; `pinch` and `grab` equal `mp`'s.
  - `test_merge_falls_back_to_the_leap_hand`: `Merger(cfg)(leap, None, 0)`, `(leap, mp, 0.2)` and `(leap, wrong_side_mp, 0)` each `is leap`.
  - `test_merge_survives_a_degenerate_mediapipe_hand`: `mp` with zero `direction` and `normal` → all joints finite.
  - `test_thumb_rule_has_hysteresis`: with the thumb tip placed at lateral offsets 60, 44, 38, 44, 49 in turn on the same `Merger`, the thumb's `extended` is True, True, False, False, True.
  - `test_thumb_lateral_is_signed`: a thumb tip on the pinky side of the palm gives a negative value, on the index side a positive one.
- [ ] **Step 2:** Run `../.venv/bin/python -m pytest tests/test_leap_hybrid.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `thumb_lateral` and `Merger` in `leap_hybrid.py` (module docstring: the Leap is the body, MediaPipe the fingers). Orthonormal bases from each hand's `direction` and `normal`; rotation `R = B_leap @ B_mp.T`; joints `leap.palm + (joints - mp.palm) @ R.T`; if a basis vector has norm below 1e-6 use `R = I`. The thumb flag is decided from the unrotated `mp` hand with the hysteresis state held on the `Merger`.
- [ ] **Step 4:** Run the file. Expected: PASS.
- [ ] **Step 5: Commit** `feat: leap_hybrid Merger (Leap body, MediaPipe fingers)`.

---

### Task 4: `LeapHybridSource`

**Files:**
- Modify: `application/orion/leap_hybrid.py`
- Test: `application/tests/test_leap_hybrid.py`

**Interfaces:**
- Consumes: `LeapMediaPipeSource` (`_emit(t, hands)`, `_process`, `_setup`, `status`), `Merger`, `from_leap`.
- Produces: `LeapHybridSource(on_frame, on_image, ir_fps=30, *, cfg, hybrid, rectifier_factory=None, finder_factory=None)`; `name = "leap_hybrid"`; `cfg` is the `[leap_mp]` table, `hybrid` the `[leap_hybrid]` table. `_emit(t, hands)` stores `(t, hands[0] or None)` and does not call `on_frame`. `_tracking(e)` builds `L = from_leap(e)`, merges the Leap hand whose side matches the stored MediaPipe hand (age `time.monotonic() - t`), leaves other hands alone, emits `Frame(t=L.t, fps=L.fps, hands=…, source="leap_hybrid", leap=L)`, and sets `status["fingers"]` to `"mediapipe"` or `"leap"`. Any exception in the merge emits the Leap frame unchanged.

- [ ] **Step 1: Write the failing tests** (helper `leap_event(*hands)` builds the `SimpleNamespace` event `from_leap` reads, as in `test_core.test_from_leap_with_fake_structs`; fake `finder_factory`/`rectifier_factory` as in `test_leap_mp.py`):
  - `test_hybrid_emits_one_merged_frame_per_leap_event`: after `src._emit(time.monotonic(), (mp_hand,))`, `src._tracking(event)` emits a frame with `source == "leap_hybrid"`, `frame.leap.hands[0]` equal to the Leap's, `frame.hands[0].extended` equal to MediaPipe's for the index, and `status["fingers"] == "mediapipe"`.
  - `test_hybrid_without_mediapipe_is_the_leap`: no `_emit` yet → `frame.hands[0]` equals the Leap hand and `status["fingers"] == "leap"`.
  - `test_hybrid_merges_only_the_matching_hand`: two Leap hands (left, right) and an MP hand on the left → the right hand is the identical object.
  - `test_hybrid_survives_a_merge_error`: monkeypatch `Merger.__call__` to raise → a frame with the Leap hands is still emitted.
  - `test_hybrid_worker_does_not_emit_frames`: `src._process(PAIR, 0.0)` with agreeing fake views stores a hand and calls `on_frame` zero times.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** the class as specified.
- [ ] **Step 4:** Run the whole suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat: LeapHybridSource`.

---

### Task 5: Wiring (config, engine, UI)

**Files:**
- Modify: `application/orion/default.toml`, `application/orion/config.py:34`, `application/orion/engine.py` (`start`), `application/web/src/views/Settings.svelte:33`, `application/web/src/App.svelte:69`
- Test: `application/tests/test_leap_hybrid.py`

**Interfaces:**
- Produces: `[leap_hybrid]` table with `max_age = 0.12`, `thumb_out = 45`; `Config.load` fills its defaults; `Engine.start` maps `"leap_hybrid"` to `LeapHybridSource` with `cfg=self.cfg["leap_mp"], hybrid=self.cfg["leap_hybrid"]`; Settings option `<option value="leap_hybrid">Leap + MediaPipe</option>`; the sidebar label for the source is `Leap + MediaPipe`, followed by `· mediapipe|leap` from `s.fingers`.

- [ ] **Step 1: Write the failing tests** `test_leap_hybrid_defaults_load` (a user file with only `[leap_hybrid] max_age = 0.2` still gets `thumb_out == 45`) and `test_engine_starts_the_leap_hybrid_source` (as `test_engine_starts_the_leap_mp_source`: patch `Source.start` and `watch_active_window`, `general.source = "leap_hybrid"`, `isinstance(engine.source, LeapHybridSource)`).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** the wiring as listed.
- [ ] **Step 4:** Run `../.venv/bin/python -m pytest tests -q`, then in `application/web` `npm test && npm run build`. Expected: all pass, build succeeds.
- [ ] **Step 5: Commit** `feat: Leap + MediaPipe (hybrid) source option in config, engine and UI`.

---

### Task 6: Compare script `--hybrid` and the live measurement

**Files:**
- Modify: `scripts/leap_mp_compare.py`; append a Results section to the hybrid spec

**Interfaces:**
- Produces: `leap_mp_compare.py --hybrid [speed] [new]` runs `LeapHybridSource`; for every emitted frame the "MediaPipe" series is `frame` (merged) and the "Leap" series is `frame.leap`, so the existing report compares merged against Leap. Saved files are named `…-calibration-hybrid.orec` and `…-calibration-leap.orec`.

- [ ] **Step 1: Implement** `--hybrid` (no test: a measuring tool). Smoke-run it with `XDG_DATA_HOME` pointing at a temp directory and speed 0.2: it must finish without errors.
- [ ] **Step 2: Live session.** The user runs `.venv/bin/python scripts/leap_mp_compare.py --hybrid` (about 5½ minutes, app paused). Read the saved recordings and check the five acceptance criteria in the spec; also confirm by hand that OrionDo opens with the peace sign and fires an item as on the plain Leap source.
- [ ] **Step 3:** For any criterion that fails, record the numbers and the cause in the spec's Results section (tuning, for example the thumb threshold or the depth scale, is a follow-up task decided with the user).
- [ ] **Step 4: Commit** `feat: compare script --hybrid; hybrid results`.

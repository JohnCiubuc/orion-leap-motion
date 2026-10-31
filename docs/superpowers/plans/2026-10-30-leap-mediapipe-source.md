# Leap (MediaPipe) Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Leap (MediaPipe)" tracking source that runs MediaPipe Hands on both undistorted Leap IR images, cross-checks the two views, and feeds ordinary `Frame`/`Hand` objects to the existing gesture pipeline.

**Architecture:** `LeapSource` gets small hooks; a new `LeapMediaPipeSource` subclass copies each image pair into a latest-pair slot, a worker rectifies both images to one shared pinhole, finds a hand in each with crop-based MediaPipe, and `Fusion` triangulates (both views agree), falls back to one view, or drops the hand (views disagree). A live bring-up task calibrates axis/label signs and measures against Leap's own tracking.

**Tech Stack:** Python 3.14 (`.venv`), numpy, OpenCV 5 (`cv2.remap`), MediaPipe 1.2 Hand Landmarker, LeapC cffi, Svelte 5 UI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-30-leap-mediapipe-source-design.md`

## Global Constraints

- One hand only; webcam development is paused (reuse webcam code, change its behaviour not at all: `tests/test_webcam.py` must pass unchanged).
- Camera image 640×240, 8-bit; rectified model: pinhole, f = 143 px, 640×240, principal point at the image centre, identical for both cameras. Baseline from `LeapExtrinsicCameraMatrix`, fallback 40 mm.
- Search windows: 240×240 at x = 0, 200, 400, one per frame in rotation. Tracking window: 1.6 × hand bounding-box side, clamped to 96–240 px, centred on the last position, resized to 256 for MediaPipe. Drop to search after 3 consecutive misses.
- Agreement: median row difference < `agree_px` (4.0); ≥ 18 of 21 disparities positive; median depth in 60–600 mm. Hold a missed hand `hold` = 0.08 s. `min_score` 0.5, `hand_mm` 95.
- The pure parts of `orion/leap_mp.py` import neither `cv2` nor `mediapipe` at module level.
- Tests: from `application/`, run `../.venv/bin/python -m pytest tests -q` (system Python has no cv2). Baseline before this plan: 262 passed, 14 skipped.
- Guesses carry `# shortcut: <limit>, <when to upgrade>` comments. Every commit message ends with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- A frame pair with no hand, or an exception inside the detector, must still emit a frame (empty hands), so Leap's watchdog never restarts the controller and an open menu closes. (Task 7)
- Hand at the image edge: crops stay inside the frame and landmarks are never NaN or out of range. (Task 4)
- Only one camera sees the hand (the other is blocked or the hand is at its edge): a hand is still produced, status says which camera. (Task 5)
- MediaPipe slower than the camera: only the newest pair is processed, stale pairs are dropped, latency does not grow. (Task 7)
- Missing `mediapipe`/`cv2`, or images arriving before calibration works: status error text, no crash. (Task 7)

---

### Task 0: Housekeeping commits

**Files:** `application/orion/sources.py`, the two spec files, this plan.

- [ ] **Step 1:** `git add application/orion/sources.py && git commit` with message `fix: Restart controller's unpause passed an opaque struct (get_connection_ptr()[0])`.
- [ ] **Step 2:** `git add docs/superpowers && git commit` with message `docs: Leap (MediaPipe) source spec and plan`.
- [ ] **Step 3:** `git status --short` shows nothing but ignored files.

---

### Task 1: Split `points_to_hand` out of `landmarks_to_hand`

**Files:**
- Modify: `application/orion/webcam.py` (`landmarks_to_hand`, lines ~99-124)
- Test: `application/tests/test_webcam.py`

**Interfaces:**
- Produces: `points_to_hand(w: np.ndarray, palm: np.ndarray, label: str, score: float, prev_extended: frozenset[str] = frozenset(), hid: int = 0) -> Hand`. `w` is (21, 3) in mm, already in Leap axes and absolute position, MediaPipe landmark order; `palm` (3,) float32.

- [ ] **Step 1: Write the failing test** `test_points_to_hand_reads_a_leap_hand` in `tests/test_webcam.py`: with `hand = facing(extended={"index", "middle"})`, `h = points_to_hand(landmarks(hand), palm_of(hand), "right", 0.9)`; assert `h.extended == hand.extended`, `np.allclose(h.normal, hand.normal, atol=0.1)`, `np.allclose(h.direction, hand.direction, atol=0.1)`, `h.pinch == 0` and `h.side == "right"`.
- [ ] **Step 2:** Run `../.venv/bin/python -m pytest tests/test_webcam.py -k points_to_hand -q`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement.** Move everything in `landmarks_to_hand` after `w` has been pitched and shifted onto `palm` (the finger loop, `pinch`, `grab`, `normal`, `direction`, the `Hand(...)` return) into `points_to_hand`; `landmarks_to_hand` ends with `return points_to_hand(w, palm, det.label, det.score, prev_extended, hid)`. `normal` keeps its `label == "left"` sign flip.
- [ ] **Step 4:** Run `../.venv/bin/python -m pytest tests -q`. Expected: all pass, same counts as baseline plus 1.
- [ ] **Step 5: Commit** `refactor: points_to_hand split out of landmarks_to_hand`.

---

### Task 2: Pinhole and Rectifier

**Files:**
- Create: `application/orion/leap_mp.py`
- Create: `application/tests/test_leap_mp.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) Pinhole(f: float = 143.0, w: int = 640, h: int = 240)` with properties `cx = w / 2`, `cy = h / 2`.
- Produces: `Rectifier(project: Callable[[str, tuple[float, float, float]], tuple[float, float]], pinhole: Pinhole = Pinhole())` and `.rectify(camera: str, gray: np.ndarray) -> np.ndarray`; `camera` is `"left"` or `"right"`. `project(camera, ray)` returns the raw-image pixel `(x, y)` of a ray `(x, y, z)`; for each output pixel the ray is `((u - cx) / f, (v - cy) / f, 1)`. `rectify` uses `cv2.remap` (bilinear, zero border), importing `cv2` inside the method.

- [ ] **Step 1: Write the failing test** `test_rectifier_undoes_distortion_and_camera_offset` (`pytest.importorskip("cv2")`): `pin = Pinhole(f=40, w=160, h=60)`; fake projector with barrel distortion `k = 0.15` and a 3 px vertical offset for `"right"`: for ray `(x, y, 1)` with `r2 = x*x + y*y` return `(80 + 40*x*(1 + k*r2), 30 + 40*y*(1 + k*r2) + (3 if camera == "right" else 0))`. For each camera render a Gaussian blob (sigma 1.2) at `project(camera, (0.5, -0.3, 1))` on a 60×160 float image; after `rectify`, the blob's intensity-weighted centroid is within 0.5 px of `(pin.cx + pin.f*0.5, pin.cy + pin.f*-0.3)` = `(100, 18)`.
- [ ] **Step 2:** Run it. Expected: FAIL (ImportError for `orion.leap_mp`).
- [ ] **Step 3: Implement** `Pinhole` and `Rectifier` in `leap_mp.py` (module docstring: what the module is, that pure parts need no cv2/mediapipe). Build `float32` maps with `numpy` meshgrid then one projector call per pixel; store per camera.
- [ ] **Step 4:** Run the test. Expected: PASS.
- [ ] **Step 5: Commit** `feat: leap_mp Rectifier (undistort both IR cameras to one pinhole)`.

---

### Task 3: Geometry: triangulate, backproject, axes, agreement

**Files:**
- Modify: `application/orion/leap_mp.py`
- Test: `application/tests/test_leap_mp.py`

**Interfaces:**
- Consumes: `Pinhole` (Task 2); `PALM_LM`, `apparent_depth`, `Cam`, `Detection` from `orion.webcam`.
- Produces: `View` dataclass `(px: np.ndarray (21, 2) rectified pixels, world: np.ndarray (21, 3) metres hand-centred camera-axis, label: str, score: float)`.
- Produces: `triangulate(left_px, right_px, pinhole, baseline) -> np.ndarray (21, 3)`, left-camera frame, mm, x right, y down, z forward: `d = xL - xR`, `Z = f*B/d`, `X = (xL - cx)*Z/f`, `Y = ((yL + yR)/2 - cy)*Z/f`. The right camera sits `baseline` mm to the right of the left one.
- Produces: `backproject(view, pinhole, hand_mm) -> np.ndarray (21, 3)` same frame: palm depth from `apparent_depth` (build a `Detection` with `image` = px normalised by the pinhole size plus zero z, and a `Cam(pinhole.w, pinhole.h, fov_deg, hand_mm)` whose `fov_deg = 2*degrees(atan(w/2/f))`), palm ray through the mean of `PALM_LM` pixels, other points = palm point + `(world - world[PALM_LM].mean(0))` scaled to mm so wrist→middle-knuckle equals `hand_mm`.
- Produces: `to_leap_axes(points, baseline) -> np.ndarray`: camera `(X, Y, Z)` → Leap `(X - baseline/2, Z, LEAP_Z_SIGN * Y)`. Constants `LEAP_Z_SIGN = 1`, `SWAP_CAMERAS = False`, `LABEL_FLIP = False`, each with `# shortcut: unverified, confirmed against Leap's own tracking in Task 9`.
- Produces: `agreement(left_px, right_px, pinhole, baseline, agree_px) -> bool` per the Global Constraints.

- [ ] **Step 1: Write the failing tests** in `tests/test_leap_mp.py` (helper `scene(z=200.0)` builds 21 random camera-frame points, X ±50, Y ±30, Z `z` ± 5, seed fixed, and `project_pair(points)` gives rectified left/right px with `xR = cx + f*(X - B)/Z`):
  - `test_triangulate_round_trip`: recovered points within 0.5 mm.
  - `test_backproject_recovers_a_flat_hand`: planar hand at Z = 200, `world = (pts - pts[PALM_LM].mean(0))/1000`, `hand_mm = |pts[9]-pts[0]|`; result within 3 mm of `pts`.
  - `test_to_leap_axes`: `[[10, 5, 200]]` with baseline 40 → `[[-10, 200, 5 * LEAP_Z_SIGN]]`.
  - `test_agreement`: `True` for the consistent pair; `False` for a 10 px row offset on the right; `False` for left and right swapped (negative disparity); `False` for a scene at Z = 700.
- [ ] **Step 2:** Run them. Expected: FAIL (names undefined).
- [ ] **Step 3: Implement** the four functions and `View` as specified.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: leap_mp stereo geometry (triangulate, backproject, agreement)`.

---

### Task 4: Crops and `HandFinder`

**Files:**
- Modify: `application/orion/leap_mp.py`
- Test: `application/tests/test_leap_mp.py`

**Interfaces:**
- Consumes: `View`, `Pinhole`, `PALM_LM`.
- Produces: `search_windows(w: int, h: int) -> list[tuple[int, int, int]]` (`(x0, y0, side)`): for 640×240, `[(0, 0, 240), (200, 0, 240), (400, 0, 240)]`.
- Produces: `crop_around(center: tuple[float, float], side: float, w: int, h: int) -> tuple[int, int, int]`: side clamped to 96–`min(w, h)`, window moved to lie fully inside the frame.
- Produces: `HandFinder(backend, pinhole: Pinhole = Pinhole(), min_score: float = 0.5)` with `.find(gray: np.ndarray) -> View | None`. `backend(crop: np.ndarray) -> list[tuple[np.ndarray (21, 2) in 0..1 of the crop, np.ndarray (21, 3) world, str label, float score]]`. `find` crops, calls the backend, keeps the best result with `score >= min_score`, maps landmarks to full-frame pixels `x0 + n*side`, and keeps state: searching (next window in rotation each call) or tracking (window = `crop_around(palm centre, 1.6 * hand bbox side, ...)`); 3 consecutive misses → searching from window 0.
- Produces: `mediapipe_backend() -> Callable` (the real backend): one IMAGE-mode `HandLandmarker` with `num_hands=1`, model from `orion.webcam.ensure_model()`, crop converted to a 256×256 RGB image; imports `mediapipe`/`cv2` inside.

- [ ] **Step 1: Write the failing tests**:
  - `test_search_windows_cover_the_frame` and `test_crop_around_stays_inside`: `crop_around((630, 10), 200, 640, 240)` → `x0 + s <= 640`, `y0 >= 0`, `y0 + s <= 240`; `crop_around((320, 120), 10, ...)` → side 96.
  - `test_finder_searches_then_tracks_then_gives_up` with a scripted backend that records the crop shape and returns a hand (all landmarks at normalised 0.5, score 0.9) only for crops whose first pixel column value marks window 3 (tag the test image with a bright column at x = 400): calls 1-2 return `None`, call 3 returns a `View` whose px mean is `(520, 120)`; call 4's crop is the tracking window (side clamped to 96, centred near 520); three empty backend answers later the next call crops window 0 again.
  - `test_finder_ignores_low_scores`: score 0.3 → `None`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** as specified. No cv2 in `HandFinder`; resizing lives in `mediapipe_backend`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: leap_mp crop search/tracking and MediaPipe backend`.

---

### Task 5: `Fusion`

**Files:**
- Modify: `application/orion/leap_mp.py`
- Test: `application/tests/test_leap_mp.py`

**Interfaces:**
- Consumes: Task 3 geometry, `points_to_hand` (Task 1), `HandTracker._smooth` and `_Track` from `orion.webcam` (private, same package; one `_Track(1)` and a `HandTracker(Cam())` held by the instance).
- Produces: `Fusion(cfg: dict, pinhole: Pinhole = Pinhole(), baseline: float = 40.0)` and `.update(t: float, left: View | None, right: View | None) -> tuple[tuple[Hand, ...], str]`; status is one of `"agree"`, `"left only"`, `"right only"`, `"disagree"`, `"none"`. `cfg` has `agree_px`, `hold`, `hand_mm`. With `SWAP_CAMERAS` the two views are exchanged first; with `LABEL_FLIP` the label is swapped. Agree → `triangulate`; one view → `backproject`; both converted by `to_leap_axes`, palm = mean of `PALM_LM` points, `points_to_hand(..., hid=1)`, then smoothed. Label and score come from the higher-scoring view. Disagree/none → previous hand repeated while `t - seen <= hold`, then `()`.

- [ ] **Step 1: Write the failing tests** (views built from `scene()` and `project_pair`, `world` from the points; cfg `{"agree_px": 4.0, "hold": 0.08, "hand_mm": 95}`):
  - `test_fusion_agree_gives_metric_palm`: status `"agree"`, palm within 2 mm of `to_leap_axes(points[PALM_LM].mean(0))`.
  - `test_fusion_one_camera_still_gives_a_hand`: left `None` → `"right only"` and a hand whose palm depth (leap y) is within 15 % of 200; right `None` → `"left only"`.
  - `test_fusion_disagree_holds_then_drops`: good frames, then a right view shifted 10 px in rows at t+0.05 → `"disagree"` with the previous hand; at t+0.2 → `()`.
  - `test_fusion_recovers`: after the drop an agreeing pair yields a hand with `id == 1`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** `Fusion` as specified.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: leap_mp Fusion (agree / one camera / disagree)`.

---

### Task 6: `LeapSource` hooks

**Files:**
- Modify: `application/orion/sources.py` (`LeapSource`)
- Test: `application/tests/test_core.py`

**Interfaces:**
- Produces: module function `raw_images(e) -> list[tuple[int, int, bytes]]` (width, height, pixels per camera, copied now because the C buffer is only valid during the callback).
- Produces on `LeapSource`: `_tracking(self, e)` (default `self.on_frame(from_leap(e))`), `_images(self, e)` (default: `self._emit_ir(lambda: IRImage(w, h * 2, b"".join(pixels)))` built from `raw_images(e)`), `_on_open(self, conn)` (default no-op, called right after `self._conn = conn`), class attribute `always_images = False` (when true the Images policy is set on connect regardless of `_ir`, and the `ir` setter only stores the flag). The nested `Listener` calls these hooks.

- [ ] **Step 1: Write the failing tests** (`pytest.importorskip("leapc_cffi")`):
  - `test_leap_source_tracking_hook`: with the `NS` event from `test_from_leap_with_fake_structs`, `LeapSource(frames.append, lambda i: None)._tracking(event)` appends one frame.
  - `test_raw_images_copies_both_cameras`: two `ffi.new("LEAP_IMAGE*")` objects with `properties.width = 640`, `height = 240`, `bpp = 1`, `data` pointing at distinct filled `ffi.new("uint8_t[]", 640*240)` buffers, `offset = 0`, wrapped as `NS(c_data=img[0])`; `raw_images(NS(image=[a, b]))` returns two `(640, 240, bytes)` tuples with the right fill bytes.
  - `test_images_hook_stacks_pair_for_the_ui`: with `src.ir = True`, `_images(event)` emits `IRImage(640, 480, ...)`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** by moving the existing listener bodies into the hooks; change `if self._ir:` in `run` to `if self._ir or self.always_images:` and make the `ir` setter's early return include `self.always_images`.
- [ ] **Step 4:** Run `../.venv/bin/python -m pytest tests -q`. Expected: all pass.
- [ ] **Step 5: Commit** `refactor: LeapSource tracking/image/open hooks`.

---

### Task 7: `LeapMediaPipeSource`

**Files:**
- Modify: `application/orion/leap_mp.py`
- Test: `application/tests/test_leap_mp.py`

**Interfaces:**
- Consumes: `LeapSource` hooks (Task 6), `Rectifier`, `HandFinder`, `Fusion`, `mediapipe_backend`, `raw_images`.
- Produces: `LeapMediaPipeSource(on_frame, on_image, ir_fps=30, *, cfg: dict, rectifier_factory=None, finder_factory=None)`; `name = "leap_mp"`, `always_images = True`. `rectifier_factory(conn) -> Rectifier` (default: `Rectifier` with a LeapC projector using `libleapc.LeapRectilinearToPixel(conn.get_connection_ptr(), eLeapPerspectiveType_stereo_left/right, LEAP_VECTOR)`), `finder_factory() -> HandFinder` (default: `HandFinder(mediapipe_backend())`). Internal: `_offer(pair)` stores the newest `(left, right)` uint8 arrays in a one-slot buffer (replacing and counting a stale one), `_process(pair, t)` does rectify → find ×2 → `Fusion.update` → `on_frame(Frame(t, fps, hands, source="leap_mp"))` → preview, `_images(e)` converts `raw_images(e)` to arrays and calls `_offer`, `_on_open(conn)` starts the worker once. `_tracking` forwards to `self.on_reference(from_leap(e))` when that attribute is set (used by Task 9's script), otherwise ignores the event. `status["agreement"]` holds the latest status word.
- The baseline passed to `Fusion` is read once from `libleapc.LeapExtrinsicCameraMatrix` (translation between the two cameras, mm) when the rectifier is built; any failure or a value outside 20–80 mm falls back to 40.
- Produces: `preview(left, right, view_left, view_right) -> IRImage` (stacked 640×480, landmarks as value-255 dots 3 px wide, original arrays untouched).

- [ ] **Step 1: Write the failing tests** (fake factories; a `FakeRectifier` whose `rectify` returns its input; fake finders returning scripted `View`s built like Task 5's):
  - `test_process_emits_a_frame_per_pair`: agreeing views → one `Frame` with one hand, `status["agreement"] == "agree"`; no views → a `Frame` with no hands.
  - `test_process_survives_a_detector_exception`: a finder that raises → an empty `Frame` is emitted, no exception escapes, the next pair works.
  - `test_offer_keeps_only_the_newest_pair`: two `_offer`s → the slot holds the second, the first counted as dropped.
  - `test_missing_dependencies_set_a_readable_error`: `finder_factory` raising `ImportError` → after the worker's setup `status["error"]` mentions the `webcam` extra and no exception escapes.
  - `test_preview_draws_dots_without_touching_inputs`: dot pixels are 255 at the landmark positions, input arrays unchanged, result `IRImage(640, 480, ...)`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.** The worker thread waits on an event, takes the slot, calls `_process` inside `try/except Exception` (log, emit an empty frame), and builds the rectifier lazily on the first pair (calibration is only readable once images flow); a failure there sets `status["error"]`. `fps` is an exponential average of the processing rate. Previews go through `_emit_ir` only when `ir` is on.
- [ ] **Step 4:** Run `../.venv/bin/python -m pytest tests -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: LeapMediaPipeSource`.

---

### Task 8: Wiring (config, engine, UI)

**Files:**
- Modify: `application/orion/default.toml`, `application/orion/config.py:34`, `application/orion/engine.py:23,78-79`, `application/web/src/views/Settings.svelte:33`, `application/web/src/App.svelte:66-70`
- Test: `application/tests/test_core.py`

**Interfaces:**
- Consumes: `LeapMediaPipeSource` (Task 7).
- Produces: `[leap_mp]` table in `default.toml` with `agree_px = 4.0`, `hold = 0.08`, `hand_mm = 95`, `min_score = 0.5` (comment: needs the webcam extra); `general.source` comment lists `leap_mp`; `Config.load` fills `leap_mp` defaults like `webcam`; `Engine.start` maps `"leap_mp"` to the new class with `cfg=self.cfg["leap_mp"]`; Settings select gets `<option value="leap_mp">Leap (MediaPipe)</option>`; the header shows `Leap (MediaPipe) · {fps} fps · {agreement}` for this source.

- [ ] **Step 1: Write the failing test** `test_leap_mp_defaults_load`: a `Config` over an empty user file has `cfg["leap_mp"]["agree_px"] == 4.0` and `["hold"] == 0.08`, and an override of `agree_px` in the user file keeps the other defaults.
- [ ] **Step 2:** Run it. Expected: FAIL (KeyError).
- [ ] **Step 3: Implement** the config, engine and UI changes as listed.
- [ ] **Step 4:** Run `../.venv/bin/python -m pytest tests -q` and, in `application/web`, `npm test && npm run build`. Expected: all pass, build succeeds.
- [ ] **Step 5: Commit** `feat: Leap (MediaPipe) source option in config, engine and UI`.

---

### Task 9: Live bring-up and measurement

**Files:**
- Create: `scripts/leap_mp_compare.py`
- Modify: `application/orion/leap_mp.py` (the three `shortcut:` constants), spec (append a "Results" section)

**Interfaces:**
- Consumes: `LeapMediaPipeSource` with `on_reference`.
- Produces: `python scripts/leap_mp_compare.py [seconds]` (default 30): runs the source against the real device and prints (a) processing fps and the share of pairs per agreement word, (b) per finger, fingertip distance between MediaPipe and Leap (median, 90th percentile) over frames where both have a hand, (c) Pearson correlation of palm x, y, z between the two over the session, (d) share of frames where the two report the same hand side.

- [ ] **Step 1: Write the script** from the interface above (no tests: it is a measuring tool).
- [ ] **Step 2: Run it while moving the open hand** left/right, up/down and toward/away from you for 30 s. Expected: runs without error; if all pairs are `none`, record the hand-size/distance observation in Results and stop here.
- [ ] **Step 3: Set the signs** from (c) and (d): negative x correlation → `SWAP_CAMERAS = True`; negative z correlation → `LEAP_Z_SIGN = -1`; side agreement under 50 % → `LABEL_FLIP = True`. Remove the "unverified" wording from their comments. Re-run and confirm correlations are positive and side agreement is high.
- [ ] **Step 4: Open the app** with `general.source = "leap_mp"`, open the IR view, and confirm the rectified pair shows landmark dots on the hand and the header shows the agreement word.
- [ ] **Step 5: Gesture trial.** Record (UI Record button) the same sequence as before: thumb to middle, ring, pinky, index (ok), peace, fist, relaxed. Replay the recording through `touch_*`, `ok`, `pinch`, `peace`, `fist` and compare with the Leap result (touches fire once each, nothing else misfires).
- [ ] **Step 6: Write the Results section** in the spec: detection rate, fps, agreement shares, fingertip error table, which touches worked, and a verdict (keep / tune / drop).
- [ ] **Step 7: Commit** `feat: leap_mp live calibration, compare script, results`.

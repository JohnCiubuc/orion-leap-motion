# Webcam Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `webcam` frame source (`general.source = "webcam"`) that drives OrionDo first, then the rest of the Leap's gestures.

**Architecture:** One new module `orion/webcam.py`: pure `landmarks_to_hand` (MediaPipe landmarks → `Hand`, Leap axes/mm), a stateful `HandTracker` (ids, finger debounce, One-Euro smoothing, dropout hold, velocity) and `WebcamSource(Source)` (capture + MediaPipe loop + camera auto-detect). Gestures, router and engine are untouched except `Engine.start` choosing the class.

**Tech Stack:** Python 3.14, numpy, MediaPipe Hand Landmarker (tasks API) + OpenCV capture (both from the optional `webcam` extra, imported lazily), pytest, Svelte settings page.

**Spec:** `docs/superpowers/specs/2026-10-28-webcam-source-design.md`

## Global Constraints

- Work on branch `webcam-source`; commit per task; never push or merge unless the user asks.
- Units/axes are `frame.py`'s: mm, +x right, +y up, +z toward the user. MediaPipe image y points down and its world z grows away from the camera; both are converted in `landmarks_to_hand` only.
- Camera frames are flipped horizontally before detection when `mirror = true` (default), so image x = user's right and MediaPipe's Left/Right label is the user's real hand.
- `hand_mm` default 95 (wrist → middle-knuckle), `fov_deg` default 70 (horizontal), nominal camera distance 400 mm maps to leap `z = 0`, palm height offset +200 mm on `y`.
- `mediapipe`/`cv2` are imported lazily inside `WebcamSource.run`; `import orion.webcam` and the whole test suite must work without them.
- Model file `hand_landmarker.task` (mediapipe 1.x does not bundle it) comes from `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task`, cached at `~/.cache/orion-renewal/hand_landmarker.task`, fetched once, **only after the user has been told** (Task 5 step 3).
- Existing suite stays green: `cd application && python -m pytest tests/test_core.py -q` (131 pass at start).
- Constants that need tuning on a real hand are module constants with a `shortcut:` comment (limit + when to upgrade).

## Review Focus

- No camera / camera busy / `mediapipe` not installed: app still starts, status carries an `error` string, Leap and demo untouched.
- Offline or half-downloaded model: no crash, no corrupt cache file (download to `.tmp`, then rename).
- Camera stalls or no hand in view: empty `Frame`s keep flowing at the capture rate so OrionDo's 1.5 s "lost" close and pose `end` events still happen.
- A single hand whose Left/Right label flickers must keep one `Hand.id`, so `Handedness` and OrionDo don't see a new hand.
- Hand at the frame edge, partly out of view, or very close (wrist→knuckle length near 0 px): no division by zero, no NaN/inf in `palm`.

---

### Task 1: Branch, config, extra, settings selector

**Files:**
- Modify: `application/pyproject.toml` (extra), `application/orion/default.toml`, `application/orion/config.py:29-33`, `application/web/src/views/Settings.svelte:32`, `application/web/src/App.svelte:69`
- Test: `application/tests/test_core.py`

**Interfaces:**
- Produces: `cfg["webcam"]` always present with keys `device="auto"`, `width=640`, `height=480`, `fps=30`, `mirror=true`, `hand_mm=95`, `fov_deg=70`; `general.source` accepts `"webcam"`.

- [ ] **Step 1:** `git switch -c webcam-source`.
- [ ] **Step 2: Failing test** `test_config_carries_webcam_defaults`: a `Config` over a temp file containing only `[general]\nsource = "webcam"` has `cfg["webcam"]["device"] == "auto"` and `cfg["webcam"]["mirror"] is True`. Run it; expect KeyError.
- [ ] **Step 3:** Add a documented `[webcam]` table to `default.toml` (and `# leap | webcam | demo` on `source`); add `"webcam"` to the settings-table loop in `Config.load`; add `webcam = ["mediapipe"]` to `[project.optional-dependencies]`.
- [ ] **Step 4:** Settings page: add `<option value="webcam">Webcam</option>` to the tracking-source select (note stays "Applies on restart"). App.svelte status line: show `s.source` as is for webcam (no change needed beyond confirming it renders "webcam · N fps"); if `s.error` is set, show it where the not-connected text is.
- [ ] **Step 5:** Run test + full suite + `cd application/web && npm run build`; all pass.
- [ ] **Step 6: Commit** `feat: webcam source config and settings option`.

### Task 2: Pure landmark conversion

**Files:**
- Create: `application/orion/webcam.py`
- Test: `application/tests/test_webcam.py`

**Interfaces:**
- Produces (all in `orion/webcam.py`):
  - `@dataclass class Cam: width: int = 640; height: int = 480; fov_deg: float = 70; hand_mm: float = 95`
  - `@dataclass class Detection: image: np.ndarray  # (21,3) normalised x,y (0..1, y down), z unused; world: np.ndarray  # (21,3) metres, hand-centred, y down, z away from camera; label: str  # "left"|"right"; score: float`
  - `landmarks_to_hand(det: Detection, cam: Cam, prev_extended: frozenset[str] = frozenset(), hid: int = 0) -> Hand`
- Test helper `project(hand: Hand, cam: Cam, distance=400.0) -> Detection` lives in `tests/test_webcam.py` (inverse of the above for a `make_hand` hand: landmark 0 = middle finger `joints[0]`, landmarks 1-4 / 5-8 / … = `joints[1:5]` of thumb, index, middle, ring, pinky; world = leap→MP axes in metres relative to the mean of landmarks 0,5,9,13,17; pinhole projection at `distance` mm). Use `Cam(hand_mm=64)` in tests, since `make_hand`'s wrist→middle-knuckle is 64 mm.

- [ ] **Step 1: Failing tests**
  - `test_axes`: project a `peace` hand, then the same shifted +30 mm in x and +30 mm in y (leap axes); converted `index.tip[:2]` moves by ≈(+30, +30) (±2 mm).
  - `test_round_trip_poses`: for `peace`, `fist`, `open_palm` (reuse `POSES` shape from `test_core.py`), `landmarks_to_hand(project(h, cam), cam).extended & {"index","middle","ring","pinky"}` equals `h.extended & {…}`; `palm` within 3 mm of the original.
  - `test_depth_from_size`: the same hand projected at 300 mm and 500 mm converts to palm z differing by ≈ +200 mm.
  - `test_degenerate_size_is_finite`: a detection whose landmarks all coincide returns a `Hand` with `np.isfinite(palm).all()`.
  - `test_extended_hysteresis`: a finger whose straightness sits between the on and off thresholds keeps whatever `prev_extended` says.
- [ ] **Step 2:** Run; expect ImportError/FAIL.
- [ ] **Step 3: Implement** `landmarks_to_hand`. Approach: palm image point = mean of landmarks 0,5,9,13,17; `f = (width/2)/tan(fov/2)`; distance `Z = f·hand_mm / len_px` with `len_px = max(|lm0→lm9| in pixels, 1)`; `palm = (X, Y + 200, Z - 400)`; every joint = palm + (world − world palm centre)·1000 with axes `(x, −y, z)`; joints per finger = `[lm0] + lm[4k+1 … 4k+4]` (thumb: k=0 → landmarks 1-4); finger straightness = chord(first→tip) / sum of segment lengths, on at ≥ 0.80, off below 0.65 (hysteresis via `prev_extended`; `shortcut: thresholds from make_hand geometry, retune on a real hand`). `side = det.label`, `confidence = det.score`, `pinch=0`, `grab=0`, `normal=(0,-1,0)`, `direction=(0,0,-1)`, `velocity=0`, `stable=palm.copy()` (Task 6 fills these).
- [ ] **Step 4:** Run tests; pass.
- [ ] **Step 5: Commit** `feat: webcam landmark conversion`.

### Task 3: HandTracker (stability layer)

**Files:**
- Modify: `application/orion/webcam.py`
- Test: `application/tests/test_webcam.py`

**Interfaces:**
- Consumes: `Detection`, `Cam`, `landmarks_to_hand` (Task 2).
- Produces: `class HandTracker: def __init__(self, cam: Cam); def update(self, t: float, dets: list[Detection]) -> tuple[Hand, ...]` — one call per captured frame (empty `dets` allowed).
- Constants: `DEBOUNCE = 2` (frames a finger must hold a new state), `HOLD = 0.08` (s a missed hand is repeated), `MIN_CUTOFF = 1.5`, `BETA = 0.02`, `D_CUTOFF = 1.0` (One-Euro).

- [ ] **Step 1: Failing tests** (frames at 30 fps, `t = i/30`)
  - `test_ids_survive_label_flicker`: one hand tracked for 30 frames with the label alternating `left`/`right` every frame keeps a single `Hand.id`.
  - `test_finger_debounce`: a single frame where `ring` flips to extended does not change `extended`; two consecutive frames do.
  - `test_one_frame_dropout_repeats_hand`: frame with `dets=[]` after a detection returns the previous hand; after 0.2 s of misses returns `()`.
  - `test_jitter_is_quiet`: hand held still with ±1 mm gaussian noise (seeded) on world landmarks: `|index.tip − palm|` std below 1 mm over 60 frames, and `|velocity|` stays under 20 mm/s (below the `tap_still` default of 60).
  - `test_velocity_tracks_motion`: a hand moving 100 mm/s in x reports `velocity[0]` within 15 % after 30 frames.
- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3: Implement.** Ids: match each detection to the nearest previous track by image distance of the palm (< 0.25 normalised) else issue a new id; `side` is the raw label (the engine's `Handedness` stabilises it). One-Euro filter (small class, ndarray-shaped) over `[palm, joints]` per track; `velocity` = filtered finite difference of the smoothed palm; `stable` = smoothed palm. `extended` debounced per finger using `DEBOUNCE`; pass the debounced set as `prev_extended`. Dropout: keep each track's last `Hand` and `last_seen`, re-emit while `t − last_seen ≤ HOLD`, then drop the track.
- [ ] **Step 4:** Run tests; pass.
- [ ] **Step 5: Commit** `feat: webcam hand tracker (ids, debounce, smoothing, dropout hold)`.

### Task 4: OrionDo end-to-end on webcam frames (milestone 1 gate)

**Files:**
- Test: `application/tests/test_webcam.py` (plus a small fix in `webcam.py` if a test exposes one)

**Interfaces:**
- Consumes: `HandTracker.update`, `project`, `REGISTRY["oriondo"]`, `menu_items` helper from `test_core.py` (copy its few lines, don't import across test modules).

- [ ] **Step 1: Failing tests** — a helper `webcam_frames(poses_and_motion, fps=30)` builds `Frame(t, hands=tracker.update(t, [project(h, cam)]), source="webcam")`:
  - `test_oriondo_opens_on_peace_via_webcam`: holding `peace` for 0.6 s produces `oriondo begin`.
  - `test_oriondo_hovers_and_fires`: after open, moving the index tip +20 mm toward the top slice hovers slice 0 (update value `hover == 0`); continuing to +40 mm yields `fire` with `index == 0`.
  - `test_oriondo_no_tap_close_from_jitter`: ±1 mm noise for 2 s while open never produces `end` with `"tap"`.
  - `test_oriondo_survives_one_frame_dropout`: a single empty-detection frame mid-pull does not re-anchor (the pull still fires on the original origin).
  - `test_oriondo_closes_when_hand_leaves`: empty frames for 1.6 s after open produce `end` `"lost"`.
- [ ] **Step 2:** Run. For any failure, fix the tracker/conversion (not the gesture), re-run. If the tap test cannot pass by smoothing alone, document raising `tap_trigger` for this source in the spec's "Known limits" instead of changing `OrionDo`.
- [ ] **Step 3:** Full suite green.
- [ ] **Step 4: Commit** `test: OrionDo runs on webcam frames`.

### Task 5: WebcamSource, camera auto-detect, model fetch, wiring

**Files:**
- Modify: `application/orion/webcam.py`, `application/orion/engine.py:22,76-78`, `application/web/src/views/Settings.svelte`
- Test: `application/tests/test_webcam.py`

**Interfaces:**
- Consumes: `Source` (`sources.py`), `HandTracker`, `Cam`, `Detection`, `cfg["webcam"]`.
- Produces:
  - `find_cameras() -> list[dict]` → `[{"path": "/dev/video2", "name": "C922 Pro Stream Webcam"}]`: entries of `/sys/class/video4linux/video*` whose `index` file reads `0` (capture nodes; metadata nodes report 1), sorted by number.
  - `class WebcamSource(Source)`, `name = "webcam"`, `__init__(on_frame, on_image, ir_fps, *, cfg: dict, capture_factory=None, detector_factory=None)` (factories exist only so tests inject fakes); `status` gains `cameras` (list above) and `error` (str, empty when fine).
  - `run()`: open `cfg["device"]` (`"auto"` → first camera from `find_cameras()` that opens and returns a frame, else status `error = "No webcam found"`); on every captured frame call `on_frame(Frame(t=time.monotonic(), fps=measured, hands=tracker.update(t, dets), source="webcam"))` — **including empty frames**; if reads fail, emit empty frames at ≥ 10 Hz and set `connected=False`.

- [ ] **Step 1: Failing tests** with fakes (no cv2/mediapipe): `find_cameras` against a tmp sysfs dir (parameter `root=Path`), `test_source_emits_empty_frames_without_hands`, `test_source_emits_hands`, `test_source_reports_missing_camera` (`error` set, `run()` returns, no exception), `test_source_reports_missing_mediapipe` (import failure → `error` mentions `pip install -e ".[webcam]"`).
- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3: Tell the user, then fetch.** Before any download: print what and where (URL and cache path from Global Constraints, ~7 MB) and ask for a go-ahead. `ensure_model() -> Path`: returns the cached path, otherwise downloads to `hand_landmarker.task.tmp` and renames; failure → `RuntimeError` surfaced as `status["error"]`.
- [ ] **Step 4: Implement** `WebcamSource.run` (OpenCV `VideoCapture`, set width/height/fps from cfg, `cv2.flip(frame, 1)` when `mirror`, MediaPipe `HandLandmarker` in VIDEO mode with `num_hands=2`, results → `Detection`s using `hand_landmarks` + `hand_world_landmarks` + first `handedness` category). `Engine.start`: map `"webcam"` to `WebcamSource` and pass `cfg=self.cfg["webcam"]`; `ReplaySource`/`DemoSource` paths unchanged.
- [ ] **Step 5:** Settings page: when `g.source === "webcam"`, show a "Camera" select bound to `orion.draft.webcam.device` with options `auto` ("Auto-detect") plus `s.cameras` (`path`, `name`); show `s.error` as a warning line under it.
- [ ] **Step 6:** Install the extra only with the user's go-ahead (`.venv/bin/pip install -e "application[webcam]"`), then a smoke run: `orion-renewal --headless` with `general.source = "webcam"` in a temp `XDG_CONFIG_HOME` prints status with `connected` true and a camera name.
- [ ] **Step 7:** Suite + `npm run build` green; **Commit** `feat: webcam source with camera auto-detect`.
- [ ] **Step 8:** Hand the user the real-hand checklist: peace opens the pie; fingertip steers; pull fires; pose does not flicker; tap does not close by accident. Record tuning findings (`DEBOUNCE`, `BETA`, straightness thresholds, `tap_trigger`) back into constants/config.

### Task 6: Milestone 2: remaining Hand fields and preview

**Files:**
- Modify: `application/orion/webcam.py`
- Test: `application/tests/test_webcam.py`

**Interfaces:**
- Consumes: Task 2 `landmarks_to_hand`, Task 5 `Source._emit_ir`.

- [ ] **Step 1: Failing tests** over the `POSES` round trip: `pinch` > 0.85 for `ok` and < 0.3 for `open_palm`; `grab` > 0.9 for `fist`, < 0.2 for `open_palm`; `normal` points out of the palm (`peace`/`open_palm` face the camera: `normal[2]` has the sign `make_hand` uses); `direction` points wrist → fingers; every pose in `POSES` is detected by its `REGISTRY` gesture from converted frames (reuse `run`/`hold` shapes at 30 fps).
- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3:** Implement in `landmarks_to_hand`: `pinch` from thumb-tip↔index-tip distance (0 at ≥ 60 mm, 1 at ≤ 10 mm, linear), `grab` = mean curl fraction of the four fingers, `normal`/`direction` from wrist, index-MCP and pinky-MCP world points (sign flipped for `left`), `stable` smoothed palm (tracker already does this).
- [ ] **Step 4:** In `WebcamSource.run`, call `self._emit_ir(lambda: IRImage(w, h, gray_bytes))` with the flipped frame converted to 8-bit grayscale and downscaled to 320 px wide.
- [ ] **Step 5:** Suite green; **Commit** `feat: webcam source fills pinch/grab/normal and previews`.

### Task 7: Notes

**Files:**
- Modify: `CLAUDE.md` (project notes), `README.md` (one short section)

- [ ] **Step 1:** README: how to install the extra, set `general.source = "webcam"`, camera selection, the known limits from the spec.
- [ ] **Step 2:** CLAUDE.md: add the webcam source to "Where things live" and the real-hand tuning item to Pending; update the "Last updated" line.
- [ ] **Step 3: Commit** `docs: webcam source notes`.

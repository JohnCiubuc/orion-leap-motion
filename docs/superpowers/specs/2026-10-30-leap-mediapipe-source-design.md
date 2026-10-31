# Leap (MediaPipe) source: design

Date 2026-10-30. Branch `leap-mediapipe`. Status: draft for review. An experiment: merge only if it earns it.

## Why

The Leap's own tracker loses fingers when they curl and overlap the palm, so thumb-to-fingertip gestures (`touch_middle`, `touch_ring`, `touch_pinky`) fail. Question: does MediaPipe Hands, run on the Leap's two infrared cameras, track those poses better? Two views of one hand let each stream check the other.

## Scope

One hand. New source option "Leap (MediaPipe)" (`general.source = "leap_mp"`) next to Leap, webcam and demo. Everything downstream of the source (gestures, router, OrionDo) is unchanged and sees ordinary `Frame`/`Hand` objects.

Out of scope: two hands, fusing with Leap's own tracking, GPU, fine-tuning a model, any webcam work (paused; the webcam module is reused as code only).

## What the device gave us (probed live, 2026-10-30)

- Each camera image is 640×240, 8-bit, ~130° wide, effective focal length ~143 px. A hand 20 cm away is ~60 px wide.
- `LeapRectilinearToPixel(conn, camera, ray)` works per camera (`conn = Connection.get_connection_ptr()`, no `[0]`). The cameras differ by ~3 px vertically, so they are not rectified as shipped.
- MediaPipe's palm detector resizes its whole input to 192×192, which would shrink a 60 px hand to ~18 px. Detection therefore needs crops (below).

## Data flow

```
LeapC image event ──► latest-pair slot ──► worker thread
   (copy both 640×240 images,                │
    never block the callback)                ▼
                              rectify L, R to one shared pinhole (cv2.remap, tables built once)
                                             │
                          per camera: crop → MediaPipe → 21 landmarks in rectified px
                                             │
                                 cross-check (epipolar row, disparity, depth)
                      agree ─► triangulate 21 points to mm, Leap axes
                      one camera ─► monocular estimate from that camera
                      disagree ─► hold HOLD s, then report no hand
                                             │
                      points_to_hand ► One-Euro smoothing, finger debounce ► Frame ► engine
```

The worker always takes the newest pair and drops older ones, so latency does not build up when MediaPipe is slower than the camera.

## Components

New module `orion/leap_mp.py`; the pure parts import neither OpenCV nor MediaPipe at module level (same rule as `webcam.py`).

1. **`Rectifier`**: built from a projector `f(camera, ray) -> (x, y)` (LeapC in production, a fake in tests). Output model: pinhole, 640×240, f = 143 px, principal point at the image centre, identical for both cameras. For every output pixel it asks the projector where that ray lands in the raw image, stores the maps once, then `rectify(camera, gray)` is one `cv2.remap`. The baseline is read from `LeapExtrinsicCameraMatrix`; if unavailable, 40 mm.
2. **Crops** (`search_windows`, `crop_around`): with no hand, each frame tries one of three 240×240 windows (x = 0, 200, 400) in rotation. With a hand, the window is a square of 1.6× the hand's bounding-box side (about 2.5× the palm), clamped to 96–240 px, centred on its last position, and resized to 256 for MediaPipe. Landmarks map back to full-frame pixels. MediaPipe runs in IMAGE mode on the crop; each camera has its own tracking state.
3. **`triangulate(left, right, f, cx, cy, baseline)`**: for rectified landmarks, disparity `d = xL − xR`, depth `Z = f·B/d`; returns (21, 3) mm. Camera axes are converted to Leap axes (origin between the cameras, y away from the device, z toward the user). The sign of the z axis is fixed empirically against Leap's own tracking in the first implementation task and then locked by a test.
4. **`agreement(left, right)`**: `agree` when the median row difference is below `agree_px` (default 4), at least 18 of 21 disparities are positive, and the hand's depth lies in 60–600 mm. Otherwise `disagree`. A camera with no detection gives `left only` / `right only`.
5. **`fuse`**: `agree` → triangulated points; `left only` / `right only` → that camera's landmarks through the existing monocular path (`landmarks_to_hand` with `Cam` built from the Leap's f and image size); `disagree` → no new hand, the last good hand is repeated for `HOLD` (0.08 s) and then dropped, so an open menu closes instead of firing on a wrong pose.
6. **`points_to_hand`** (small split in `webcam.py`): the part of `landmarks_to_hand` that turns 21 points in mm into a `Hand` (finger straightness, `extended`, `pinch`, `grab`, normal, direction). `landmarks_to_hand` calls it, so the webcam source behaves as before; the webcam tests must still pass unchanged. Smoothing and finger debounce reuse the existing `OneEuro`/tracker pieces.
7. **`LeapMediaPipeSource(LeapSource)`**: `LeapSource` gets two small hooks (`_tracking(e)`, `_images(e)`) so the connection, retry and restart logic are reused. The new source ignores Leap tracking events, keeps the Images policy on regardless of the UI's IR toggle, and copies each image pair into the slot. The UI's IR toggle only decides whether previews are sent.
8. **Preview**: when IR is on, the worker sends the rectified pair (stacked, as `IRView` expects) with the landmarks drawn as bright dots (`IRView` is a single-channel texture, so no colour). `status["agreement"]` (`agree`, `left only`, `right only`, `disagree`, `none`) is shown as text in the header status line.

## Config and UI

- `[leap_mp]` in `default.toml`: `agree_px = 4.0`, `hold = 0.08`, `hand_mm = 95`, `min_score = 0.5`. Constants that are guesses carry `# shortcut:` comments.
- Settings: a "Leap (MediaPipe)" entry in the source select, and the agreement word in the header status line.
- Needs the same extra as the webcam source (`mediapipe`, `opencv`; both are already in `.venv`; the model file is cached).

## Evaluation

1. Detection rate and processing fps per camera, shown in the status.
2. `scripts/leap_mp_compare.py` (a measuring tool, not part of the app): runs the pipeline and Leap's own tracking on the same live session and prints, per finger, detection rate and the distance between the two fingertip estimates. Leap is the reference for open-hand poses only; it is expected to be wrong on curled fingers, which is the point.
3. The real test: the thumb-touch gestures live, with the existing thresholds.

An honest "no" is a valid result: if hands under ~25 cm are not found on most frames, the experiment ends there and we write that down.

## Testing

Unit (TDD, in `tests/test_leap_mp.py`):
- `Rectifier` with a fake pinhole-plus-distortion projector: rectifying a synthetic grid round-trips within 0.5 px.
- `triangulate` on points projected with known intrinsics and baseline: recovers positions within 0.5 mm.
- `agreement`: agree, row mismatch, negative disparity, depth out of range, one camera missing.
- `fuse` over a scripted sequence: agree → disagree → hold → drop → recover.
- Crop windows: rotation, clamping at the edges, round-trip of landmark coordinates.
- Source with a fake detector and fake image events: a frame is emitted per pair, stale pairs are dropped, the Images policy stays on.
- `points_to_hand` equals the previous `landmarks_to_hand` output on the existing webcam test hands.

Manual: real MediaPipe on real IR, LeapC calibration calls, the UI chip and the preview.

## Known limits

- 60–100 px hands are near what MediaPipe handles; far hands may not be found.
- MediaPipe was not trained on infrared images from below.
- Two MediaPipe passes per frame may cap the frame rate; measure before optimising.
- Depth from a 40 mm baseline is ~1.4 % per pixel of disparity error at 20 cm.

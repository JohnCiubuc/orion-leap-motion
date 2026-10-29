# Webcam source: design

Date: 2026-10-28. Status: design approved in chat, spec awaiting review.

## Goal
A new frame source, `WebcamSource`, that replaces the Leap as the live source (`general.source = "webcam"`).
**Primary target: OrionDo works with it.** Everything else the Leap supports is secondary and comes after.

## Background
Sources emit `Frame`/`Hand` dataclasses in millimetres (`frame.py`; +x right, +y up, +z toward the user).
`Engine.start` picks the class from `general.source`. Gestures and the engine do not change.
Webcams present: two C922 nodes (`/dev/video2`, `/dev/video3`). `mediapipe` is not installed; a py3-none wheel exists for Python 3.14.

## Approach
MediaPipe Hand Landmarker (up to 2 hands) on OpenCV capture, in an optional extra `webcam = ["mediapipe"]`.
Heavy imports are lazy (as `leap` is in `LeapSource`). New file `orion/webcam.py`:
- `WebcamSource(Source)`: capture + detect loop in its own thread, emits `Frame(source="webcam")`.
- `landmarks_to_hand(...)`: pure conversion, no camera or MediaPipe import, unit-testable.

## What OrionDo consumes (drives milestone 1)
1. `Hand.extended` stable enough that `peace` (index+middle out, ring+pinky curled; thumb ignored) holds 0.3 s.
2. `index.tip[:2]` in real mm, x right, y up. Deadzone 8 mm, pull 35 mm, slice angle from this vector.
3. `index.tip - palm` and `|velocity|` quiet: `FingerMotion` taps at 5 mm of fingertip motion in 0.12 s with palm < 60 mm/s.
4. Continuous frames: a gap > 0.15 s re-anchors the marker, > 1.5 s closes the menu.

## Milestone 1: OrionDo end to end
Fields filled properly: `extended`, `joints` (5 per finger: wrist prepended as the base), `palm`, `velocity`, `confidence`, `side`, `id`. Other fields plausible only.
- **Mm and axes.** Fingertip mm from MediaPipe world landmarks (real hand shape). Palm placement from the image, scaled by apparent hand size (wrist to middle-knuckle ≈ `hand_mm`, default 95) and a nominal `fov_deg`. The scale is low-pass filtered so moving toward the camera does not look like marker drift. Mirroring handled in one place; image y is flipped to y-up.
- **Extended fingers.** From joint angles with hysteresis (different on/off thresholds) and a 2-3 frame debounce.
- **Jitter.** One-Euro filter on the index tip and palm; `velocity` from the smoothed palm.
- **Dropouts.** A 1-2 frame detection miss repeats the last hand (no empty frame, so no re-anchor mid-pull). Real losses pass through so the 1.5 s close works.
- **Tap sensitivity.** If still too sensitive on a webcam, raise `tap_trigger` for this source (config value, not code).
- **Tests.**
  - Axis test: fingertip moved up/right gives `tip[:2]` with the right signs.
  - Round-trip: `make_hand` → fake landmarks → `landmarks_to_hand` agrees on poses and positions.
  - OrionDo driven with converted frames: opens on peace, hovers the right slice, fires at the pull distance, no tap-close on jitter, no re-anchor over a 1-frame dropout.
  - Source loop with a fake capture and a fake detector.
- Then the user's real-hand test.

## Milestone 2 (secondary)
- Fill `pinch`, `grab`, `normal`, `direction`, `stable` so the other poses, swipe, zoom and joystick work.
- Webcam preview as the `IRImage` panel (downscaled grayscale via `_emit_ir`); status shows the camera name.
- `[webcam]` config beyond the basics: `device` (default: first node that returns frames), `width`/`height`/`fps`, `mirror`.

## Out of scope
Calibration UI, running Leap and webcam together, Leap policy flags and service restart (`restart()` keeps the base-class error).

## Known limits
~30 fps vs the Leap's 110; depth is estimated, so zoom and swipe distances are approximate; OrionDo's 8 mm deadzone is noisier on a webcam (hence the smoothing).

## Open items for the plan
- Does mediapipe 1.x bundle `hand_landmarker.task` (~7 MB)? If not, download once to `~/.cache/orion-renewal/` and tell the user before it happens.
- Which of the two `/dev/video` nodes delivers frames (the second is usually metadata).
- Where `general.source` is validated or listed (config, web UI), so "webcam" is accepted.

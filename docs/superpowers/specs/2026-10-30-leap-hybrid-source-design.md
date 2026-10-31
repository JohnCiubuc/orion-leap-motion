# Leap hybrid source: design

Date 2026-10-30. Branch `leap-mediapipe`. Status: draft for review. Builds on `2026-10-30-leap-mediapipe-source-design.md`.

## Why

Two trackers, two strengths, measured on the same hand in one 33-phase session (`scripts/leap_mp_compare.py`):

| | Leap | MediaPipe (left camera, GPU) |
|---|---|---|
| Position, motion, hand identity | exact, 110 fps | palm 47 mm off, height 1.37×, depth range ~2× |
| Palm orientation | [−0.1, −1, −0.1] palm down (right) | tilted 15–25° |
| Fingers across the image (x, z) | loses curled fingers over the palm | palm-relative error 8 mm (x), 3 mm (z) |
| Fingers in depth (y) | n/a | corr +0.68, median error 47 mm, slope 2.15 |
| Index/middle/ring bent at the camera | misses middle, ring | sees all three |
| Pinky and thumb folded in a flat hand | sees them | misses them |
| Thumb across the palm, tip-to-tip touches | misses many | fires cleanly (palm down) |
| End-on poses (palm-up fist, thumb down, index up) | tracks | finds no hand |

So: the Leap is the body, MediaPipe is the fingers, and the Leap's fingers are the fallback when MediaPipe has none.

## Decisions (from the discussion)

- A **new source `leap_hybrid`** next to `leap`, `leap_mp` and `webcam`.
- The Leap supplies general motion and absolute location; **most gestures run on MediaPipe's fingers**.
- **OrionDo keeps the Leap's interaction exactly as it is now**: it sees the Leap's own hand (trigger pose, index fingertip, tap), never the merged one.
- **Palm-up finger touches are ignored** (the palm hides the fingers from the camera). Palm-up open hand and palm-up fist must still be recognised; the fist comes from the Leap fallback, since MediaPipe finds no hand there.
- One hand. A second Leap hand passes through unchanged.

Out of scope: two-hand merging, tuning the depth scale beyond measuring it, two-camera hybrid.

## Data flow

```
Leap tracking event ──► Leap Frame L (from_leap)                       ┐
                                                                       ├─► merge(L.hand, MP hand) ► Frame(hands=merged, leap=L) ► engine
image events ─► LeapMediaPipeSource pipeline ─► latest MP hand + time ─┘
```

The Leap clocks the output: one merged frame per Leap tracking event. The MediaPipe worker (unchanged from `leap_mp`) keeps publishing its newest hand into a one-slot store instead of emitting frames.

## Components

1. **`Frame.leap: Frame | None = None`** (`frame.py`): the unmodified Leap frame, set only by the hybrid. **`Engine`** passes `frame.leap or frame` to the OrionDo gesture and the unmodified `frame` to every other gesture, the router, the recorder and the UI.
2. **`merge(leap: Hand, mp: Hand | None, age: float, cfg) -> Hand`** (new, pure, in `orion/leap_hybrid.py`). Returns `leap` untouched when `mp` is `None`, older than `max_age` (0.12 s), or on the other side. Otherwise a copy of `leap` with:
   - **Kept from the Leap:** `id`, `side`, `confidence`, `palm`, `stable`, `velocity`, `normal`, `direction`.
   - **Finger joints:** MediaPipe's palm-relative joints, rotated from MediaPipe's palm frame into the Leap's (orthonormal bases from each hand's `direction` and `normal`; translation-only if either frame is degenerate), then placed at the Leap's palm. This removes MediaPipe's tilt and absolute offset and keeps its in-image finger geometry.
   - **`extended`:** MediaPipe's flags for index to pinky. The thumb is extended when its tip's offset from the palm toward the thumb side, measured across the image along the line from the pinky knuckle to the index knuckle, is at least `thumb_out` mm (45; hysteresis 40 to 48). Measured on the session: 52–83 mm with the thumb out (open, OK sign, relaxed, flat), 6–34 mm when folded (touches, fist, peace, pointing). MediaPipe's thumb straightness is 0.84–1.0 in every pose, so it cannot decide.
   - **`pinch` and `grab`:** MediaPipe's (`planar_pinch`, grab gate as in `leap_mp`).
3. **`LeapHybridSource(LeapMediaPipeSource)`** (`orion/leap_hybrid.py`): `_emit` stores the newest MediaPipe hand and its time; `_tracking(e)` builds `L = from_leap(e)`, merges the first hand (or the hand whose side matches MediaPipe's) and emits `Frame(t=L.t, fps=L.fps, hands=…, source="leap_hybrid", leap=L)`. Setup errors, a missing GPU or a stale MediaPipe never stop frames: the Leap hand passes through and `status["error"]` says why. `status["fingers"]` is `"mediapipe"` or `"leap"` for the UI.
4. **Palm-up guard** (`gestures/fingers.py`): `thumb_touch` returns `None` while the palm faces up (`normal[1] > 0.3`). Applies to every source.
5. **Config and UI:** `general.source = "leap_hybrid"`; `[leap_hybrid]` holds `max_age = 0.12`, `thumb_out = 45`; the MediaPipe settings stay in `[leap_mp]` (cameras, delegate, hand_mm, …). Settings gets a "Leap + MediaPipe" option; the sidebar shows `Leap + MediaPipe · fps · mediapipe|leap`.
6. **`scripts/leap_mp_compare.py`** learns `--hybrid`: it runs the hybrid source and compares `frame.hands` against `frame.leap.hands`, so the same 33 phases measure the merged result.

## Acceptance (measured with the script in `--hybrid` mode)

1. The touch phases (palm down) fire as they do on `leap_mp`: each once, nothing extra; palm-up touches fire nothing.
2. The flat finger-down phases: the bent digit reads not-extended in at least 90 % of frames for index, middle, ring, and the thumb-across-palm phase reads thumb not-extended; none of the other digits does.
3. Palm-up fist, thumb down and index-up (MediaPipe finds nothing): the merged hand equals the Leap's, and `fist` fires in palm-up fist.
4. Palm normal of the merged hand equals the Leap's in every phase.
5. OrionDo opens with the trigger pose and fires an item exactly as on the plain Leap source (`frame.leap` reaches it; a test pins this).

## Testing

Unit (TDD, `tests/test_leap_hybrid.py`): `merge` with a synthetic Leap hand and a MediaPipe hand that is rotated 20°, offset by 50 mm and has noisy depth (palm, normal, direction, velocity, side, id come out as the Leap's; joints come out in the Leap's frame; flags and pinch as MediaPipe's); stale, missing and wrong-side MediaPipe return the Leap hand unchanged; the thumb rule with hysteresis on the recorded lateral offsets; a source test with a fake Leap event and a fake MediaPipe store (frame per Leap event, `leap` set, fallback when MediaPipe raises); an engine test that OrionDo receives `frame.leap`; `thumb_touch` is `None` palm-up. Manual: the 33-phase session.

## Known limits

- The finger depth scale (MediaPipe over-reads by ~2×) is measured, not corrected, in this round.
- Everything is tuned on one hand.

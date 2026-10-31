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

## Results (first live `--hybrid` session, 2026-10-30, one hand)

| # | Criterion | Result |
|---|---|---|
| 1 | Palm-down touches fire once, nothing extra; palm-up touches silent | **Met.** `touch_middle`, `touch_ring`, `touch_pinky` each fire once; all three palm-up touch phases fire nothing. The right-edge pinky and the four taps did not fire, but the Leap's own distances agree with the hybrid's there (thumb nearer the index than the pinky; mid-tap thumb-to-middle 55 mm on both), so those poses were not performed as touches that time. |
| 2 | Bent digit not-extended in at least 90 % of frames (index, middle, ring); thumb across the palm | **Met after one fix.** Middle 0 % and ring 0 % extended, thumb 6 % (Leap 4 %) straight away. The index read 100 % extended: the bend is shallow (0.87 straight against an open-finger minimum of 0.912) and sat just above the 0.85 cut-off, so the cut-offs are now 0.90 on / 0.88 off. Replayed: index 0 %, the others 100 %. **Pinky: not met, not required.** MediaPipe cannot see it bend (0.93 straight, same as open); the Leap can (28 % extended). |
| 3 | Palm-up fist, thumb down and index-up fall back to the Leap | **Partly checkable.** Thumb down and index-up behave as the Leap (index-up: fingers from the Leap in 77 % of frames). In this run the Leap itself lost the hand in the palm-up fist and palm-up pinky phases, so the fallback was not exercised there. |
| 4 | Palm normal equals the Leap's | **Met.** Difference 0.000 in every phase. |
| 5 | OrionDo behaves as on the plain Leap | Wired (`frame.leap`, pinned by a test); **the by-hand check is the user's to confirm.** |

Found and fixed during the session:
- `thumb_down` (a fist) fired `touch_middle`: MediaPipe's grab hovers at 0.66-0.70, right on the 0.7 closed-hand guard, while the Leap reads 1.0. The merged hand now takes the larger of the two grabs (a deviation from "grab from MediaPipe" above).
- A merged hand whose MediaPipe palm normal points opposite the Leap's now falls back to the Leap's fingers (a flipped normal would mirror the fingers).

Open:
- **Pinky and thumb-across-palm per finger:** the Leap sees the pinky bend that MediaPipe misses. A per-finger "either tracker says bent" rule for the pinky would fix `flat_pinky_down`; not done, to be decided.
- **Pinch on a fist from the Leap fallback:** when MediaPipe has no hand, a fist falls back to the Leap's pinch strength, which reads about 0.9 on a fist (`thumb_down` fired `pinch` 3 times). Applying the same closed-hand gate to fallback hands would stop it; not done, to be decided.
- The 15-25° tilt correction, `thumb_out` and `max_age` are only checked on this session.

# LeapC / Gemini SDK — What the API actually exposes

Compiled by reading the `leapc-python-bindings` source directly
(`leapc-python-api/src/leap/{datatypes,enums,events,functions,connection,device,recording}.py`)
and verified live against an original Leap Motion Controller. All of this is
accessible from Python (or C, via the same underlying `LeapC.h`) once the
service in this repo's `install.sh` is running.

## 1. Skeletal hand tracking (core feature, `TrackingEvent`)

Per frame, for up to 2 hands (`event.hands`):

- **Per hand**: `id`, `type` (Left/Right), `confidence`, `visible_time`,
  `pinch_distance`, `pinch_strength`, `grab_angle`, `grab_strength` — the
  service computes pinch/grab gesture scores for you, no custom logic needed.
- **Palm** (`hand.palm`): `position`, `stabilized_position` (jitter-reduced),
  `velocity`, `normal`, `direction`, `width`, `orientation` (quaternion).
- **5 fingers** (`hand.digits`: thumb/index/middle/ring/pinky), each with 4
  bones (metacarpal/proximal/intermediate/distal), each bone exposing
  `prev_joint`/`next_joint` positions, `width`, `rotation` (quaternion).
  `digit.is_extended` gives an instant flag for "is this finger extended".
- **Arm** (`hand.arm`): forearm bone position/orientation too.
- **Frame metadata**: `frame_id`, `timestamp` (µs), `framerate`, `tracking_frame_id`.

This alone is enough for mouse/gesture control, custom gesture recognition,
per-finger bend detection, and 3D hand visualization — no extra CV/ML needed.

**Verified live** (2026-07-13): open hand → all fingers extended,
`pinch=0.00 grab=0.00`; closed fist → all fingers retracted,
`pinch≈0.6–1.0 grab≈0.8–1.0`. Two hands tracked simultaneously,
confidence in the 0.6–0.85 range, ~114 FPS.

## 2. Raw camera images (`ImageEvent`, no LeapUVC needed)

Enabling the images policy flag gets you `ImageEvent.image`: the **raw stereo
IR camera frame pair**, streamed straight through the service. This means you
can do your own CV/ML work (custom hand models, depth estimation, ArUco
marker tracking, etc.) without touching LeapUVC at all — LeapUVC is only
needed if you want to bypass the tracking service entirely.

## 3. Multi-device support

- `Connection(multi_device_aware=True)` + `connection.get_devices()` lets you
  enumerate and subscribe to multiple cameras at once.
- Per-device `device.open()` context, `set_primary_device()`, and every event
  carries `metadata.device_id`.
- `Device.get_info()` gives serial, PID, FOV (horizontal/vertical, radians),
  max sensing range (µm), and camera count.

## 4. Tracking modes / policies

- `set_tracking_mode()` / `get_tracking_mode()`: Desktop / HMD / ScreenTop —
  tunes the tracking algorithm for how the camera is mounted. This device
  defaults to Desktop mode automatically (confirmed in the service log:
  `TrackingRunner()#160: default mode Desktop`).
- `set_policy_flags()` toggles image streaming, background frame delivery, etc.

## 5. Frame interpolation (`interpolate_frame`, for low-latency VR rendering)

`LeapInterpolateFrame` interpolates hand position to an arbitrary timestamp —
useful when your render loop runs at a different rate than the tracking
frame rate (e.g. 90Hz VR vs. tracking rate), avoiding jitter/lag in VR
overlays or real-time interaction demos.

## 6. Recording / playback (`Recording`, `Recorder`)

Tracking sessions can be written to and replayed from `.lmt` files
(`Recorder` is a `Listener`, so it just streams live data straight to a file).
Useful for iterating on an algorithm offline, or collecting a gesture dataset,
without the physical device attached.

## 7. Hardware-dependent events (unverified on this device)

- `IMUEvent` (accelerometer/gyroscope/temperature), `HeadPoseEvent`,
  `EyesEvent` all exist in the API but are presumed to require hardware only
  present on **Leap Motion Controller 2** (IMU, etc.) — not yet confirmed
  whether they ever fire on the original controller. If you test this on
  real hardware, please open an issue with your findings.
- `LogEvent`/`LogEvents`: streams service diagnostic logs to the client.
- `ConfigResponseEvent`/`ConfigChangeEvent`: remote get/set of service config.
- `get_server_status()`: query service version + connected device list
  without opening a full connection.

## 8. Project ideas mapped to features

| Idea | Uses |
|---|---|
| Gesture mouse/keyboard control | `palm.position` + `pinch_strength`/`grab_strength` |
| Custom gesture recognizer | `digits[].is_extended` combinations + bone angles |
| Low-latency VR/overlay rendering | `interpolate_frame` |
| Custom CV/ML experiments (depth, marker tracking) | raw stereo IR via `ImageEvent` (no LeapUVC needed) |
| Gesture dataset collection | `Recording`/`Recorder` |
| Extended coverage via multiple cameras | `multi_device_aware=True` + `get_devices()` |
| Robotic arm control | stream `palm`/`digits` coordinates over serial to a robot controller |

## Reference

Full API source: https://github.com/ultraleap/leapc-python-bindings
(preservation fork, used by this repo's Quickstart: https://github.com/ohora23/leapc-python-bindings)
(`leapc-python-api/src/leap/`)

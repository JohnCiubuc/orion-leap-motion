"""Webcam frame source: MediaPipe hand landmarks → Orion's Hand model (Leap axes, millimetres).

`landmarks_to_hand` is pure geometry; `import orion.webcam` needs neither OpenCV nor MediaPipe.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import APP
from .frame import FINGERS, Finger, Frame, Hand, IRImage
from .sources import Source

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
MODEL_FILE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP / "hand_landmarker.task"
log = logging.getLogger(__name__)
PREVIEW_WIDTH = 320
STALL_PERIOD = 0.05  # s between empty frames while the camera delivers nothing
PALM_LM = (0, 5, 9, 13, 17)  # wrist + the four knuckles: the palm's centre is their mean
NOMINAL_DISTANCE = 400.0  # mm from the camera that maps to leap z = 0
PALM_HEIGHT = 200.0  # mm added to y so the hand sits where the Leap would see it
DEPTH_RANGE = (100.0, 2000.0)  # mm; keeps a tiny or huge apparent hand size from producing absurd positions
DEBOUNCE = 2  # frames a finger must hold a new state before it flips
HOLD = 0.08  # s a missed hand is repeated, so one lost detection doesn't read as the hand leaving
MIN_CUTOFF, BETA, D_CUTOFF, DEPTH_CUTOFF = 1.5, 0.02, 1.0, 0.4  # shortcut: One-Euro settings guessed from synthetic jitter, retune on a real hand
MATCH_DISTANCE = 0.25  # normalised image distance within which a detection continues a track
PINCH_OPEN, PINCH_CLOSED = 60.0, 10.0  # mm between thumb and index tips for pinch 0 and 1
GRAB_OPEN, GRAB_CLOSED = 0.85, 0.60  # finger straightness for grab 0 and 1; shortcut: from synthetic hands, retune on a real hand
EXTEND_ON, EXTEND_OFF = 0.80, 0.65  # shortcut: finger straightness cut-offs picked from synthetic hands, retune on a real hand


@dataclass
class Cam:
    width: int = 640
    height: int = 480
    fov_deg: float = 70  # horizontal
    hand_mm: float = 95  # wrist → middle-knuckle
    tilt_deg: float = 0  # pitch applied to the hand's shape about its palm: 90 turns an upright hand into one lying flat


@dataclass
class Detection:
    image: np.ndarray  # (21, 3) normalised x, y (0..1, y down)
    world: np.ndarray  # (21, 3) metres, hand-centred, y down, z away from the camera
    label: str  # "left" | "right" as the detector reports it
    score: float


def _unit(v: np.ndarray) -> np.ndarray:
    return (v / (np.linalg.norm(v) or 1.0)).astype(np.float32)


def _extended(straightness: float, was: bool) -> bool:
    """Between the two cut-offs a finger keeps its previous state, so it doesn't flicker."""
    if straightness >= EXTEND_ON:
        return True
    return was and straightness >= EXTEND_OFF


def _straightness(pts: np.ndarray) -> float:
    """Chord over path length of a finger's four landmarks: 1 when straight, lower as it curls."""
    path = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
    return float(np.linalg.norm(pts[-1] - pts[0])) / path if path > 1e-6 else 0.0


def _focal(cam: Cam) -> float:
    return (cam.width / 2) / math.tan(math.radians(cam.fov_deg) / 2)


def _spread(points: np.ndarray) -> float:
    """Mean distance of the points from their centre."""
    return float(np.linalg.norm(points - points.mean(axis=0), axis=1).mean())


def _world_mm(det: Detection, cam: Cam) -> np.ndarray:
    """MediaPipe's hand shape in mm, y up, scaled so wrist → middle-knuckle is the user's `hand_mm` (for depth only)."""
    w = det.world * (1000, -1000, 1000)
    length = float(np.linalg.norm(w[9] - w[0]))
    return w * (cam.hand_mm / length if length > 1e-6 else 1.0)


def apparent_depth(det: Detection, cam: Cam) -> float:
    """Distance from the camera in mm: how big the palm looks against how big it really is. Both are measured
    across the image plane, so tilting the hand toward the camera shrinks them alike and the estimate holds."""
    px = _spread(det.image[list(PALM_LM), :2] * (cam.width, cam.height))
    mm = _spread(_world_mm(det, cam)[list(PALM_LM), :2])
    return min(max(_focal(cam) * mm / max(px, 1e-3), DEPTH_RANGE[0]), DEPTH_RANGE[1])


def landmarks_to_hand(det: Detection, cam: Cam, prev_extended: frozenset[str] = frozenset(), hid: int = 0,
                      depth: float | None = None) -> Hand:
    """`depth` overrides the distance estimate (the tracker passes a smoothed one)."""
    f = _focal(cam)
    px = det.image[:, :2] * (cam.width, cam.height)
    z = apparent_depth(det, cam) if depth is None else depth
    c = px[list(PALM_LM)].mean(axis=0)
    palm = np.array(((c[0] - cam.width / 2) * z / f,
                     -(c[1] - cam.height / 2) * z / f + PALM_HEIGHT,
                     z - NOMINAL_DISTANCE), np.float32)
    w = det.world * (1000, -1000, 1000)  # the fingertip keeps MediaPipe's own scale: re-scaling per frame would add jitter
    a = math.radians(cam.tilt_deg)  # Orion's gestures expect the hand lying flat, as over a Leap: pitch it about the palm
    pitch = np.array(((1, 0, 0), (0, math.cos(a), math.sin(a)), (0, -math.sin(a), math.cos(a))))
    w = (w - w[list(PALM_LM)].mean(axis=0)) @ pitch.T + palm
    fingers, straight = [], []
    for k, name in enumerate(FINGERS):
        pts = w[4 * k + 1:4 * k + 5]
        straight.append(_straightness(pts))
        joints = np.vstack((w[0], pts)).astype(np.float32)
        fingers.append(Finger(name, _extended(straight[-1], name in prev_extended), joints))
    pinch = min(max((PINCH_OPEN - float(np.linalg.norm(w[4] - w[8]))) / (PINCH_OPEN - PINCH_CLOSED), 0.0), 1.0)
    grab = float(np.mean([min(max((GRAB_OPEN - s) / (GRAB_OPEN - GRAB_CLOSED), 0.0), 1.0) for s in straight[1:]]))
    normal = np.cross(w[5] - w[0], w[17] - w[0]) * (-1 if det.label == "left" else 1)
    direction = w[9] - w[0]
    return Hand(hid, det.label, det.score, pinch, grab, palm, palm.copy(), np.zeros(3, np.float32),
                _unit(normal), _unit(direction), tuple(fingers))


def _alpha(cutoff, dt):
    return 1 / (1 + 1 / (2 * math.pi * cutoff * dt))


class OneEuro:
    """Low-pass filter that smooths hard while the signal is still and lightly while it moves.
    `dx` is the smoothed rate of change, in units per second."""

    def __init__(self, min_cutoff=MIN_CUTOFF, beta=BETA):
        self.min_cutoff, self.beta = min_cutoff, beta
        self.t = self.x = self.raw = self.dx = None

    def __call__(self, t: float, x: np.ndarray) -> np.ndarray:
        if self.x is None:
            self.t, self.raw, self.dx = t, x, np.zeros(x.shape)
            self.x = x.astype(np.float64)
            return self.x
        dt = max(t - self.t, 1e-3)
        self.dx = self.dx + _alpha(D_CUTOFF, dt) * ((x - self.raw) / dt - self.dx)
        self.x = self.x + _alpha(self.min_cutoff + self.beta * np.abs(self.dx), dt) * (x - self.x)
        self.t, self.raw = t, x
        return self.x


class _Track:
    def __init__(self, hid):
        self.id, self.filter, self.depth, self.extended, self.flip = hid, OneEuro(), OneEuro(DEPTH_CUTOFF, 0.0), frozenset(), dict.fromkeys(FINGERS, 0)
        self.hand, self.seen, self.at = None, 0.0, np.zeros(2)


class HandTracker:
    """Turns each frame's detections into steady `Hand`s: stable ids, debounced fingers, smoothed positions,
    velocity, and a short hold over missed detections. Call `update` once per captured frame."""

    def __init__(self, cam: Cam):
        self.cam, self.tracks, self.next_id = cam, [], 1

    def update(self, t: float, dets: list[Detection]) -> tuple[Hand, ...]:
        free, hands = list(self.tracks), []
        for det in dets:
            at = det.image[list(PALM_LM), :2].mean(axis=0)
            near = min(free, key=lambda tr: np.linalg.norm(tr.at - at), default=None)
            if near is None or np.linalg.norm(near.at - at) > MATCH_DISTANCE:
                near = _Track(self.next_id)
                self.next_id += 1
                self.tracks.append(near)
            else:
                free.remove(near)
            near.at, near.seen = at, t
            depth = float(near.depth(t, np.array(apparent_depth(det, self.cam))))  # distance is the noisiest estimate: smooth it hardest
            near.hand = self._smooth(t, near, landmarks_to_hand(det, self.cam, near.extended, near.id, depth))
            hands.append(near.hand)
        for tr in free:  # not seen this frame
            if t - tr.seen <= HOLD:
                hands.append(tr.hand)
            else:
                self.tracks.remove(tr)
        return tuple(hands)

    def _smooth(self, t, tr, raw: Hand) -> Hand:
        for f in raw.fingers:  # a finger flips only after DEBOUNCE frames in the new state
            tr.flip[f.name] = tr.flip[f.name] + 1 if f.extended != (f.name in tr.extended) else 0
            if tr.flip[f.name] >= DEBOUNCE:
                tr.extended, tr.flip[f.name] = tr.extended ^ {f.name}, 0
        v = tr.filter(t, np.concatenate((raw.palm, np.stack([f.joints for f in raw.fingers]).ravel(),
                                         (raw.pinch, raw.grab), raw.normal, raw.direction)))
        palm = v[:3].astype(np.float32)
        fingers = tuple(Finger(f.name, f.name in tr.extended, v[3 + 15 * k:18 + 15 * k].reshape(5, 3).astype(np.float32))
                        for k, f in enumerate(raw.fingers))
        return dataclasses.replace(raw, palm=palm, stable=palm.copy(), velocity=tr.filter.dx[:3].astype(np.float32),
                                   pinch=float(min(max(v[78], 0), 1)), grab=float(min(max(v[79], 0), 1)),
                                   normal=_unit(v[80:83]), direction=_unit(v[83:86]), fingers=fingers)


# ── Source ────────────────────────────────────────────────────────────────────

def find_cameras(root: Path = Path("/sys/class/video4linux")) -> list[dict]:
    """Capture nodes of the attached cameras (a camera's later nodes carry metadata, not images)."""
    nodes = sorted((d for d in root.glob("video*") if d.name[5:].isdigit()), key=lambda d: int(d.name[5:]))
    return [{"path": f"/dev/{d.name}", "name": (d / "name").read_text().strip()}
            for d in nodes if (d / "index").read_text().strip() == "0"]


def ensure_model(path: Path = MODEL_FILE, url: str = MODEL_URL) -> Path:
    """The hand-landmark model is not bundled with mediapipe: fetch it once, never leaving a partial file."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:
            f.write(r.read())
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Could not download the hand model ({e})") from e
    tmp.replace(path)
    return path


def _cv_capture(path: str, cfg: dict):
    import cv2
    cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
    for prop, key in ((cv2.CAP_PROP_FRAME_WIDTH, "width"), (cv2.CAP_PROP_FRAME_HEIGHT, "height"), (cv2.CAP_PROP_FPS, "fps")):
        cap.set(prop, cfg[key])
    return cap


def _mediapipe_detector():
    import mediapipe as mp
    from mediapipe.tasks import python as tasks
    from mediapipe.tasks.python import vision
    landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=tasks.BaseOptions(model_asset_path=str(ensure_model())),
        running_mode=vision.RunningMode.VIDEO, num_hands=2))
    xyz = lambda pts: np.array([(p.x, p.y, p.z) for p in pts])  # noqa: E731

    def detect(rgb, t_ms):
        r = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)), t_ms)
        return [Detection(xyz(img), xyz(world), cats[0].category_name.lower(), cats[0].score)
                for img, world, cats in zip(r.hand_landmarks, r.hand_world_landmarks, r.handedness)]
    return detect


class WebcamSource(Source):
    name = "webcam"

    def __init__(self, on_frame, on_image, ir_fps: float = 30, *, cfg: dict, capture_factory=None,
                 detector_factory=None, cameras: list[dict] | None = None):
        super().__init__(on_frame, on_image, ir_fps)
        self.cfg, self.capture_factory = cfg, capture_factory or _cv_capture
        self.detector_factory = detector_factory or _mediapipe_detector
        self.status.update(cameras=find_cameras() if cameras is None else cameras, error="")

    def run(self):
        cap, self._streaming = None, False
        try:
            detect = self.detector_factory()
            cap = self._open()
            self._streaming = True
            self._loop(cap, detect)
        except ImportError as e:
            self._fail(f'The webcam source needs the "webcam" extra: pip install -e ".[webcam]" ({e})')
        except Exception as e:
            self._fail(str(e))
        finally:
            if cap:
                cap.release()
            if self._streaming:  # whatever ended the loop, let an open menu see the hand go
                self._empty(time.monotonic())

    def _empty(self, t):
        try:
            self.on_frame(Frame(t=t, fps=0.0, source="webcam"))
        except Exception:
            log.exception("webcam: empty frame failed")

    def _fail(self, text):
        self.status.update(connected=False, error=text)

    def _open(self):
        """The configured device, or in auto mode the first camera that opens and returns an image."""
        cameras, device = self.status["cameras"], self.cfg["device"]
        names = {c["path"]: c["name"] for c in cameras}
        for path in [c["path"] for c in cameras] if device == "auto" else [device]:
            try:
                cap = self.capture_factory(path, self.cfg)
            except Exception:
                continue
            if cap.read()[0]:
                self.status.update(connected=True, device=names.get(path, path), error="")
                return cap
            cap.release()
        raise RuntimeError("No webcam found" if device == "auto" else f"Could not open {device}")

    def _loop(self, cap, detect):
        tracker, last, fps, last_ms = None, time.monotonic(), 0.0, 0
        while not self._stop.is_set():
            ok, image = cap.read()
            t = time.monotonic()
            self.status["connected"] = bool(ok)
            if not ok:  # keep the clock running so OrionDo's "hand lost" close and pose ends still happen
                self._empty(t)
                self._stop.wait(STALL_PERIOD)
                continue
            try:  # one bad frame (detector or a gesture raising) must not end the stream: the menu only closes on frames
                if self.cfg["mirror"]:
                    image = image[:, ::-1]  # so moving your hand right moves it right
                if tracker is None:
                    tracker = HandTracker(Cam(image.shape[1], image.shape[0], self.cfg["fov_deg"], self.cfg["hand_mm"],
                                              self.cfg["tilt"]))
                fps += (1 / max(t - last, 1e-3) - fps) * 0.1
                last, last_ms = t, max(int(t * 1000), last_ms + 1)  # the detector needs strictly rising timestamps
                dets = detect(image[:, :, ::-1], last_ms)  # BGR → RGB
                if self.cfg["mirror"]:  # the detector sees a mirrored hand, so it names the other side
                    dets = [dataclasses.replace(d, label="left" if d.label == "right" else "right") for d in dets]
                hands = tracker.update(t, dets)
                self.on_frame(Frame(t=t, fps=fps, hands=hands, source="webcam"))
                self._emit_ir(lambda: self._preview(image))
            except Exception:
                log.exception("webcam: frame failed")
                self._empty(t)

    @staticmethod
    def _preview(image) -> IRImage:
        small = image[::max(1, image.shape[1] // PREVIEW_WIDTH), ::max(1, image.shape[1] // PREVIEW_WIDTH)]
        gray = small.mean(axis=2).astype(np.uint8)
        return IRImage(gray.shape[1], gray.shape[0] * 2, np.vstack((gray, gray)).tobytes())  # IRView expects a stereo pair

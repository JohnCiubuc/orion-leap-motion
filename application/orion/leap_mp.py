"""Leap (MediaPipe) source: MediaPipe Hands on both undistorted Leap IR images, each view checking the other.

The geometry, crop and fusion code is pure numpy; `cv2` and `mediapipe` are imported inside the functions that need them.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .frame import Frame, Hand, IRImage, from_leap
from .sources import LeapSource, raw_images
from .webcam import PALM_LM, PINCH_CLOSED, PINCH_OPEN, Cam, Detection, HandTracker, _Track, apparent_depth, points_to_hand

log = logging.getLogger(__name__)
DEPTH_MM = (60.0, 600.0)  # a hand over the device: nearer or further is a mismatch, not a hand
MIN_AGREEING = 18  # of 21 landmarks need a positive disparity
EXTEND = (0.90, 0.85)  # (on, off) finger straightness; shortcut: MediaPipe under-curls fingers (curled ones read 0.75-0.78, the Leap's 0.63), tuned on one hand
PINCH_MAX_GRAB = 0.35  # shortcut: an OK sign reads 0.13-0.15, a thumbs up 0.5-0.86; tuned on one hand
LABEL_FRAMES = 15  # consecutive frames of the other label before the hand's side changes (MediaPipe guesses it per frame)
SETUP_RETRY_S = 3.0  # wait this long after a failed setup before trying again


@dataclass(frozen=True)
class Pinhole:
    """The ideal camera both IR images are rectified to (the Leap's own lens is ~130° wide and distorted)."""
    f: float = 143.0
    w: int = 640
    h: int = 240

    @property
    def cx(self) -> float:
        return self.w / 2

    @property
    def cy(self) -> float:
        return self.h / 2


class Rectifier:
    """Undistorts raw IR images onto a shared pinhole. `project(camera, ray)` gives the raw pixel a ray lands on."""

    def __init__(self, project: Callable[[str, tuple[float, float, float]], tuple[float, float]],
                 pinhole: Pinhole = Pinhole()):
        self.pinhole, self.maps = pinhole, {}
        for camera in ("left", "right"):
            xs = np.empty((pinhole.h, pinhole.w), np.float32)
            ys = np.empty_like(xs)
            for v in range(pinhole.h):
                for u in range(pinhole.w):
                    xs[v, u], ys[v, u] = project(camera, ((u - pinhole.cx) / pinhole.f, (v - pinhole.cy) / pinhole.f, 1.0))
            self.maps[camera] = (xs, ys)

    def rectify(self, camera: str, gray: np.ndarray) -> np.ndarray:
        import cv2
        return cv2.remap(gray, *self.maps[camera], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


@dataclass
class View:
    """One camera's hand: rectified pixels, MediaPipe's hand-centred world shape, and its label and score."""
    px: np.ndarray  # (21, 2)
    world: np.ndarray  # (21, 3) metres, x right, y down, z forward
    label: str
    score: float


def triangulate(left_px: np.ndarray, right_px: np.ndarray, pinhole: Pinhole, baseline: float) -> np.ndarray:
    """(21, 3) mm in the left camera's frame (x right, y down, z forward) from the same landmarks in both rectified images.
    A landmark the cameras barely disagree on (depth outside `DEPTH_MM`) takes the hand's median depth along its own ray."""
    d = left_px[:, 0] - right_px[:, 0]
    with np.errstate(divide="ignore"):
        z = np.where(d > 0, pinhole.f * baseline / np.maximum(d, 1e-12), np.nan)
    bad = ~((z >= DEPTH_MM[0]) & (z <= DEPTH_MM[1]))  # NaN compares false, so it counts as bad
    z[bad] = np.median(z[~bad]) if (~bad).any() else DEPTH_MM[1]
    return np.column_stack(((left_px[:, 0] - pinhole.cx) * z / pinhole.f,
                            ((left_px[:, 1] + right_px[:, 1]) / 2 - pinhole.cy) * z / pinhole.f, z))


def backproject(view: View, pinhole: Pinhole, hand_mm: float) -> np.ndarray:
    """(21, 3) mm in the camera's frame from one view: palm depth from how big the palm looks, shape from MediaPipe."""
    cam = Cam(pinhole.w, pinhole.h, math.degrees(2 * math.atan(pinhole.w / 2 / pinhole.f)), hand_mm)
    norm = view.px / (pinhole.w, pinhole.h)
    z = apparent_depth(Detection(np.column_stack((norm, np.zeros(21))), view.world, view.label, view.score), cam)
    c = view.px[list(PALM_LM)].mean(axis=0)
    palm = np.array(((c[0] - pinhole.cx) * z / pinhole.f, (c[1] - pinhole.cy) * z / pinhole.f, z))
    w = view.world * 1000
    w = w * (hand_mm / (float(np.linalg.norm(w[9] - w[0])) or 1.0))
    return palm + w - w[list(PALM_LM)].mean(axis=0)


def to_leap_axes(points: np.ndarray, cam_x: float) -> np.ndarray:
    """A camera's frame (x right and y down in its image, z forward) → Leap axes (y away from the device, z toward the user).
    `cam_x` is where that camera sits along the Leap's x. Measured against the Leap's own tracking: image x runs toward
    Leap -x, image y toward +z, and the cameras (LeapExtrinsicCameraMatrix) sit at x = -20 (left) and +20 (right) mm."""
    return np.column_stack((cam_x - points[:, 0], points[:, 2], points[:, 1]))


def agreement(left_px: np.ndarray, right_px: np.ndarray, pinhole: Pinhole, baseline: float, agree_px: float) -> bool:
    """Whether two rectified views can be the same hand: same rows, a positive disparity, a plausible depth."""
    if float(np.median(np.abs(left_px[:, 1] - right_px[:, 1]))) >= agree_px:
        return False
    d = left_px[:, 0] - right_px[:, 0]
    if int((d > 0).sum()) < MIN_AGREEING:
        return False
    return DEPTH_MM[0] <= float(np.median(pinhole.f * baseline / d[d > 0])) <= DEPTH_MM[1]


# ── Finding a hand in one camera ──────────────────────────────────────────────

CROP_SCALE = 1.6  # tracking window = this × the hand's bounding-box side (about 2.5× the palm)
CROP_MIN = 96  # px; MediaPipe's palm detector needs the hand at a usable size
LOST_AFTER = 3  # consecutive misses before searching the whole frame again
CROP_INPUT = 256  # px; what MediaPipe is given


def search_windows(w: int, h: int) -> list[tuple[int, int, int]]:
    """Square `(x0, y0, side)` windows that together cover a wide, short frame: tried one per frame while no hand is tracked."""
    side = min(w, h)
    return [(round(x), 0, side) for x in np.linspace(0, w - side, 3)]


def crop_around(center: tuple[float, float], side: float, w: int, h: int) -> tuple[int, int, int]:
    """Square window of about `side` px centred on `center`, kept inside the frame."""
    s = round(min(max(side, CROP_MIN), min(w, h)))
    return (int(min(max(round(center[0] - s / 2), 0), w - s)), int(min(max(round(center[1] - s / 2), 0), h - s)), s)


class HandFinder:
    """One camera's hand: searches the frame window by window, then follows the hand with a tight crop.

    `backend(crop)` returns `[(landmarks (21, 2) in 0..1 of the crop, world (21, 3), label, score)]`."""

    def __init__(self, backend, pinhole: Pinhole = Pinhole(), min_score: float = 0.5):
        self.backend, self.pinhole, self.min_score = backend, pinhole, min_score
        self.center = self.side = None
        self.misses = self.searched = 0

    def find(self, gray: np.ndarray) -> View | None:
        h, w = gray.shape[:2]
        if self.center is None:
            x0, y0, s = search_windows(w, h)[self.searched % 3]
            self.searched += 1
        else:
            x0, y0, s = crop_around(self.center, CROP_SCALE * self.side, w, h)
        found = [r for r in self.backend(gray[y0:y0 + s, x0:x0 + s]) if r[3] >= self.min_score]
        if not found:
            self.misses += 1
            if self.center is not None and self.misses >= LOST_AFTER:
                self.center, self.searched = None, 0
            return None
        norm, world, label, score = max(found, key=lambda r: r[3])
        px = np.column_stack((x0 + norm[:, 0] * s, y0 + norm[:, 1] * s))
        self.center, self.side, self.misses = px[list(PALM_LM)].mean(axis=0), float(np.ptp(px, axis=0).max()), 0
        return View(px, world, label, score)


def mediapipe_backend(delegate: str = "gpu"):
    """The real backend for `HandFinder`: one single-image MediaPipe hand landmarker, crops upscaled to 256 px.
    Runs on the GPU when asked (about 4× faster than the CPU here), and moves to the CPU for good if the GPU cannot
    start or fails on a frame; `.delegate` says which is in use."""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as tasks
    from mediapipe.tasks.python import vision

    from .webcam import ensure_model

    def make(kind):
        d = tasks.BaseOptions.Delegate.GPU if kind == "gpu" else tasks.BaseOptions.Delegate.CPU
        return vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=tasks.BaseOptions(model_asset_path=str(ensure_model()), delegate=d),
            running_mode=vision.RunningMode.IMAGE, num_hands=1))

    def to_cpu(why):
        log.warning("leap_mp: GPU delegate unusable (%s); running MediaPipe on the CPU", why)
        backend.delegate, state["landmarker"] = "cpu", make("cpu")

    state = {}

    def backend(crop):
        rgb = cv2.cvtColor(cv2.resize(crop, (CROP_INPUT, CROP_INPUT)), cv2.COLOR_GRAY2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        try:
            r = state["landmarker"].detect(image)
        except Exception as e:
            if backend.delegate == "cpu":
                raise
            to_cpu(e)
            r = state["landmarker"].detect(image)
        return [(np.array([(p.x, p.y) for p in img]), np.array([(p.x, p.y, p.z) for p in world]),
                 cats[0].category_name.lower(), cats[0].score)
                for img, world, cats in zip(r.hand_landmarks, r.hand_world_landmarks, r.handedness)]

    backend.delegate = delegate
    backend.close = lambda: state["landmarker"].close()
    try:
        state["landmarker"] = make(delegate)
    except Exception as e:
        if delegate == "cpu":
            raise
        to_cpu(e)
    return backend


def planar_pinch(w: np.ndarray, grab: float = 0.0) -> float:
    """Thumb-index pinch, 0..1, from the tips' distance across the image plane (Leap x, z): depth is MediaPipe's weakest axis.
    Zero for a closed hand: in a fist or a thumbs up the thumb merely rests on the index."""
    if grab >= PINCH_MAX_GRAB:
        return 0.0
    d = float(np.hypot(w[4, 0] - w[8, 0], w[4, 2] - w[8, 2]))
    return min(max((PINCH_OPEN - d) / (PINCH_OPEN - PINCH_CLOSED), 0.0), 1.0)


# ── Two views, one hand ───────────────────────────────────────────────────────

class Fusion:
    """Turns the two cameras' views into one steady `Hand`: triangulated when they agree, from one camera when only one
    sees the hand, and dropped (after a short hold) when they disagree. `cfg`: `agree_px`, `hold`, `hand_mm`."""

    def __init__(self, cfg: dict, pinhole: Pinhole = Pinhole(), baseline: float = 40.0):
        self.cfg, self.pinhole, self.baseline = cfg, pinhole, baseline
        self.smoother, self.track = HandTracker(Cam()), _Track(1)  # one hand: one track, smoothed like the webcam's
        self._side, self._flips = None, 0

    def update(self, t: float, left: View | None, right: View | None) -> tuple[tuple[Hand, ...], str]:
        half = self.baseline / 2
        if left and right:
            first, second = right, left  # image x runs toward Leap -x, so the right camera is the pair's first (smaller image x)
            if not agreement(first.px, second.px, self.pinhole, self.baseline, self.cfg["agree_px"]):
                return self._held(t), "disagree"
            points, cam_x, status = triangulate(first.px, second.px, self.pinhole, self.baseline), half, "agree"
        elif left or right:
            view = left or right
            points = backproject(view, self.pinhole, self.cfg["hand_mm"])
            cam_x, status = (-half, "left only") if left else (half, "right only")
        else:
            return self._held(t), "none"
        best = max((v for v in (left, right) if v), key=lambda v: v.score)
        w = to_leap_axes(points, cam_x)
        palm = w[list(PALM_LM)].mean(axis=0).astype(np.float32)
        raw = points_to_hand(w, palm, self._steady_side(best.label), best.score, self.track.extended, 1, EXTEND)
        hand = self.smoother._smooth(t, self.track, dataclasses.replace(raw, pinch=planar_pinch(w, raw.grab)))
        self.track.hand, self.track.seen = hand, t
        return (hand,), status

    def _steady_side(self, seen: str) -> str:
        if self._side is None:
            self._side = seen
        elif seen == self._side:
            self._flips = 0
        else:
            self._flips += 1
            if self._flips >= LABEL_FRAMES:
                self._side, self._flips = seen, 0
        return self._side

    def _held(self, t: float) -> tuple[Hand, ...]:
        """The last hand while a miss is shorter than `hold`; after that the track starts over."""
        if self.track.hand is None:
            return ()
        if t - self.track.seen <= self.cfg["hold"]:
            return (self.track.hand,)
        self.track, self._side = _Track(1), None
        return ()


# ── Preview ───────────────────────────────────────────────────────────────────

def preview(left: np.ndarray, right: np.ndarray, view_left: View | None, view_right: View | None) -> IRImage:
    """The rectified pair stacked for the IR view, with each found hand's landmarks as bright dots."""
    out = []
    for img, view in ((left, view_left), (right, view_right)):
        img = img.copy()
        if view is not None:
            for x, y in np.rint(view.px).astype(int):
                img[max(y - 1, 0):y + 2, max(x - 1, 0):x + 2] = 255
        out.append(img)
    return IRImage(left.shape[1], left.shape[0] * 2, np.vstack(out).tobytes())


# ── The source ────────────────────────────────────────────────────────────────

def leapc_rectifier(conn) -> Rectifier:
    """A `Rectifier` over the connected device's own lens calibration, with `.baseline` (mm) read from its camera extrinsics."""
    from leapc_cffi import ffi, libleapc
    ptr = conn.get_connection_ptr()
    cameras = {"left": libleapc.eLeapPerspectiveType_stereo_left, "right": libleapc.eLeapPerspectiveType_stereo_right}
    ray = ffi.new("LEAP_VECTOR*")

    def project(camera, r):
        ray.x, ray.y, ray.z = r
        pixel = libleapc.LeapRectilinearToPixel(ptr, cameras[camera], ray[0])
        return pixel.x, pixel.y

    rectifier = Rectifier(project)
    x = {}
    for name, camera in cameras.items():
        m = ffi.new("float[16]")
        libleapc.LeapExtrinsicCameraMatrix(ptr, camera, m)
        x[name] = m[12]  # the camera's offset along the device's x axis
    baseline = x["right"] - x["left"]
    rectifier.baseline = baseline if 20.0 <= baseline <= 80.0 else 40.0  # shortcut: a Leap's cameras are 40 mm apart, so an odd reading means the calibration was not ready
    return rectifier


class LeapMediaPipeSource(LeapSource):
    """The Leap's two IR cameras, tracked by MediaPipe instead of the Leap's own hand model."""
    name = "leap_mp"
    always_images = True

    def __init__(self, on_frame, on_image, ir_fps: float = 30, *, cfg: dict, rectifier_factory=None, finder_factory=None):
        super().__init__(on_frame, on_image, ir_fps)
        self.cfg = cfg
        self._left_only = cfg["cameras"] == "left"
        self.rectifier_factory = rectifier_factory or leapc_rectifier
        self.finder_factory = finder_factory or (lambda: HandFinder(mediapipe_backend(cfg["delegate"]), min_score=cfg["min_score"]))
        self.on_reference = None  # optional callback for Leap's own frames (the compare script)
        self._slot, self._dropped, self._wake, self._lock = None, 0, threading.Event(), threading.Lock()
        self._rect = self._fusion = self._finders = self._worker = None
        self._broken, self._fps, self._last = False, 0.0, 0.0
        self._setup_thread, self._retry_at, self._image_error = None, 0.0, False

    # ── LeapSource hooks ──────────────────────────────────────────────────────

    def _tracking(self, e):
        if self.on_reference:
            self.on_reference(from_leap(e))

    def _images(self, e):
        try:
            self._offer(tuple(np.frombuffer(px, np.uint8).reshape(h, w) for w, h, px in raw_images(e)))
        except Exception as err:  # runs on Leap's poll thread: an odd image must not break it
            if not self._image_error:
                self._image_error = True
                log.warning("leap_mp: unusable image event: %s", err)

    def _on_open(self, conn):
        if self._worker is None:
            self._worker = threading.Thread(target=self._work, name="leap-mp", daemon=True)
            self._worker.start()

    def stop(self):
        super().stop()
        self._wake.set()
        if self._worker is not None:
            self._worker.join(timeout=2)  # let a detection in flight finish rather than die with the process
        for finder in self._finders or ():
            close = getattr(getattr(finder, "backend", None), "close", None)
            if close:
                close()

    # ── Worker ────────────────────────────────────────────────────────────────

    def _offer(self, pair):
        """Keep only the newest pair: MediaPipe is slower than the cameras, and old frames would only add latency."""
        with self._lock:
            self._dropped += self._slot is not None
            self._slot = pair
        self._wake.set()

    def _work(self):
        while not self._stop.is_set():
            if not self._wake.wait(0.5):
                continue
            with self._lock:
                pair, self._slot = self._slot, None
                self._wake.clear()
            if pair is not None:
                try:
                    self._process(pair, time.monotonic())
                except Exception:  # the worker is never restarted, so nothing may end it
                    log.exception("leap_mp: worker error")

    def _ensure_setup(self):
        """Start (or, after a back-off, retry) the setup on its own thread: the model load can take seconds, or a download
        far longer, and frames have to keep flowing meanwhile or the watchdog would restart the controller."""
        if self._broken or time.monotonic() < self._retry_at or (self._setup_thread and self._setup_thread.is_alive()):
            return
        self._setup_thread = threading.Thread(target=self._setup, name="leap-mp-setup", daemon=True)
        self._setup_thread.start()

    def _setup(self) -> bool:
        """Build the rectifier, finders and fusion, each once (the calibration is only readable once images flow)."""
        if self._broken:
            return False
        try:
            self._rect = self._rect or self.rectifier_factory(getattr(self, "_conn", None))
            self._finders = self._finders or (self.finder_factory(), None if self._left_only else self.finder_factory())
            self._fusion = Fusion(self.cfg, baseline=getattr(self._rect, "baseline", 40.0))
            self.status["delegate"] = getattr(self._finders[0].backend, "delegate", "")
            self.status["error"] = ""
        except ImportError as e:
            self._broken = True
            self.status["error"] = f'The Leap (MediaPipe) source needs the "webcam" extra: pip install -e ".[webcam]" ({e})'
        except Exception as e:
            self._retry_at = time.monotonic() + SETUP_RETRY_S
            self.status["error"] = f"Could not set up the Leap (MediaPipe) source: {e}"
            log.warning("leap_mp: setup failed: %s", e)
        return self._fusion is not None

    def _process(self, pair, t: float):
        try:
            if self._fusion is None:
                self._ensure_setup()
                return self._emit(t, ())
            left = self._rect.rectify("left", pair[0])
            right = np.zeros_like(left) if self._left_only else self._rect.rectify("right", pair[1])
            views = (self._finders[0].find(left), None if self._left_only else self._finders[1].find(right))
            hands, self.status["agreement"] = self._fusion.update(t, *views)
            self._emit(t, hands)
            self._emit_ir(lambda: preview(left, right, *views))
        except Exception:  # one bad frame must not end the stream: the menu and the watchdog both run on frames
            log.exception("leap_mp: frame failed")
            self._emit(t, ())

    def _emit(self, t: float, hands):
        self._fps += (1 / max(t - self._last, 1e-3) - self._fps) * 0.1
        self._last = t
        self.on_frame(Frame(t=t, fps=self._fps, hands=tuple(hands), source="leap_mp"))

"""Real-time visualization of Leap Motion hand tracking: raw IR camera feed
(actual captured hand shape) side by side with the skeleton overlay
(palm + finger bones, pinch/grab scores)."""

import os
import sys
import threading

# Wayland (Hyprland, Sway, GNOME, KDE...): the pip `opencv-python` wheel bundles
# a Qt build that has only the X11 "xcb" platform plugin. Left alone, Qt sees
# WAYLAND_DISPLAY, looks for a wayland plugin, warns, and may fail to open a
# window. Point it at XWayland explicitly. This must happen before cv2 is
# imported. Set QT_QPA_PLATFORM yourself to override.
if os.environ.get("WAYLAND_DISPLAY") and "QT_QPA_PLATFORM" not in os.environ:
    if os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    else:
        sys.exit(
            "Wayland session without XWayland (DISPLAY is unset). OpenCV's "
            "window needs XWayland; enable it in your compositor (Hyprland: "
            "`xwayland { enabled = true }`, the default)."
        )

import cv2
import numpy as np
import leap
from leap.enums import PolicyFlag
from leapc_cffi import ffi

SKELETON_W, SKELETON_H = 800, 600
X_RANGE = (-200, 200)  # mm, left/right
Y_RANGE = (0, 500)  # mm, height above device

IR_SCALE = 2  # native IR image is 640x240

COLORS = {"HandType.Left": (255, 120, 0), "HandType.Right": (0, 200, 255)}


def to_px(x, y):
    px = int((x - X_RANGE[0]) / (X_RANGE[1] - X_RANGE[0]) * SKELETON_W)
    py = int(SKELETON_H - (y - Y_RANGE[0]) / (Y_RANGE[1] - Y_RANGE[0]) * SKELETON_H)
    return px, py


def image_to_array(img):
    """Copy a leap.datatypes.Image's raw pixel buffer out to a numpy array.

    Must be called synchronously inside the event callback -- the underlying
    C buffer is only valid until the next poll (same UAF hazard the bindings'
    own TrackingEvent guards against for hand data).
    """
    props = img.c_data.properties
    w, h, bpp = props.width, props.height, props.bpp
    ptr = ffi.cast("uint8_t*", img.c_data.data) + img.c_data.offset
    buf = ffi.buffer(ptr, w * h * bpp)
    return np.frombuffer(buf, dtype=np.uint8).reshape((h, w)).copy()


class VizListener(leap.Listener):
    def __init__(self):
        self.lock = threading.Lock()
        self.latest = None
        self.latest_ir = None

    def on_tracking_event(self, event):
        with self.lock:
            self.latest = event

    def on_image_event(self, event):
        ir_frame = image_to_array(event.image[0])
        with self.lock:
            self.latest_ir = ir_frame


def draw_hand(img, hand):
    color = COLORS.get(str(hand.type), (255, 255, 255))
    px, py = to_px(hand.palm.position.x, hand.palm.position.y)
    cv2.circle(img, (px, py), 10, color, -1)

    for digit in hand.digits:
        pts = []
        for bone in digit.bones:
            p1 = to_px(bone.prev_joint.x, bone.prev_joint.y)
            p2 = to_px(bone.next_joint.x, bone.next_joint.y)
            cv2.line(img, p1, p2, color, 3)
            pts.append(p2)
        for p in pts:
            cv2.circle(img, p, 4, (255, 255, 255), -1)

    label = f"{str(hand.type).split('.')[-1]} pinch={hand.pinch_strength:.2f} grab={hand.grab_strength:.2f}"
    cv2.putText(img, label, (px - 60, py - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def render_skeleton_panel(event):
    img = np.zeros((SKELETON_H, SKELETON_W, 3), dtype=np.uint8)
    cv2.putText(img, "Skeleton", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
    if event is not None:
        for hand in event.hands:
            draw_hand(img, hand)
    else:
        cv2.putText(img, "Waiting for device...", (10, SKELETON_H // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    return img


def render_ir_panel(ir_frame):
    if ir_frame is None:
        h, w = 240 * IR_SCALE, 640 * IR_SCALE
        img = np.zeros((h, w, 3), dtype=np.uint8)
        cv2.putText(img, "Waiting for camera...", (10, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
        return img
    img = cv2.cvtColor(ir_frame, cv2.COLOR_GRAY2BGR)
    img = cv2.resize(img, (ir_frame.shape[1] * IR_SCALE, ir_frame.shape[0] * IR_SCALE))
    cv2.putText(img, "IR camera (raw)", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1, cv2.LINE_AA)
    return img


def compose(ir_panel, skeleton_panel):
    target_h = ir_panel.shape[0]
    scale = target_h / skeleton_panel.shape[0]
    skeleton_resized = cv2.resize(skeleton_panel, (int(skeleton_panel.shape[1] * scale), target_h))
    return cv2.hconcat([ir_panel, skeleton_resized])


def main():
    listener = VizListener()
    connection = leap.Connection()
    connection.add_listener(listener)

    with connection.open():
        connection.set_tracking_mode(leap.TrackingMode.Desktop)
        connection.set_policy_flags(flags_to_set=[PolicyFlag.Images])

        while True:
            with listener.lock:
                event = listener.latest
                ir_frame = listener.latest_ir

            combined = compose(render_ir_panel(ir_frame), render_skeleton_panel(event))
            cv2.imshow("Leap Motion Live (q to quit)", combined)
            if cv2.waitKey(16) & 0xFF == ord("q"):
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

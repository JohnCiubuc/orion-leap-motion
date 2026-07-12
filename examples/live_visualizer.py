"""Real-time OpenCV visualization of Leap Motion hand tracking (front view, X-Y plane)."""

import threading
import cv2
import numpy as np
import leap

W, H = 800, 600
X_RANGE = (-200, 200)  # mm, left/right
Y_RANGE = (0, 500)  # mm, height above device

COLORS = {"HandType.Left": (255, 120, 0), "HandType.Right": (0, 200, 255)}


def to_px(x, y):
    px = int((x - X_RANGE[0]) / (X_RANGE[1] - X_RANGE[0]) * W)
    py = int(H - (y - Y_RANGE[0]) / (Y_RANGE[1] - Y_RANGE[0]) * H)
    return px, py


class VizListener(leap.Listener):
    def __init__(self):
        self.lock = threading.Lock()
        self.latest = None

    def on_tracking_event(self, event):
        with self.lock:
            self.latest = event


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


def main():
    listener = VizListener()
    connection = leap.Connection()
    connection.add_listener(listener)

    with connection.open():
        connection.set_tracking_mode(leap.TrackingMode.Desktop)
        while True:
            img = np.zeros((H, W, 3), dtype=np.uint8)
            cv2.putText(
                img, "Leap Motion live view (q to quit)", (10, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA
            )

            with listener.lock:
                event = listener.latest

            if event is not None:
                for hand in event.hands:
                    draw_hand(img, hand)
            else:
                cv2.putText(img, "Waiting for device...", (10, H // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)

            cv2.imshow("Leap Motion Live", img)
            if cv2.waitKey(16) & 0xFF == ord("q"):
                break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

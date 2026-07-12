"""Quick manual verification: print rich per-hand data for a short window."""

import time
import leap


class RichListener(leap.Listener):
    def on_tracking_event(self, event):
        if not event.hands:
            return
        if event.tracking_frame_id % 20 != 0:
            return
        for hand in event.hands:
            extended = [d.is_extended for d in hand.digits]
            print(
                f"[{hand.type}] palm=({hand.palm.position.x:.1f}, {hand.palm.position.y:.1f}, {hand.palm.position.z:.1f}) "
                f"pinch={hand.pinch_strength:.2f} grab={hand.grab_strength:.2f} "
                f"confidence={hand.confidence:.2f} extended(t,i,m,r,p)={extended}"
            )


def main():
    listener = RichListener()
    connection = leap.Connection()
    connection.add_listener(listener)
    with connection.open():
        connection.set_tracking_mode(leap.TrackingMode.Desktop)
        time.sleep(15)


if __name__ == "__main__":
    main()

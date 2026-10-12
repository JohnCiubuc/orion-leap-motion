"""Leap controller recovery when it stops streaming ("falls asleep").

    usb_reset()        same as unplugging and replugging the USB cable (no root:
                       the 70-leapmotion udev rule gives the desktop user access)
    restart_service()  restart the tracking service (systemd; polkit asks for your password)
Unpausing the service itself lives in LeapSource.restart (it needs the LeapC connection).
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path

LEAP_USB_IDS = {("f182", "0003"), ("2936", "1206"), ("2936", "1202")}  # LMC, LMC2, SIR170
SERVICE = "ultraleap-hand-tracking-service.service"
USBDEVFS_RESET = 0x5514  # _IO('U', 20) from linux/usbdevice_fs.h


def find_devices(sysfs: Path = Path("/sys/bus/usb/devices")) -> list[Path]:
    """/dev/bus/usb nodes of every connected Leap controller."""
    nodes = []
    for d in sysfs.iterdir() if sysfs.is_dir() else ():
        try:
            ids = ((d / "idVendor").read_text().strip(), (d / "idProduct").read_text().strip())
            if ids in LEAP_USB_IDS:
                bus, dev = int((d / "busnum").read_text()), int((d / "devnum").read_text())
                nodes.append(Path(f"/dev/bus/usb/{bus:03d}/{dev:03d}"))
        except (FileNotFoundError, ValueError):
            continue  # interfaces and hubs without these attributes
    return nodes


def usb_reset() -> int:
    """Reset every Leap controller on the bus. Returns how many were reset."""
    nodes = find_devices()
    if not nodes:
        raise RuntimeError("No Leap Motion controller found on USB. Check the cable.")
    for node in nodes:
        try:
            fd = os.open(node, os.O_WRONLY)
        except PermissionError:
            raise RuntimeError(f"No permission to reset {node}. Install the Leap udev rule "
                               "(packaging/arch/70-leapmotion.rules) or replug the device.") from None
        try:
            fcntl.ioctl(fd, USBDEVFS_RESET, 0)
        finally:
            os.close(fd)
    return len(nodes)


def restart_service():
    r = subprocess.run(["systemctl", "restart", SERVICE], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "systemctl restart failed")

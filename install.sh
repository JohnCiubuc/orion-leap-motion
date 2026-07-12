#!/usr/bin/env bash
# Installs Ultraleap Gemini v5.17.1.0 hand-tracking service + control panel on
# Linux (tested on Ubuntu 24.04, amd64), fetching the .debs from a Wayback
# Machine snapshot of the now-dead repo.ultraleap.com apt repo, then applies
# the udev fix needed for the tracking service to actually open the device.
#
# See README.md for background on why this is necessary.

set -euo pipefail

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "This installer only has archived .debs for amd64/x86_64. Aborting." >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

SERVICE_URL="https://web.archive.org/web/20260124060130id_/https://repo.ultraleap.com/apt/pool/main/u/ultraleap-hand-tracking-service/ultraleap-hand-tracking-service_5.17.1.0-a9f25232-1.0_amd64.deb"
CONTROL_PANEL_URL="https://web.archive.org/web/20260124060130id_/https://repo.ultraleap.com/apt/pool/main/u/ultraleap-hand-tracking-control-panel/ultraleap-hand-tracking-control-panel_1125862.deb"

echo "==> Downloading ultraleap-hand-tracking-service (5.17.1.0, ~700MB)..."
curl -fL --progress-bar -o "$WORKDIR/ultraleap-hand-tracking-service.deb" "$SERVICE_URL"

echo "==> Downloading ultraleap-hand-tracking-control-panel (3.4.1, ~19MB)..."
curl -fL --progress-bar -o "$WORKDIR/ultraleap-hand-tracking-control-panel.deb" "$CONTROL_PANEL_URL"

echo "==> Installing packages (requires sudo)..."
sudo dpkg -i "$WORKDIR/ultraleap-hand-tracking-service.deb" "$WORKDIR/ultraleap-hand-tracking-control-panel.deb" || {
  echo "==> dpkg reported missing dependencies, trying apt-get -f install..."
  sudo apt-get install -f -y
}

echo "==> Applying udev fix (vendor rule is broken, see README.md)..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo cp "$SCRIPT_DIR/udev/99-leapmotion-fix.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --action=add

echo "==> Restarting service..."
sudo systemctl restart ultraleap-hand-tracking-service
sleep 2

echo "==> Status:"
systemctl is-active ultraleap-hand-tracking-service
lsusb | grep -i leap || echo "(device not currently plugged in / not detected by lsusb)"

echo
echo "Done. Check 'journalctl -u ultraleap-hand-tracking-service -n 20 --no-pager'"
echo "for 'LMC detected' / firmware version to confirm the device opened correctly."
echo "For Python bindings, see the Quickstart section in README.md."

#!/usr/bin/env bash
# Installs Orion Renewal into the repo's .venv (next to the LeapC bindings),
# builds the web UI, and adds a launcher, desktop entry and uinput udev rule.
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$APP")"
VENV="$REPO/.venv"
log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m==> ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── Python: LeapC bindings first (repo script), then Orion itself ────────────
if ! "$VENV/bin/python" -c "import leap" 2>/dev/null; then
  log "LeapC bindings missing — running scripts/setup-python.sh"
  "$REPO/scripts/setup-python.sh"
fi
log "Installing Orion Renewal (editable) into .venv…"
"$VENV/bin/pip" install --quiet -e "$APP[dev]"

# ── Gesture overlay: GTK4 layer-shell, runs under the system Python ─────────
if ! pacman -Q gtk4-layer-shell python-gobject >/dev/null 2>&1; then
  read -rp "Install the on-screen gesture overlay (gtk4-layer-shell, python-gobject; uses sudo)? [Y/n] " ans
  [[ "${ans:-y}" =~ ^[Yy] ]] && sudo pacman -S --needed gtk4-layer-shell python-gobject
fi

# ── Web UI ───────────────────────────────────────────────────────────────────
command -v npm >/dev/null || die "npm not found (sudo pacman -S npm)."
log "Building the interface…"
npm --prefix "$APP/web" ci --silent || npm --prefix "$APP/web" install --silent
npm --prefix "$APP/web" run build --silent

# ── udev: input emulation permission + keep the controller awake ────────────
RULE=/etc/udev/rules.d/71-orion-uinput.rules
if ! cmp -s "$APP/udev/71-orion-uinput.rules" "$RULE"; then
  read -rp "Install Orion's udev rules (mouse/keyboard actions, no USB autosuspend for the Leap; uses sudo)? [Y/n] " ans
  if [[ "${ans:-y}" =~ ^[Yy] ]]; then
    sudo install -Dm644 "$APP/udev/71-orion-uinput.rules" "$RULE"
    echo uinput | sudo tee /etc/modules-load.d/orion-uinput.conf >/dev/null
    sudo modprobe uinput
    sudo udevadm control --reload && sudo udevadm trigger --name-match=uinput
    sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=f182
    sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=2936
  fi
fi

# ── Launcher + desktop entry ────────────────────────────────────────────────
mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
ln -sf "$VENV/bin/orion-renewal" ~/.local/bin/orion-renewal
install -m644 "$APP/orion/assets/orion.svg" ~/.local/share/icons/hicolor/scalable/apps/orion-renewal.svg
cat > ~/.local/share/applications/orion-renewal.desktop <<DESKTOP
[Desktop Entry]
Name=Orion Renewal
Comment=Leap Motion gesture control
Exec=$HOME/.local/bin/orion-renewal
Icon=orion-renewal
Type=Application
Categories=Utility;Settings;
DESKTOP

cat <<MSG

Done. Run:            orion-renewal            (or --demo to try without the device)
Start with Hyprland:  exec-once = orion-renewal --hidden     (in hyprland.conf)
Tray icon:            needs the "tray" module in your Waybar config.
MSG

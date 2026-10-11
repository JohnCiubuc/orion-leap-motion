#!/usr/bin/env bash
# Installs the Ultraleap Gemini v5.17.1.0 hand-tracking service (and,
# optionally, the 3.4.1 control panel) for the original Leap Motion Controller,
# using .debs from a Wayback Machine snapshot of the dead repo.ultraleap.com.
#
#   Arch Linux (and derivatives): builds a real pacman package from
#                                 packaging/arch/PKGBUILD and installs it, so
#                                 every file is tracked and
#                                 `pacman -R ultraleap-hand-tracking-service`
#                                 removes it cleanly.
#   Debian / Ubuntu:              installs the .debs with dpkg (original path).
#
# Either way it then applies the udev fix, then enables and starts the service.
# See README.md for background.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE=ultraleap-hand-tracking-service

WITH_CONTROL_PANEL=1
ASSUME_YES=0
ACCEPT_EULA=0

usage() {
  cat <<EOF
Usage: $0 [options]

  --no-control-panel   Install only the tracking service (skip the Unity GUI,
                       which needs XWayland on Wayland compositors).
  --accept-eula        Accept Ultraleap's EULA (leapctl eula -y) without
                       asking. Tracking does not start until it is accepted.
  -y, --yes            Do not prompt (passes --noconfirm to makepkg/pacman).
                       Does NOT imply --accept-eula.
  -h, --help           Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --no-control-panel) WITH_CONTROL_PANEL=0 ;;
    --accept-eula)      ACCEPT_EULA=1 ;;
    -y|--yes)           ASSUME_YES=1 ;;
    -h|--help)          usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==> WARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m==> ERROR:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

[[ "$(uname -m)" == "x86_64" ]] \
  || die "Only amd64/x86_64 builds of the Ultraleap service were archived."
((EUID != 0)) \
  || die "Run this as your normal user, not root (makepkg refuses root; sudo is used where needed)."

detect_family() {
  local id="" id_like=""
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    id="$(. /etc/os-release; echo "${ID:-}")"
    # shellcheck disable=SC1091
    id_like="$(. /etc/os-release; echo "${ID_LIKE:-}")"
  fi
  if [[ "$id" == arch || " $id_like " == *" arch "* ]] || have pacman; then
    echo arch
  elif [[ "$id" == debian || " $id_like " == *" debian "* ]] || have dpkg; then
    echo debian
  else
    echo unknown
  fi
}

# --------------------------------------------------------------------------
# Arch
# --------------------------------------------------------------------------
install_arch() {
  local pkgdir="$SCRIPT_DIR/packaging/arch"
  local -a confirm=()
  ((ASSUME_YES)) && confirm=(--noconfirm)

  if ! have makepkg || ! have fakeroot; then
    die "makepkg/fakeroot missing. Install them with: sudo pacman -S --needed base-devel"
  fi
  have curl || die "curl missing: sudo pacman -S --needed curl"

  log "Building pacman packages from packaging/arch/PKGBUILD."
  log "The first run downloads the service .deb (~700 MB) from the Wayback Machine."
  log "makepkg keeps the download next to the PKGBUILD, so rebuilds don't fetch it again."
  (
    cd "$pkgdir"
    # -s: pull in any missing build/runtime deps via pacman; -f: rebuild if a
    # package file already exists (e.g. after editing the PKGBUILD).
    makepkg -sf "${confirm[@]}"
  )

  # Ask makepkg which files it built, so we don't have to guess about
  # PKGEXT/pkgrel.
  local -a pkgs=() want=("$SERVICE")
  ((WITH_CONTROL_PANEL)) && want+=(ultraleap-hand-tracking-control-panel)
  local f name
  while IFS= read -r f; do
    name="$(basename "$f")"
    for w in "${want[@]}"; do
      [[ "$name" == "$w"-[0-9]* ]] && pkgs+=("$f")
    done
  done < <(cd "$pkgdir" && makepkg --packagelist)
  ((${#pkgs[@]})) || die "makepkg did not produce the expected packages."

  log "Installing: ${pkgs[*]##*/}"
  sudo pacman -U --needed "${confirm[@]}" "${pkgs[@]}"

  # The vendor rule was never installed (the package drops it), but clean up
  # the override from older versions of this script if it is present.
  if [[ -f /etc/udev/rules.d/99-leapmotion-fix.rules ]]; then
    log "Removing old /etc/udev/rules.d/99-leapmotion-fix.rules (the package now ships the rule)."
    sudo rm -f /etc/udev/rules.d/99-leapmotion-fix.rules
  fi
}

# --------------------------------------------------------------------------
# Debian / Ubuntu (original behaviour, unchanged apart from error handling)
# --------------------------------------------------------------------------
install_debian() {
  local base="https://web.archive.org/web/20260124060130id_/https://repo.ultraleap.com/apt/pool/main/u"
  local svc_url="$base/ultraleap-hand-tracking-service/ultraleap-hand-tracking-service_5.17.1.0-a9f25232-1.0_amd64.deb"
  local cp_url="$base/ultraleap-hand-tracking-control-panel/ultraleap-hand-tracking-control-panel_1125862.deb"

  WORKDIR="$(mktemp -d)"
  trap 'rm -rf "$WORKDIR"' EXIT

  local -a debs=("$WORKDIR/service.deb")
  log "Downloading ultraleap-hand-tracking-service 5.17.1.0 (~700 MB)..."
  curl -fL --progress-bar -o "$WORKDIR/service.deb" "$svc_url"
  if ((WITH_CONTROL_PANEL)); then
    log "Downloading ultraleap-hand-tracking-control-panel 3.4.1 (~19 MB)..."
    curl -fL --progress-bar -o "$WORKDIR/control-panel.deb" "$cp_url"
    debs+=("$WORKDIR/control-panel.deb")
  fi

  log "Installing packages (requires sudo)..."
  sudo dpkg -i "${debs[@]}" || {
    log "dpkg reported missing dependencies, running apt-get -f install..."
    sudo apt-get install -f -y
  }

  log "Applying udev fix (vendor rule is broken, see README.md)..."
  sudo install -Dm644 "$SCRIPT_DIR/udev/99-leapmotion-fix.rules" \
    /etc/udev/rules.d/99-leapmotion-fix.rules
  sudo udevadm control --reload-rules
}

# --------------------------------------------------------------------------
family="$(detect_family)"
case "$family" in
  arch)   install_arch ;;
  debian) install_debian ;;
  *) die "Unsupported distribution (need pacman or dpkg). See packaging/arch/PKGBUILD for the layout fixes." ;;
esac

log "Re-applying udev rules to an already-plugged-in device..."
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=f182 --action=add

log "Enabling and (re)starting $SERVICE..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"
sudo systemctl restart "$SERVICE"
sleep 2

log "Status:"
systemctl is-active "$SERVICE" || warn "$SERVICE is not active. Check: journalctl -u $SERVICE -n 50 --no-pager"

# Ultraleap's EULA. On Debian the package asked via debconf and ran
# `leapctl eula -y`; pacman has no install-time questions, so ask here.
if have leapctl; then
  if ((ACCEPT_EULA)); then
    accept=y
  elif [[ -t 0 ]]; then
    echo
    echo "Ultraleap's licence (EULA) must be accepted before the service will track."
    echo "Read it with:  leapctl eula"
    read -r -p "Accept it now (runs 'leapctl eula -y')? [y/N] " accept
  else
    accept=n
  fi
  if [[ "$accept" == [yY]* ]]; then
    sleep 3   # the vendor postinst waits for the service to finish starting
    leapctl eula -y || warn "leapctl eula -y failed. Retry once the service is up."
  else
    log "Skipped. Accept later with: leapctl eula -y"
  fi
fi

if have lsusb; then
  lsusb -d f182:0003 || echo "(Leap Motion Controller not detected; plug it in)"
elif grep -qx 'f182' /sys/bus/usb/devices/*/idVendor 2>/dev/null; then
  echo "Leap Motion Controller detected on USB."
else
  echo "(Leap Motion Controller not detected; plug it in)"
fi

cat <<EOF

Done. Confirm the device opened (look for 'LMC detected' and a firmware version):
  journalctl -u $SERVICE -n 20 --no-pager

Next, Python bindings and the live visualizer:
  ./scripts/setup-python.sh
  source .venv/bin/activate && python examples/live_visualizer.py
EOF

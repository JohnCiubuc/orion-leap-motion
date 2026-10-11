#!/usr/bin/env bash
# Downloads and unpacks the archived Ultraleap .debs through the Arch PKGBUILD
# (makepkg -o: download + prepare, no build), then writes a report to
# inspect-report.txt in the repo root:
#   * sha256 of each .deb (to pin in packaging/arch/PKGBUILD)
#   * Debian control fields (Depends etc.) and conffiles
#   * maintainer scripts (postinst etc.), i.e. what pacman will NOT run
#   * systemd units, udev rules, sysusers/tmpfiles the debs ship
#   * shared libraries the binaries need that this system lacks
#
# The download is reused by later `makepkg` / ./install.sh runs.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="$REPO_DIR/packaging/arch"
REPORT="$REPO_DIR/inspect-report.txt"

command -v makepkg >/dev/null || { echo "makepkg not found (sudo pacman -S --needed base-devel)" >&2; exit 1; }

cd "$PKG_DIR"
makepkg -o -f --skipinteg >&2

section() { printf '\n===== %s =====\n' "$*"; }

{
  section "System"
  uname -r
  grep -E '^(NAME|VERSION_ID|BUILD_ID)=' /etc/os-release || true
  echo "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-} DISPLAY=${DISPLAY:-}"
  echo "HYPRLAND_INSTANCE_SIGNATURE=${HYPRLAND_INSTANCE_SIGNATURE:+set}"
  python3 --version 2>&1 || true

  section "sha256 (paste into PKGBUILD sha256sums)"
  sha256sum ./*.deb

  for d in service control-panel; do
    root="$PKG_DIR/src/$d"
    section "$d: control"
    cat "$root/control/control" 2>/dev/null || echo "(none)"
    section "$d: conffiles"
    cat "$root/control/conffiles" 2>/dev/null || echo "(none)"
    for s in preinst postinst prerm postrm triggers; do
      if [[ -f "$root/control/$s" ]]; then
        section "$d: $s"
        cat "$root/control/$s"
      fi
    done
    section "$d: file tree (dirs, depth 4)"
    (cd "$root/data" && find . -maxdepth 4 -type d | sort)
    section "$d: units / udev / sysusers / tmpfiles / desktop / ld.so"
    (cd "$root/data" && find . \( -name '*.service' -o -name '*.socket' -o -name '*.rules' \
        -o -path '*sysusers.d*' -o -path '*tmpfiles.d*' -o -name '*.desktop' -o -path '*ld.so.conf.d*' \) \
        -type f -print -exec sed 's/^/    /' {} \;)
    section "$d: missing shared libraries"
    # ELF files only; report unique "not found" deps. Every directory in the
    # package that holds a .so is on the search path, standing in for any
    # absolute RUNPATH that only resolves once installed.
    libpath="$(cd "$root/data" && find "$PWD" -name '*.so*' -printf '%h\n' | sort -u | paste -sd:)"
    (cd "$root/data" && find . -type f \( -perm -u+x -o -name '*.so*' \) -print0 \
      | while IFS= read -r -d '' f; do
          head -c4 "$f" 2>/dev/null | grep -q $'\x7fELF' || continue
          LD_LIBRARY_PATH="$libpath" ldd "$f" 2>/dev/null | awk -v f="$f" '/not found/ {print $1 "  (needed by " f ")"}'
        done | sort -u) || true
    if [[ -f "$root/data/usr/bin/leapd" ]]; then
      section "$d: leapd dynamic section"
      readelf -d "$root/data/usr/bin/leapd" | grep -E 'NEEDED|RPATH|RUNPATH' || true
      section "$d: where bundled libraries live"
      (cd "$root/data" && find . -name 'lib*realuvc*' -o -name 'libLeapC.so*' | sort)
      ls -l "$root/data/usr/bin/"
    fi
  done
} > "$REPORT"

echo
echo "Report written to: $REPORT"
echo "Share it (or just say it's there) so we can pin checksums and finalize dependencies."

#!/usr/bin/env bash
# Sets up a Python virtualenv in .venv with the LeapC Python bindings built
# against the installed service, plus the examples' requirements.
#
# Arch's system Python is "externally managed" (PEP 668), so everything goes in
# a venv. The bindings ship a precompiled module only for Python 3.8, so
# leapc-cffi is always rebuilt here for whatever Python you have.
#
# Env overrides:
#   PYTHON=python3.12          interpreter to create the venv with
#   LEAPC_BINDINGS_DIR=/path   use an existing checkout of the bindings

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
BINDINGS_REPO="https://github.com/ohora23/leapc-python-bindings.git"
BINDINGS_DIR="${LEAPC_BINDINGS_DIR:-$REPO_DIR/third_party/leapc-python-bindings}"
VENV="$REPO_DIR/.venv"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m==> ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[[ -f /usr/include/LeapC.h ]] \
  || die "/usr/include/LeapC.h not found. Run ./install.sh first."
ls /usr/lib/ultraleap-hand-tracking-service/libLeapC.so* >/dev/null 2>&1 \
  || die "libLeapC.so not found under /usr/lib/ultraleap-hand-tracking-service. Run ./install.sh first."
command -v "$PYTHON" >/dev/null || die "$PYTHON not found (sudo pacman -S python)."
command -v git >/dev/null || die "git not found (sudo pacman -S git)."
command -v cc >/dev/null || die "No C compiler (sudo pacman -S --needed base-devel)."

if [[ ! -d "$BINDINGS_DIR/.git" && ! -d "$BINDINGS_DIR/leapc-cffi" ]]; then
  log "Cloning leapc-python-bindings into ${BINDINGS_DIR#"$REPO_DIR"/}..."
  mkdir -p "$(dirname "$BINDINGS_DIR")"
  git clone --depth 1 "$BINDINGS_REPO" "$BINDINGS_DIR"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  log "Creating virtualenv at .venv ($("$PYTHON" --version))..."
  "$PYTHON" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

log "Installing build tooling and example requirements..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet build cffi
python -m pip install --quiet -r "$REPO_DIR/examples/requirements.txt"

log "Building leapc-cffi against the installed LeapC..."
rm -rf "$BINDINGS_DIR/leapc-cffi/dist"
python -m build --wheel "$BINDINGS_DIR/leapc-cffi"
python -m pip install --quiet --force-reinstall "$BINDINGS_DIR"/leapc-cffi/dist/leapc_cffi-*.whl

log "Installing leapc-python-api (editable)..."
python -m pip install --quiet -e "$BINDINGS_DIR/leapc-python-api"

python - <<'PY'
import leap, leapc_cffi  # noqa: F401
print("leap bindings import OK")
PY

cat <<EOF

Ready. Try:
  source .venv/bin/activate
  python examples/hand_test.py          # terminal output, 15 s
  python examples/live_visualizer.py    # IR feed + skeleton window (q to quit)
EOF

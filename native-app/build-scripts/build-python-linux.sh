#!/usr/bin/env bash
# Build the bundled Python sync binary for Linux (x64).
#
# Requirements (all managed by uv — no system Python needed):
#   uv  https://docs.astral.sh/uv/getting-started/installation/
#
# Run from anywhere in the repo:
#   bash native-app/build-scripts/build-python-linux.sh
#
# Output: native-app/python-bin/sync
#         (electron-builder picks this up via extraResources in package.json)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NATIVE_APP_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$NATIVE_APP_DIR")"

echo "==> Installing PyInstaller into project venv…"
cd "$PROJECT_ROOT"
uv pip install pyinstaller

echo ""
echo "==> Building sync binary…"
cd "$NATIVE_APP_DIR"

uv run pyinstaller sync-runner.spec \
    --distpath python-bin \
    --workpath build/pyinstaller \
    --clean \
    --noconfirm

echo ""
echo "==> Build complete!"
echo "    Binary: $NATIVE_APP_DIR/python-bin/sync"
echo ""
echo "    Next step:  cd native-app && npm run build:linux"

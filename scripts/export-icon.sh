#!/usr/bin/env bash
# Export assets/icon.html to PNG icons: headless Chrome renders a 1024 px master with a
# transparent background, then sips downsamples it (Chrome cannot capture windows that
# small, and downsampling a large master gives cleaner edges at small sizes).
# Usage: scripts/export-icon.sh [light|dark]   (default: light; macOS for sips)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TILE="${1:-light}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[ -x "$CHROME" ] || { echo "set CHROME to a Chrome or Chromium binary" >&2; exit 1; }
command -v sips >/dev/null 2>&1 || { echo "sips (macOS) is required for downsampling" >&2; exit 1; }

MASTER="$ROOT/assets/icon-1024.png"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --default-background-color=00000000 --window-size=1024,1024 \
  --screenshot="$MASTER" "file://$ROOT/assets/icon.html?t=$TILE" >/dev/null 2>&1
echo "wrote assets/icon-1024.png (1024x1024)"

for spec in "512:logo.png" "128:composer-icon.png"; do
  size="${spec%%:*}" name="${spec#*:}"
  sips -z "$size" "$size" "$MASTER" --out "$ROOT/assets/$name" >/dev/null
  echo "wrote assets/$name (${size}x${size})"
done

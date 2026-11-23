#!/usr/bin/env bash
# Download Noto Sans KR (SIL Open Font License 1.1) so figures can render Korean (한글) labels.
# Fonts are not committed (size); the figure style falls back to an installed system font if this is missing.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)/fonts"
mkdir -p "$DIR"
BASE="https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskr"
curl -fsSL -o "$DIR/NotoSansKR-wght.ttf" "$BASE/NotoSansKR%5Bwght%5D.ttf"
curl -fsSL -o "$DIR/OFL.txt" "$BASE/OFL.txt"
echo "downloaded to $DIR"

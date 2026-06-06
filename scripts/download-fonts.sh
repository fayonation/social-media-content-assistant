#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
FONTS_DIR="assets/fonts"
mkdir -p "$FONTS_DIR"

NOTO_SANS_URL="https://github.com/notofonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf"
NOTO_ARABIC_URL="https://github.com/notofonts/noto-fonts/raw/main/hinted/ttf/NotoNaskhArabic/NotoNaskhArabic-Regular.ttf"

if [[ ! -f "$FONTS_DIR/NotoSans.ttf" ]]; then
  echo "Downloading NotoSans.ttf…"
  curl -fsSL -o "$FONTS_DIR/NotoSans.ttf" "$NOTO_SANS_URL"
fi

if [[ ! -f "$FONTS_DIR/NotoNaskhArabic.ttf" ]]; then
  echo "Downloading NotoNaskhArabic.ttf…"
  curl -fsSL -o "$FONTS_DIR/NotoNaskhArabic.ttf" "$NOTO_ARABIC_URL"
fi

echo "Fonts ready in $FONTS_DIR"

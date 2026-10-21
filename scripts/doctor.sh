#!/usr/bin/env bash
# Check what the demo-video pipeline needs on this Mac; print the fix for anything missing.
set -uo pipefail
fail=0
need() { if ! command -v "$1" >/dev/null 2>&1; then echo "MISSING $1 -> $2"; fail=1; fi; }
need ffmpeg  "brew install ffmpeg"
need ffprobe "brew install ffmpeg"
need tmux    "brew install tmux"
need uv      "curl -LsSf https://astral.sh/uv/install.sh | sh"
for f in "/System/Library/Fonts/Supplemental/Arial.ttf" "/System/Library/Fonts/Supplemental/Arial Bold.ttf"; do
  [ -f "$f" ] || { echo "MISSING font $f"; fail=1; }
done
# Read the list first: `grep -q` closing the pipe early fails it under pipefail.
filters="$(ffmpeg -hide_banner -filters 2>/dev/null || true)"
if command -v ffmpeg >/dev/null && ! grep -q " drawtext " <<<"$filters"; then
  echo "MISSING ffmpeg drawtext filter -> brew reinstall ffmpeg (needs libfreetype)"; fail=1
fi
if command -v uv >/dev/null && ! uv run -q --no-project --with playwright python -c \
  "from playwright.sync_api import sync_playwright as p; b=p().start().chromium.launch(); b.close()" >/dev/null 2>&1; then
  echo "MISSING Playwright Chromium -> uv run --no-project --with playwright playwright install chromium"; fail=1
fi
[ $fail = 0 ] && echo "doctor: ok"
exit $fail

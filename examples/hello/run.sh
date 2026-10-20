#!/usr/bin/env bash
# The pipeline's smoke test: record both hello takes and assemble the video, end to end.
#   bash run.sh   -> ~/Movies/demo-video/hello/final/hello.mp4 (+ -script.md, -picture.mp4, -preview.mp4)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export DEMO_VIDEO_SCRIPTS="${DEMO_VIDEO_SCRIPTS:-$HERE/../../scripts}"
PY=(uv run -q --no-project --with playwright python)

bash "$DEMO_VIDEO_SCRIPTS/doctor.sh"
if lsof -nP -iTCP:8795 -sTCP:LISTEN >/dev/null; then echo "port 8795 is in use; stop that server first"; exit 1; fi
bash "$DEMO_VIDEO_SCRIPTS/stage.sh" start hellodemo 7692 "$HERE" '^report done'
python3 -m http.server 8795 --bind 127.0.0.1 --directory "$HERE" >/dev/null 2>&1 & WEB=$!
trap '{ kill $WEB && wait $WEB; } 2>/dev/null || true; bash "$DEMO_VIDEO_SCRIPTS/stage.sh" stop hellodemo' EXIT

(cd "$HERE" && "${PY[@]}" scenes.py)
"${PY[@]}" "$DEMO_VIDEO_SCRIPTS/assemble.py" "$HERE" "$HOME/Movies/demo-video/hello/final/hello.mp4"

#!/usr/bin/env bash
# The terminal stream's stage: a clean tmux session and its web mirror.
#
#   stage.sh start <session> <port> [cwd] [highlight-regex]
#   stage.sh stop  <session>
#
# start refuses a session or port that already exists (it is someone else's take). The
# session runs `bash --norc` with the prompt `$ `, 96x26 (term_mirror's grid): no user
# name, host or paths on camera, and `Take.until_prompt` can see when a command finished.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cmd="${1:-}"; session="${2:-}"
[ -n "$cmd" ] && [ -n "$session" ] || { sed -n 4,6p "$0"; exit 2; }

case "$cmd" in
  start)
    port="${3:?port}"; cwd="${4:-$PWD}"; highlight="${5:-}"
    if tmux has-session -t "$session" 2>/dev/null; then
      echo "tmux session $session exists: stop it first (stage.sh stop $session)"; exit 1; fi
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null; then
      echo "port $port is in use: pick another, or stop what holds it"; exit 1; fi
    tmux new-session -d -s "$session" -x 96 -y 26 -c "$cwd" "env PS1='\$ ' bash --norc"
    args=("$session" "$port"); [ -n "$highlight" ] && args+=("$highlight")
    nohup uv run -q --no-project python "$HERE/term_mirror.py" "${args[@]}" \
      >"${TMPDIR:-/tmp}/demo-mirror-$session.log" 2>&1 &
    for _ in $(seq 30); do  # a cold `uv run` resolves Python first
      curl -fsS "http://127.0.0.1:$port/" >/dev/null 2>&1 && { echo "stage $session up: http://127.0.0.1:$port"; exit 0; }
      sleep 1
    done
    # Leave nothing behind, or every retry is refused as "session exists" / "port in use".
    pkill -f "term_mirror.py $session " 2>/dev/null || true
    tmux kill-session -t "$session" 2>/dev/null || true
    echo "the mirror did not come up; see ${TMPDIR:-/tmp}/demo-mirror-$session.log"; exit 1 ;;
  stop)
    pkill -f "term_mirror.py $session " 2>/dev/null || true
    tmux kill-session -t "$session" 2>/dev/null || true
    echo "stage $session down" ;;
  *) sed -n 4,6p "$0"; exit 2 ;;
esac

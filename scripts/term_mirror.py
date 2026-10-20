"""Serve a tmux pane as a web page, for the recorder's terminal stream.

    python term_mirror.py <session> [port] [highlight-regex]   # default port 7682, localhost only

`highlight-regex` (optional): lines it matches (ANSI stripped, matched at line start) get a
bright band, for the lines a viewer must read.

`/` is a page that polls `/screen` every 200 ms and draws the pane (ANSI colours kept) in a
fixed monospace grid. Replaces ttyd: its xterm.js canvas stopped repainting in headless
Chromium after a `clear`, which recorded minutes of blank terminal.
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COLS, ROWS = 96, 26  # fits 1280x720 at 20 px Menlo with margins

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Demo terminal</title>
<style>
html,body{margin:0;height:100%;background:#0b0f17;}
#s{margin:18px 24px;font:20px/1.32 Menlo,monospace;color:#e6edf3;white-space:pre;}
</style></head><body><div id="s"></div><script>
async function tick(){
  try { const r = await fetch('/screen'); document.getElementById('s').innerHTML = await r.text(); }
  catch (e) {}
  setTimeout(tick, 200);
}
tick();
</script></body></html>"""

# The 16 ANSI colours, tuned for the dark background.
PALETTE = ["#0b0f17", "#ff6b6b", "#69db7c", "#ffd43b", "#74c0fc", "#da77f2", "#66d9e8",
           "#e6edf3", "#5c6370", "#ff8787", "#8ce99a", "#ffe066", "#a5d8ff", "#e599f7",
           "#99e9f2", "#ffffff"]
SGR = re.compile(r"\x1b\[([0-9;]*)m")


def to_html(text: str) -> str:
    """ANSI SGR colour/bold to spans; everything else escaped."""
    out, open_span, pos = [], False, 0
    for m in SGR.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        pos = m.end()
        codes = [int(c) for c in m.group(1).split(";") if c.isdigit()] or [0]
        style = []
        for c in codes:
            if 30 <= c <= 37:
                style.append(f"color:{PALETTE[c - 30]}")
            elif 90 <= c <= 97:
                style.append(f"color:{PALETTE[c - 82]}")
            elif c == 1:
                style.append("font-weight:bold")
        if open_span:
            out.append("</span>")
            open_span = False
        if style:
            out.append(f'<span style="{";".join(style)}">')
            open_span = True
    out.append(html.escape(text[pos:]))
    if open_span:
        out.append("</span>")
    return "".join(out)


TMUX = ""
KEY: re.Pattern | None = None  # the lines a viewer must read


def highlight(line: str) -> str:
    html_line = to_html(line)
    if KEY and KEY.match(SGR.sub("", line)):
        return ('<span style="background:#173a5e;color:#ffe066;font-weight:bold;'
                'display:inline-block;width:100%">' + html_line + "</span>")
    return html_line


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/screen":
            pane = subprocess.run(["tmux", "capture-pane", "-t", TMUX, "-p", "-e"],
                                  capture_output=True, text=True).stdout
            body = "\n".join(highlight(line) for line in pane.rstrip("\n").split("\n")).encode()
        else:
            body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: term_mirror.py <tmux-session> [port] [highlight-regex]")
    TMUX = sys.argv[1]
    KEY = re.compile(sys.argv[3]) if len(sys.argv) > 3 else None
    subprocess.run(["tmux", "set", "-t", TMUX, "window-size", "manual"], check=True)
    subprocess.run(["tmux", "resize-window", "-t", TMUX, "-x", str(COLS), "-y", str(ROWS)],
                   check=True)
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 7682
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()

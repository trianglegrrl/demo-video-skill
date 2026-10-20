"""The hello demo: a terminal and a tiny local web app, two scenes. The smoke test for the
pipeline (run.sh records and assembles it end to end in about three minutes)."""
from pathlib import Path

TITLE = "Hello, demo pipeline"
DESKTOP_LABEL = "Demo desktop"
OUT = Path.home() / "Movies/demo-video/hello"          # takes land in OUT/<take>/
PROFILES = Path.home() / ".cache/demo-video/hello/profiles"  # this demo's own browser profiles
TMUX = "hellodemo"                                     # the terminal stream's tmux session

# Stream order sets the background window slots (top-left, top-right, bottom-left, ...).
STREAMS = {
    "term": {"title": "Terminal — hello", "url": "http://127.0.0.1:7692", "terminal": True},
    "app": {"title": "Hello app", "url": "http://127.0.0.1:8795/app.html"},
}

# One entry per take, in video order; one line per clip in that take (None = no line).
SCENES = [
    {"take": "s1-terminal",
     "lines": ["Here's the terminal. One command kicks off a report.",
               "Half a minute later it's done, and the wait is cut out of the video."]},
    {"take": "s2-app",
     "speeds": {"the report in the app": 1.0},
     "lines": ["And here's the same report in the web app. One click,",
               "and the answer is on the page."]},
]

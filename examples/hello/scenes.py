"""Record the hello demo's takes.

    uv run --no-project --with playwright python scenes.py [s1 s2]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# The skill's scripts/: set DEMO_VIDEO_SCRIPTS when this folder is copied elsewhere.
sys.path.insert(0, os.environ.get("DEMO_VIDEO_SCRIPTS",
                                  str(Path(__file__).resolve().parents[2] / "scripts")))
import human  # noqa: E402
from recorder import Take, load_demo  # noqa: E402

DEMO = load_demo(__file__)


def s1() -> None:
    with Take("s1-terminal", DEMO) as t:
        with t.clip("one command starts the report", "term"):
            time.sleep(0.8)
            t.type("echo starting report; sleep 25; echo 'report done: 3 failed'")
            time.sleep(1.5)
        t.until(r"^report done", 60)  # off camera, between clips: the 25 s wait is cut
        with t.clip("the report is done", "term"):
            time.sleep(3.0)


def s2() -> None:
    with Take("s2-app", DEMO) as t:
        app = t.pages["app"]
        human.cursor(app)  # headless Chromium draws no pointer
        with t.clip("one click runs it", "app"):
            time.sleep(0.8)
            human.click(app, app.get_by_role("button", name="Run report"))
            time.sleep(1.0)
        app.get_by_text("3 builds failed").wait_for(timeout=30000)  # off camera
        with t.clip("the report in the app", "app"):
            human.move(app, 640, 400)
            time.sleep(3.0)


SCENES = {"s1": s1, "s2": s2}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(SCENES):
        SCENES[name]()

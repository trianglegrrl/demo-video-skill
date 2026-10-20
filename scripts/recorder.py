"""Record a demo take headless: one browser page per stream, one clock, one event log.

A demo is a folder with a `demo.py` (its streams, title and narration, see
examples/hello/demo.py) and scene scripts that open `Take`s:

    from recorder import Take, load_demo
    demo = load_demo(__file__)
    with Take("s1-intro", demo) as t:
        with t.clip("what this shot shows", "term"):
            t.type("ls -la")

Each stream is a persistent Chromium profile (sign-ins survive between takes), recorded by
Playwright to its own WebM. Nothing needs the Mac's screen: it may be locked. Every take
writes `<out>/<take>/events.jsonl` with `start` (each stream's video start on the take
clock) and `clip`/`clipend` (a stretch the cut KEEPS, and which window is in front).
Everything outside a clip is dropped by cut.py, so waits happen off camera.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Callable, Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

# A 1280x720 layout recorded at 1.5x device scale: cut.py upscales to 1080p and text still
# reads on a laptop. Playwright records at CSS-pixel size; the scale only sharpens it.
SIZE = {"width": 1280, "height": 720}
SCALE = 1.5
# Some web apps (Microsoft Teams) refuse a browser that calls itself headless.
CHROME_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def load_demo(anchor: str | Path) -> ModuleType:
    """Import the `demo.py` next to *anchor* (a scene file's __file__, or the demo folder)."""
    path = Path(anchor).resolve()
    path = path / "demo.py" if path.is_dir() else path.parent / "demo.py"
    if str(path.parent) not in sys.path:  # demo.py may import its own helpers
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("demo", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"no demo.py at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = Path(module.OUT).expanduser()
    return module


def tmux(*args: str) -> str:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=True).stdout


class Take:
    def __init__(self, name: str, demo: ModuleType, streams: tuple[str, ...] | None = None):
        self.name, self.demo = name, demo
        # Recorded into <take>.partial, swapped in only when the take ends cleanly, so a
        # failed re-record leaves the last good take in place.
        self.final, self.dir = demo.OUT / name, demo.OUT / f"{name}.partial"
        self.streams = streams or tuple(demo.STREAMS)
        self.pages: dict[str, Page] = {}
        self._ctx: dict[str, BrowserContext] = {}
        self._log = None
        self._t0 = 0.0

    # --- clock and log -------------------------------------------------------------------
    def now(self) -> float:
        return round(time.monotonic() - self._t0, 3)

    def event(self, kind: str, **fields) -> None:
        rec = {"t": self.now(), "kind": kind, **fields}
        self._log.write(json.dumps(rec) + "\n")
        self._log.flush()
        print(f"[{rec['t']:8.1f}] {kind} {fields}", flush=True)

    @contextmanager
    def clip(self, label: str, focus: str) -> Iterator[None]:
        """A stretch the cut KEEPS, with *focus* as the front window. One clip = one shot =
        one narration line in demo.SCENES."""
        if focus not in self.streams:
            raise ValueError(f"clip focus {focus!r} is not a stream of this take")
        self.event("clip", label=label, focus=focus)
        try:
            yield
        finally:
            self.event("clipend", label=label)

    # --- terminal (a tmux session, shown through term_mirror.py) ---------------------------
    @property
    def session(self) -> str:
        return self.demo.TMUX

    def type(self, command: str, cps: float = 28.0) -> None:
        """Type *command* into the demo terminal at a human pace, then Enter."""
        for ch in command:
            # tmux reads a lone ";" argument as its own command separator.
            tmux("send-keys", "-t", self.session, "-l", "\\;" if ch == ";" else ch)
            time.sleep(1.0 / cps)
        time.sleep(0.4)
        tmux("send-keys", "-t", self.session, "Enter")

    def screen(self) -> str:
        return tmux("capture-pane", "-t", self.session, "-p", "-S", "-2000")

    def until(self, pattern: str, timeout: float, poll: float = 2.0) -> re.Match:
        """Block until *pattern* shows in the terminal; fail loudly on timeout."""
        rx, end = re.compile(pattern, re.M), time.monotonic() + timeout
        while time.monotonic() < end:
            m = rx.search(self.screen())
            if m:
                return m
            time.sleep(poll)
        raise TimeoutError(f"terminal never showed /{pattern}/ within {timeout:.0f}s")

    def until_prompt(self, command: str, timeout: float) -> str:
        """Block until *command* (as typed) has finished: a bare "$" prompt line follows it.
        Returns its output. Wrapped commands: matched on the first 40 characters."""
        head, end = command[:40], time.monotonic() + timeout
        while time.monotonic() < end:
            text = self.screen()
            at = text.rfind(head)
            if at != -1:
                after = text[at:].splitlines()[1:]
                if any(line.strip() == "$" for line in after):
                    return "\n".join(after)
            time.sleep(1.0)
        raise TimeoutError(f"`{head}...` did not finish within {timeout:.0f}s")

    def until_true(self, check: Callable[[], bool], timeout: float, poll: float = 5.0,
                   what: str = "condition") -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if check():
                return
            time.sleep(poll)
        raise TimeoutError(f"{what} not met within {timeout:.0f}s")

    def clear_terminal(self) -> None:
        """Clear the pane AND its scrollback: `until` reads the scrollback, so an earlier
        run's lines would otherwise satisfy this take's waits."""
        tmux("send-keys", "-t", self.session, "clear", "Enter")
        time.sleep(0.6)
        tmux("clear-history", "-t", self.session)

    # --- lifecycle ---------------------------------------------------------------------------
    def __enter__(self) -> "Take":
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self._log = open(self.dir / "events.jsonl", "w")
        self._pw = sync_playwright().start()
        self._t0 = time.monotonic()
        try:
            self._open()
        except BaseException:
            self._close()
            raise
        self.event("ready")
        return self

    def _open(self) -> None:
        for s in self.streams:
            self._ctx[s] = open_stream(self._pw, self.demo, s, video_dir=self.dir / s)
            self.event("start", stream=s)
            ctx = self._ctx[s]
            self.pages[s] = ctx.pages[0] if ctx.pages else ctx.new_page()
        for s in self.streams:
            spec = self.demo.STREAMS[s]
            if spec.get("url"):
                # "load", not "networkidle": the terminal mirror polls forever, so the
                # network never idles. A page that loads late waits in its `prepare`.
                self.pages[s].goto(spec["url"], wait_until="load")
                self.pages[s].wait_for_timeout(1500)
            if spec.get("prepare"):
                spec["prepare"](self.pages[s])  # sign in, open the right view: off camera
        if any(spec.get("terminal") for spec in self.demo.STREAMS.values()):
            self.clear_terminal()

    def _close(self) -> None:
        for s, ctx in self._ctx.items():
            video = self.pages[s].video if s in self.pages else None
            ctx.close()  # writes the video
            if video:
                Path(video.path()).rename(self.dir / f"{s}.webm")
            shutil.rmtree(self.dir / s, ignore_errors=True)
        self._pw.stop()
        self._log.close()

    def __exit__(self, exc_type, *exc) -> None:
        self.event("end")
        self._close()
        if exc_type is not None:
            print(f"take {self.name} failed: kept the last good take; this one is in {self.dir}")
            return
        if self.final.exists():
            shutil.rmtree(self.final)
        self.dir.rename(self.final)


def open_stream(pw, demo: ModuleType, stream: str, video_dir: Path | None = None,
                headless: bool = True) -> BrowserContext:
    opts = dict(viewport=SIZE, headless=headless, color_scheme="dark", device_scale_factor=SCALE)
    if video_dir is not None:
        opts.update(record_video_dir=str(video_dir), record_video_size=SIZE)
    if demo.STREAMS[stream].get("desktop_ua"):
        opts["user_agent"] = CHROME_UA
    profile = Path(demo.PROFILES).expanduser() / f"pw-{stream}"
    return pw.chromium.launch_persistent_context(str(profile), **opts)


def signin(demo: ModuleType, stream: str, url: str) -> None:
    """Headed, once per stream: sign in by hand (MFA and all); the profile keeps it for the
    headless takes. Close the window when done."""
    with sync_playwright() as pw:
        ctx = open_stream(pw, demo, stream, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url)
        print("Sign in in the window, then close it.")
        page.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "signin":
        raise SystemExit("usage: recorder.py signin <demo-folder> <stream>")
    d, stream = load_demo(sys.argv[2]), sys.argv[3]
    if stream not in d.STREAMS:
        raise SystemExit(f"no stream {stream!r} in demo.py (streams: {', '.join(d.STREAMS)})")
    url = d.STREAMS[stream].get("signin_url") or d.STREAMS[stream].get("url")
    if not url:
        raise SystemExit(f"stream {stream!r} has no url or signin_url: it signs in through "
                         "its `prepare` on every take, so there is nothing to do here")
    signin(d, stream, url)

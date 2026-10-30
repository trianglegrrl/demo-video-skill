"""Tight cut of one take on one desktop: keep only its clips, every window live on a wallpaper.

    python cut.py <demo-folder> <take>      # preview one take: <out>/<take>/<take>-desktop.mp4

Each `clip`..`clipend` becomes one shot. All of the take's streams play in their own window
at the same take-clock moment; the clip's `focus` window is large and in front, the others
sit behind it, smaller and dimmed, so switching reads as bringing a window forward on one
desktop. A shot that starts JUMP_TAG seconds or more after the previous one ended carries a
"+40 s" / "+N min" tag for its first second and a half: the waits are cut, not hidden.
assemble.py renders every shot through `render` and voices it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from recorder import load_demo

W, H, FPS = 1920, 1080, 30
BAR = 30  # menu bar height
TITLE = 30  # window title bar height
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
RENDER_BASE_S, RENDER_PER_S = 60, 20  # render timeout: base + per second of shot
JUMP_TAG = 20.0  # seconds of cut wait that earn a tag ("+40 s", "+N min")
TAG_S = 1.6  # how long the tag stays on screen
# The front window, and the background slots in stream order (x, y, width): 16:9 content
# plus a title bar. Four slots: a demo has at most four streams.
FRONT = (176, 76, 1568)
SLOTS = [(28, 44, 760), (1132, 44, 760), (28, 600, 760), (1132, 600, 760)]


@dataclass(frozen=True)
class Shot:
    label: str
    focus: str
    t0: float
    t1: float
    gap: float  # seconds cut since the previous shot
    speed: float = 1.0

    @property
    def length(self) -> float:
        return (self.t1 - self.t0) / self.speed


def events_of(take: Path) -> list[dict]:
    return [json.loads(x) for x in (take / "events.jsonl").read_text().splitlines()]


def shots(events: list[dict], speeds: dict[str, float] | None = None) -> list[Shot]:
    out, open_clip, prev_end = [], None, None
    for e in events:
        if e["kind"] == "clip":
            open_clip = e
        elif e["kind"] == "clipend" and open_clip:
            gap = 0.0 if prev_end is None else open_clip["t"] - prev_end
            out.append(Shot(open_clip["label"], open_clip["focus"], open_clip["t"], e["t"], gap,
                            (speeds or {}).get(open_clip["label"], 1.0)))
            prev_end, open_clip = e["t"], None
    return out


def jump(gap: float) -> str:
    """The tag on a shot that follows a cut wait: "+40 s" under 90 s, else "+N min"."""
    return f"+{round(gap)} s" if gap < 90 else f"+{round(gap / 60)} min"


def _text(value: str) -> str:
    """ffmpeg's filter syntax reads ":" as an option separator and "'" as quoting."""
    if any(c in value for c in ":'\\%"):
        raise ValueError(f"no : ' \\ or % in on-screen text: {value!r}")
    return value


def wallpaper(demo: ModuleType, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"gradients=s={W}x{H}:c0=0x0f1a33:c1=0x2a1745:x0=0:y0=0:x1={W}:y1={H}:d=1",
                    "-frames:v", "1", "-vf",
                    f"drawbox=x=0:y=0:w={W}:h={BAR}:color=black@0.55:t=fill,"
                    f"drawtext=fontfile='{FONT_B}':text='{_text(demo.DESKTOP_LABEL)}':"
                    f"fontcolor=white@0.9:fontsize=17:x=18:y=7", str(dst)], check=True)


def _window(idx: int, title: str, width: int, front: bool, speed: float = 1.0) -> str:
    """Filter chain: stream -> scaled content under a title bar, dimmed when behind."""
    h = width * 9 // 32 * 2
    dim = "" if front else ",eq=brightness=-0.10:saturation=0.8"
    title_size = 17 if front else 13
    return (f"[{idx}:v]setpts=(PTS-STARTPTS)/{speed},scale={width}:{h}{dim},"
            f"pad={width}:{h + TITLE}:0:{TITLE}:color=0x2b2f36,"
            f"drawbox=x=0:y=0:w={width}:h={TITLE}:color=0x2b2f36:t=fill,"
            f"drawtext=fontfile='{FONT}':text='●':fontcolor=0xff5f57:fontsize=16:x=12:y=7,"
            f"drawtext=fontfile='{FONT}':text='●':fontcolor=0xfebc2e:fontsize=16:x=32:y=7,"
            f"drawtext=fontfile='{FONT}':text='●':fontcolor=0x28c840:fontsize=16:x=52:y=7,"
            f"drawtext=fontfile='{FONT}':text='{_text(title)}':fontcolor=white@0.85:"
            f"fontsize={title_size}:x=(w-tw)/2:y=({TITLE}-th)/2,"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.12:t=1[w{idx}]")


def duration(path: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                                check=True).stdout)


def render(demo: ModuleType, take: Path, shot: Shot, starts: dict[str, float], bg: Path,
           dst: Path) -> None:
    streams = [s for s in demo.STREAMS if s in starts]
    slot = {s: SLOTS[i] for i, s in enumerate(demo.STREAMS)}
    order = [s for s in streams if s != shot.focus] + [shot.focus]  # back to front
    args = ["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(FPS),
            "-t", f"{shot.length:.3f}", "-i", str(bg)]
    for s in order:
        args += ["-ss", f"{max(shot.t0 - starts[s], 0):.3f}", "-t", f"{shot.t1 - shot.t0:.3f}",
                 "-i", str(take / f"{s}.webm")]
    chains, last = [], "0:v"
    for i, s in enumerate(order, start=1):
        front = s == shot.focus
        x, y, width = FRONT if front else slot[s]
        chains.append(_window(i, demo.STREAMS[s]["title"], width, front, shot.speed))
        if front:  # a soft shadow under the front window
            chains.append(f"[{last}]drawbox=x={x + 10}:y={y + 14}:w={width}:"
                          f"h={width * 9 // 32 * 2 + TITLE}:color=black@0.45:t=fill[sh]")
            last = "sh"
        chains.append(f"[{last}][w{i}]overlay={x}:{y}:shortest=1[o{i}]")
        last = f"o{i}"
    tail = f"[{last}]fps={FPS},format=yuv420p"
    if shot.gap >= JUMP_TAG:
        tail += (f",drawtext=fontfile='{FONT_B}':text='{jump(shot.gap)}':fontcolor=white:fontsize=30:"
                 f"box=1:boxcolor=0x1c7ed6@0.85:boxborderw=14:x=w-tw-40:y=50:"
                 f"enable='lt(t,{TAG_S})'")
    chains.append(tail + "[v]")
    # -t on the OUTPUT too: overlay's shortest=1 alone once let a 5 s shot run 348 s.
    args += ["-filter_complex", ";".join(chains), "-map", "[v]", "-t", f"{shot.length:.3f}",
             "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(dst)]
    # A runaway render does not end on its own (seen: 22 min); fail it loudly instead.
    subprocess.run(args, check=True, timeout=RENDER_BASE_S + RENDER_PER_S * shot.length)
    got = duration(dst)
    if abs(got - shot.length) > 0.5:
        raise RuntimeError(f"shot {shot.label!r} rendered {got:.1f}s, expected {shot.length:.1f}s")


def main(demo: ModuleType, take: Path) -> None:
    events = events_of(take)
    starts = {e["stream"]: e["t"] for e in events if e["kind"] == "start"}
    speeds = next((sc.get("speeds") for sc in getattr(demo, "SCENES", [])
                   if sc["take"] == take.name), None)
    cut = shots(events, speeds)
    if not cut:
        raise SystemExit(f"{take}: no clips in this take")
    cues, at = [f"# {take.name}: desktop cut", "", "| at | front window | shot |",
                "|---|---|---|"], 0.0
    with tempfile.TemporaryDirectory() as tmp:
        bg = Path(tmp) / "bg.png"
        wallpaper(demo, bg)
        parts = []
        for i, s in enumerate(cut):
            part = Path(tmp) / f"{i:03d}.mp4"
            render(demo, take, s, starts, bg, part)
            parts.append(part)
            cues.append(f"| {int(at // 60)}:{at % 60:04.1f} | {s.focus} | {s.label} |")
            at += s.length
        listing = Path(tmp) / "parts.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        out = take / f"{take.name}-desktop.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-c", "copy", str(out)], check=True)
    cues.insert(2, f"Length {at:.1f} s, {len(cut)} shots.")
    (take / f"{take.name}-desktop-cues.md").write_text("\n".join(cues) + "\n")
    print(f"{out}  ({at:.1f} s, {len(cut)} shots)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: cut.py <demo-folder> <take>")
    d = load_demo(sys.argv[1])
    main(d, d.OUT / sys.argv[2])

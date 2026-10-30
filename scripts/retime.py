"""Fit a shot's footage to its line, so the picture doesn't play on after the voice has stopped.

A shot should run for its speech plus about a second, the pause of a person changing gears. What
it has beyond that is dead air, taken up in this order: cut what is still, then speed up the rest
(up to a cap). Whatever is left is reported, for the line to grow: fit.py turns it into a word
count, and a person's words fill it. Nothing here writes narration.

Finding "still" needs care. Whole-frame measures such as ffmpeg's freezedetect can't tell a
cursor crossing the screen, a click or a new line of text from an idle page: each changes too
few pixels, so they would be cut. `stills` asks WHERE pixels changed instead. A drifting cursor
keeps its changes inside one small box; a move or new text spreads them out.
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType

from cut import JUMP_TAG, TAG_S, Shot, duration, render

LEAD, TAIL = 0.25, 0.45  # air before a line starts, and after it ends, inside its shot
PAUSE = 1.0  # seconds from the end of one line to the start of the next
SILENT_TARGET = 3.0  # how long a shot with no line holds; pass no --fit to keep it longer
MAX_SPEED = 1.5
SLOP = 0.2  # dead air not worth touching
BEAT = 0.4  # what a cut still keeps, so the picture settles before it jumps
END_HOLD = 1.0  # what is never cut from a shot's end, so the payoff is seen
MIN_CUT = 0.2  # a shorter cut costs a visible jump for nothing
# Found by recording human.idle, human.click and human.move and comparing with where they ran.
SCAN_W, SCAN_H, SCAN_RATE = 640, 360, 10
CHANGED = 24  # 0-255: a pixel moved this much (lower catches video compression noise)
DRIFT_BOX = 24  # scan pixels: the box a drifting cursor stays inside (human.IDLE_RADIUS_PX, plus the cursor)
MIN_STILL = 0.5


@dataclass(frozen=True)
class Pacing:
    pause: float = PAUSE
    max_speed: float = MAX_SPEED

    def __post_init__(self) -> None:
        if self.pause < LEAD + TAIL:
            raise SystemExit(f"--pause must be at least {LEAD + TAIL:.2f} s: the air every line has")
        if self.max_speed < 1.0:
            raise SystemExit("--max-speed must be at least 1: fitting never slows footage down")


@dataclass(frozen=True)
class Fit:
    pieces: tuple[Shot, ...]
    dead: float  # seconds over the target before fitting (negative: it has room to spare)
    cut: float  # seconds of footage cut
    speed: float
    left: float  # seconds still over the target: for the line to grow


def target_for(speech: float | None, pause: float) -> float:
    return SILENT_TARGET if speech is None else speech + pause


def _cuts(shot: Shot, stills: list[tuple[float, float]], need: float) -> list[tuple[float, float]]:
    """Up to *need* seconds of footage out of the longest stills, each keeping its beat and
    the shot keeping its last END_HOLD, and a tagged shot its tag's time on screen."""
    tag_ends = shot.t0 + TAG_S * shot.speed if shot.gap >= JUMP_TAG else shot.t0
    room = []
    for a, b in stills:
        start, end = max(a, shot.t0), min(b, shot.t1)
        lo, hi = max(start + BEAT, tag_ends), min(end, shot.t1 - END_HOLD)
        if hi - lo >= MIN_CUT:
            room.append((hi - lo, lo))
    cuts = []
    for size, lo in sorted(room, reverse=True):
        if need < MIN_CUT:
            break
        take = min(size, need)
        cuts.append((lo, lo + take))
        need -= take
    return sorted(cuts)


def _kept(shot: Shot, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    edges = [shot.t0, *(edge for cut in cuts for edge in cut), shot.t1]
    return list(zip(edges[::2], edges[1::2]))


def plan(shot: Shot, stills: list[tuple[float, float]], target: float,
         max_speed: float = MAX_SPEED) -> Fit:
    """The shot as the pieces to play. *stills* are on the take clock, as the shot's t0 and t1 are.
    The speed an author gave the shot is a floor: fitting only ever speeds up from there."""
    dead = shot.length - target
    if dead <= SLOP:
        return Fit((shot,), dead, 0.0, shot.speed, 0.0)
    cuts = _cuts(shot, stills, dead * shot.speed)
    spans = _kept(shot, cuts)
    footage = sum(b - a for a, b in spans)
    over = footage / shot.speed - target
    speed = shot.speed if over <= SLOP else min(footage / target, max(shot.speed, max_speed))
    speed = max(speed, shot.speed)
    pieces = tuple(replace(shot, t0=a, t1=b, gap=shot.gap if i == 0 else 0.0, speed=speed)
                   for i, (a, b) in enumerate(spans))
    return Fit(pieces, dead, sum(b - a for a, b in cuts), speed, max(0.0, footage / speed - target))


def _box(mask: bytes) -> tuple[int, int, int, int] | None:
    """The bounding box of a changed-pixel mask, or None if nothing changed."""
    first = mask.find(255)
    if first < 0:
        return None
    top, bottom = first // SCAN_W, mask.rfind(255) // SCAN_W
    rows = [mask[y * SCAN_W:(y + 1) * SCAN_W] for y in range(top, bottom + 1)]
    return (min(r.find(255) for r in rows if 255 in r), top,
            max(r.rfind(255) for r in rows), bottom)


def _grow(acc: tuple | None, box: tuple | None) -> tuple | None:
    if acc is None or box is None:
        return acc or box
    return (min(acc[0], box[0]), min(acc[1], box[1]), max(acc[2], box[2]), max(acc[3], box[3]))


def stills(video: Path, start: float, seconds: float) -> list[tuple[float, float]]:
    """The stretches of *video* from *start* for *seconds* in which only something cursor-sized
    changed, in seconds from *start*. A compression keyframe (every 5.12 s from Chromium's
    recorder) ends one and starts the next, which costs at most one extra BEAT each."""
    scan = (f"fps={SCAN_RATE},scale={SCAN_W}:{SCAN_H}:flags=area,format=gray,"
            f"tblend=all_mode=difference,lut=y='if(gte(val,{CHANGED}),255,0)'")
    found, begun, acc, now = [], 0.0, None, 0.0
    size = SCAN_W * SCAN_H
    with subprocess.Popen(["ffmpeg", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}",
                           "-i", str(video), "-vf", scan, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                          stdout=subprocess.PIPE) as scanner:
        while len(mask := scanner.stdout.read(size)) == size:
            now += 1 / SCAN_RATE
            grown = _grow(acc, _box(mask))
            if grown and (grown[2] - grown[0] > DRIFT_BOX or grown[3] - grown[1] > DRIFT_BOX):
                if now - begun >= MIN_STILL:
                    found.append((begun, now))
                begun, acc = now, None
            else:
                acc = grown
    if scanner.returncode != 0:
        raise RuntimeError(f"ffmpeg could not scan {video} for still stretches")
    if now - begun >= MIN_STILL:
        found.append((begun, now))
    return found


def fit_shot(take: Path, shot: Shot, starts: dict[str, float], speech: float | None,
             pacing: Pacing) -> Fit:
    """Plan one recorded shot, scanning its front window only if it has dead air to lose. Only
    the front window: what happens in a dimmed window behind it can be cut."""
    target = target_for(speech, pacing.pause)
    if shot.length - target <= SLOP:
        return plan(shot, [], target, pacing.max_speed)
    offset = shot.t0 - starts[shot.focus]
    found = stills(take / f"{shot.focus}.webm", max(offset, 0), shot.t1 - shot.t0)
    return plan(shot, [(a + shot.t0, b + shot.t0) for a, b in found], target, pacing.max_speed)


def render_pieces(demo: ModuleType, take: Path, pieces: tuple[Shot, ...], starts: dict[str, float],
                  bg: Path, dst: Path) -> None:
    """Render a fitted shot through cut.render, one piece at a time, joined."""
    if len(pieces) == 1:
        render(demo, take, pieces[0], starts, bg, dst)
        return
    with tempfile.TemporaryDirectory() as tmp:
        parts = [Path(tmp) / f"{i:03d}.mp4" for i in range(len(pieces))]
        for piece, part in zip(pieces, parts):
            render(demo, take, piece, starts, bg, part)
        listing = Path(tmp) / "parts.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-c", "copy", str(dst)], check=True)
    want = sum(p.length for p in pieces)
    if abs(duration(dst) - want) > 0.5:
        raise RuntimeError(f"fitted shot {pieces[0].label!r} rendered {duration(dst):.1f}s, expected {want:.1f}s")

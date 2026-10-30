"""Measure the dead air: how long each shot's picture plays on after its line has stopped.

    python fit.py <demo-folder> [voice] [--pause S] [--max-speed X]

Voices the lines (cached, so this is the same audio assemble.py will use, and an ElevenLabs voice
bills only lines it hasn't voiced before) and changes no footage or lines.
For each shot it shows the footage, the speech, the dead air, what `assemble.py --fit` would do
about it, and what the picture can't absorb, as a count of words to add. See retime.py.
"""
from __future__ import annotations

import argparse
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import retime
from assemble import check, voice_scenes
from cut import Shot, events_of, shots
from recorder import load_demo
from tts import choose, spoken

FREEZE_FLAG = 0.3  # a held last frame shorter than this reads as a pause


@dataclass(frozen=True)
class Row:
    take: str
    index: int
    shot: Shot
    line: str | None
    speech: float | None
    fit: retime.Fit


def words_to_add(seconds: float, words_per_second: float) -> int:
    return math.ceil(seconds * words_per_second)


def pace(rows: list[Row]) -> float:
    """This voice's words per second, measured from its own lines."""
    spoken_rows = [r for r in rows if r.speech]
    seconds = sum(r.speech for r in spoken_rows)
    return sum(len(spoken(r.line).split()) for r in spoken_rows) / seconds if seconds else 0.0


def _row_text(row: Row, words_per_second: float) -> str:
    fit, speech = row.fit, f"{row.speech:5.1f}" if row.speech else "    -"
    head = f"{row.take} #{row.index}  footage {row.shot.length:5.1f}  speech {speech}  dead {max(fit.dead, 0):5.1f}"
    if fit.dead <= retime.SLOP:
        action = "ok"
    else:
        action = f"cut {fit.cut:.1f}, x{fit.speed:.2f}"
        if fit.left > retime.SLOP:
            action += (f", {fit.left:.1f} s left: add about {words_to_add(fit.left, words_per_second)} words"
                       if row.speech else f", {fit.left:.1f} s over the silent hold")
        if row.speech:
            action += f" (words alone: {words_to_add(fit.dead, words_per_second)})"
    played = sum(p.length for p in fit.pieces)
    frozen = retime.LEAD + (row.speech or 0.0) + retime.TAIL - played if row.speech else 0.0
    if frozen > FREEZE_FLAG:
        action = f"freezes the last frame {frozen:.1f} s: shorten the line or record a longer hold"
    return f"{head}  {action}"


def report(rows: list[Row]) -> str:
    words_per_second = pace(rows)
    before = sum(r.shot.length for r in rows)
    after = sum(max(sum(p.length for p in r.fit.pieces),
                    retime.LEAD + r.speech + retime.TAIL if r.speech else 0.0) for r in rows)
    worst = max((r.fit.dead for r in rows), default=0.0)
    return "\n".join([*(_row_text(r, words_per_second) for r in rows), "",
                      f"This voice reads {words_per_second:.1f} words a second.",
                      f"Footage {before:.1f} s, fitted {after:.1f} s. Most dead air in one shot: {max(worst, 0):.1f} s."])


def measure(demo: ModuleType, voice: str, options: dict, pacing: retime.Pacing, tmp: Path) -> list[Row]:
    check(demo)
    voiced = voice_scenes(demo.SCENES, voice, tmp, options)
    rows = []
    for s, scene in enumerate(demo.SCENES):
        take = demo.OUT / scene["take"]
        events = events_of(take)
        starts = {e["stream"]: e["t"] for e in events if e["kind"] == "start"}
        for i, (shot, line) in enumerate(zip(shots(events, scene.get("speeds")), scene["lines"])):
            speech = voiced[(s, i)][1] if line else None
            rows.append(Row(scene["take"], i, shot, line, speech,
                            retime.fit_shot(take, shot, starts, speech, pacing)))
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Measure each shot's dead air. Voices uncached lines, which an ElevenLabs voice bills.")
    parser.add_argument("folder")
    parser.add_argument("voice", nargs="?")
    parser.add_argument("--pause", type=float, default=retime.PAUSE)
    parser.add_argument("--max-speed", type=float, default=retime.MAX_SPEED)
    args = parser.parse_args()
    d = load_demo(args.folder)
    chosen, chosen_options = choose(args.voice, d)
    with tempfile.TemporaryDirectory() as scratch:
        print(report(measure(d, chosen, chosen_options, retime.Pacing(args.pause, args.max_speed), Path(scratch))))

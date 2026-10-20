"""Assemble the narrated video: every scene's shots on the desktop, voiced, held to fit.

    python assemble.py <demo-folder> <out.mp4> [voice]

For each scene in demo.SCENES (in order) and each shot in its take: render the shot
(cut.render), voice its line with macOS `say`, and when the line needs longer than the
footage, hold the shot's last frame until the line is done. A title card opens the video.

Writes four files:
  <out>.mp4            the video with the placeholder `say` narration
  <out>-script.md      the read-along script: each line's start time and its seconds
  <out>-picture.mp4    the same video with no audio, the master for the human voice-over
  <out>-preview.mp4    a small copy for sharing in chat (well under 30 MB for ~5 min)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

from cut import FONT_B, FPS, _text, duration, events_of, render, shots, wallpaper
from recorder import load_demo

WPM = 175
LEAD, TAIL = 0.25, 0.45  # air before a line starts, and after it ends, inside its shot
TITLE_SECONDS = 3.0


def voice(text: str, voice_name: str, dst: Path) -> float:
    subprocess.run(["say", "-v", voice_name, "-r", str(WPM), "-o", str(dst), text], check=True)
    return duration(dst)


def finish_shot(video: Path, line: Path | None, line_len: float, dst: Path) -> float:
    """Mux the shot with its line (or silence), holding the last frame if the line is longer."""
    length = duration(video)
    need = LEAD + line_len + TAIL if line else 0.0
    hold = max(0.0, need - length)
    total = length + hold
    vf = f"tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold else "null"
    if line:
        audio = ["-i", str(line), "-filter_complex",
                 f"[0:v]{vf}[v];[1:a]aresample=48000,adelay={int(LEAD * 1000)}|"
                 f"{int(LEAD * 1000)},apad,atrim=0:{total:.3f}[a]"]
    else:
        audio = ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=mono",
                 "-filter_complex", f"[0:v]{vf}[v];[1:a]anull[a]"]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), *audio,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac",
                    "-ar", "48000", "-ac", "1", "-b:a", "160k", "-t", f"{total:.3f}", str(dst)],
                   check=True)
    return total


def title_card(demo: ModuleType, bg: Path, dst: Path) -> None:
    s = TITLE_SECONDS
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-framerate", str(FPS),
                    "-t", f"{s}", "-i", str(bg), "-f", "lavfi", "-t", f"{s}",
                    "-i", "anullsrc=r=48000:cl=mono", "-vf",
                    f"drawtext=fontfile='{FONT_B}':text='{_text(demo.TITLE)}':fontcolor=white:"
                    f"fontsize=64:x=(w-tw)/2:y=(h-th)/2,fade=t=in:d=0.6,"
                    f"fade=t=out:st={s - 0.6}:d=0.6",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac",
                    "-ar", "48000", "-ac", "1", "-shortest", str(dst)], check=True)


def stamp(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def check(demo: ModuleType) -> None:
    """Fail before any rendering: every take recorded, one line per shot."""
    for scene in demo.SCENES:
        take = demo.OUT / scene["take"]
        if not (take / "events.jsonl").exists():
            raise SystemExit(f"{scene['take']}: not recorded (no {take}/events.jsonl)")
        n = len(shots(events_of(take)))
        if n != len(scene["lines"]):
            raise SystemExit(f"{scene['take']}: {n} shots but {len(scene['lines'])} lines")


def main(demo: ModuleType, out: Path, voice_name: str) -> None:
    check(demo)
    script = [f"# {demo.TITLE}: narration", "",
              "Read-along script. Each line: where it starts in the video, (window, seconds it has "
              "until the next shot) and the words.", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bg = tmp / "bg.png"
        wallpaper(demo, bg)
        parts, at = [tmp / "title.mp4"], TITLE_SECONDS
        title_card(demo, bg, parts[0])
        for scene in demo.SCENES:
            take = demo.OUT / scene["take"]
            events = events_of(take)
            starts = {e["stream"]: e["t"] for e in events if e["kind"] == "start"}
            script.append(f"## {scene['take']}")
            for i, (shot, text) in enumerate(zip(shots(events, scene.get("speeds")),
                                                 scene["lines"])):
                raw, clip, line_len = tmp / f"{take.name}-{i}.mp4", None, 0.0
                render(demo, take, shot, starts, bg, raw)
                if text:
                    clip = tmp / f"{take.name}-{i}.aiff"
                    line_len = voice(text, voice_name, clip)
                part = tmp / f"{take.name}-{i}-final.mp4"
                length = finish_shot(raw, clip, line_len, part)
                if text:  # the reader's budget: from this line's start to the next shot
                    script.append(f"- **{stamp(at + LEAD)}** ({shot.focus}, "
                                  f"{length - LEAD:.1f} s) {text}")
                at += length
                parts.append(part)
            script.append("")
        listing = tmp / "parts.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-c", "copy", str(out)], check=True)
    script[2:2] = [f"Length {stamp(at)}.", ""]
    out.with_name(out.stem + "-script.md").write_text("\n".join(script) + "\n")
    # The voice-over master: the same picture with no audio, so iMovie has nothing to mute.
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(out), "-an", "-c:v", "copy",
                    str(out.with_name(out.stem + "-picture.mp4"))], check=True)
    preview = out.with_name(out.stem + "-preview.mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(out), "-c:v", "libx264",
                    "-preset", "medium", "-crf", "26", "-c:a", "aac", "-b:a", "128k",
                    str(preview)], check=True)
    print(f"{out}  ({stamp(at)})")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit("usage: assemble.py <demo-folder> <out.mp4> [voice]")
    main(load_demo(sys.argv[1]), Path(sys.argv[2]).expanduser(),
         sys.argv[3] if len(sys.argv) == 4 else "Samantha")

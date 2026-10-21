"""The narration voice. Kokoro-82M (local, open weights) by default; macOS `say` for any other name.

A Kokoro voice is named like `af_heart`: language (a American, b British), gender, name. Any
other name goes to `say -v`. A line may carry Kokoro's markup for a word: a pronunciation,
`[frontmatter](/fɹˈʌntmætəɹ/)`, or a stress, `[word](+1)`. Kokoro speaks only the bracketed
word, and `spoken` does the same for `say` and for the read-along script.

Kokoro runs in its own uv environment (it needs Python 3.10 to 3.12), once for every line, so
the model loads once. Its first run downloads the model (about 330 MB) to the Hugging Face cache.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from cut import duration

KOKORO = "kokoro==0.9.4"
KOKORO_PYTHON = "3.12"
DEFAULT_VOICE = "af_heart"
SAY_WPM = 175
_KOKORO_VOICE = re.compile(r"^[a-z][fm]_[a-z]+$")
_MARKUP = re.compile(r"\[([^\]]+)\]\([^)]*\)")  # misaki's LINK_REGEX: Kokoro speaks only the word
_BATCH = Path(__file__).resolve().with_name("kokoro_lines.py")


def is_kokoro(voice: str) -> bool:
    return bool(_KOKORO_VOICE.match(voice))


def spoken(text: str) -> str:
    """The line as Kokoro speaks it: `[word](...)` becomes `word`."""
    return _MARKUP.sub(r"\1", text)


def voice_lines(lines: list[str], voice: str, tmp: Path) -> list[tuple[Path, float]]:
    """Voice each line into its own file under *tmp*; return each file and its seconds."""
    if not lines:
        return []
    if is_kokoro(voice):
        files = _kokoro(lines, voice, tmp)
    else:
        files = [_say(line, voice, tmp / f"line-{i}.aiff") for i, line in enumerate(lines)]
    for line, f in zip(lines, files):
        if not f.exists():
            raise SystemExit(f"the {voice} voice wrote no audio for: {spoken(line)!r}")
    return [(f, duration(f)) for f in files]


def _kokoro(lines: list[str], voice: str, tmp: Path) -> list[Path]:
    files = [tmp / f"line-{i}.wav" for i in range(len(lines))]
    jobs = tmp / "lines.json"
    jobs.write_text(json.dumps([{"text": t, "out": str(f)} for t, f in zip(lines, files)]))
    subprocess.run(["uv", "run", "-q", "--no-project", "--python", KOKORO_PYTHON,
                    "--with", KOKORO, "--with", "soundfile", "python", str(_BATCH),
                    str(jobs), voice],
                   check=True, env={**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"})
    return files


def _say(line: str, voice: str, dst: Path) -> Path:
    subprocess.run(["say", "-v", voice, "-r", str(SAY_WPM), "-o", str(dst), spoken(line)],
                   check=True)
    return dst

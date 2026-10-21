"""Voice a batch of lines with Kokoro-82M. Run by tts.py inside Kokoro's own uv environment.

    python kokoro_lines.py <lines.json> <voice>

lines.json is a list of {"text", "out"}; each line becomes a 24 kHz wav at "out".
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

for noise in (DeprecationWarning, FutureWarning, UserWarning):  # torch and spaCy, not errors
    warnings.filterwarnings("ignore", category=noise)

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from kokoro import KPipeline  # noqa: E402

RATE = 24000


def main(jobs: list[dict], voice: str) -> None:
    pipeline = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M")
    for job in jobs:
        audio = [chunk for _, _, chunk in pipeline(job["text"], voice=voice)]
        if not audio:
            raise SystemExit(f"Kokoro produced no audio for: {job['text']!r}")
        sf.write(job["out"], np.concatenate(audio), RATE)


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[1]).read_text()), sys.argv[2])

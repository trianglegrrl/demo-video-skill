"""The narration voice. Kokoro-82M (local, open weights) by default; ElevenLabs for `eleven:<name>`;
macOS `say` for any other name.

A Kokoro voice is named like `af_heart`: language (a American, b British), gender, name. An
ElevenLabs voice is `eleven:Bella` (a name or a voice id; plain `eleven` is the default voice), and
its words leave this Mac, so it runs only when named: on the command line, as VOICE in demo.py,
or saved with voices.py. Any other name goes to `say -v`. A line may carry Kokoro's markup for a
word: a pronunciation, `[frontmatter](/fɹˈʌntmætəɹ/)`, or a stress, `[word](+1)`. Kokoro speaks only
the bracketed word, `eleven_text` translates the markup for ElevenLabs, and `spoken` does the same
for `say` and for the read-along script.

Kokoro runs in its own uv environment (it needs Python 3.10 to 3.12), once for every line, so
the model loads once. Its first run downloads the model (about 330 MB) to the Hugging Face cache.

Every voiced line is cached with the silence around it trimmed, so a line's seconds are its speech
and a re-assemble neither re-voices nor bills. Each is cached as soon as it's voiced, so a run that
fails midway keeps what it paid for. Changing the words, voice, model or settings passed here voices
just that line again. The cache knows a voice by how it's spelled, so that a cached re-assemble needs
no network: `eleven` and `eleven:Bella` voice separately, and settings changed on ElevenLabs' own
site or a voice renamed there won't re-voice anything (delete ~/.cache/demo-video/tts to force it).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import ModuleType

import elevenlabs
from cut import duration

KOKORO = "kokoro==0.9.4"
KOKORO_PYTHON = "3.12"
DEFAULT_VOICE = "af_heart"
ELEVEN_VOICE_ID = "hpp4J3VqNfWAUOO0d1Us"  # Bella: premade, American, informative
ELEVEN_MODEL = "eleven_v4"  # ElevenLabs' pick for narration; reads /ipa/ inline
NO_SPEED_MODELS = ("eleven_v3", "eleven_v4")
SAY_WPM = 175
CACHE = Path.home() / ".cache/demo-video/tts"
CONFIG = Path.home() / ".config/demo-video/voice.json"
SILENCE = "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.02"
_KOKORO_VOICE = re.compile(r"^[a-z][fm]_[a-z]+$")
_MARKUP = re.compile(r"\[([^\]]+)\]\([^)]*\)")  # misaki's LINK_REGEX: Kokoro speaks only the word
_MARKUP_PARTS = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")
# misaki's shorthand for sounds that standard IPA writes with two symbols (its EN_PHONES.md).
_MISAKI_TO_IPA = str.maketrans({"A": "eɪ", "I": "aɪ", "W": "aʊ", "Y": "ɔɪ", "O": "oʊ", "Q": "əʊ",
                                "ʤ": "dʒ", "ʧ": "tʃ", "ᵊ": "ə"})
_BATCH = Path(__file__).resolve().with_name("kokoro_lines.py")


def is_kokoro(voice: str) -> bool:
    return bool(_KOKORO_VOICE.match(voice))


def is_eleven(voice: str) -> bool:
    return voice == "eleven" or voice.startswith("eleven:")


def spoken(text: str) -> str:
    """The line as Kokoro speaks it: `[word](...)` becomes `word`."""
    return _MARKUP.sub(r"\1", text)


def eleven_text(text: str, model: str) -> str:
    """The line for ElevenLabs: v4 reads `/ipa/` inline; other models get the plain word."""
    def translate(found: re.Match) -> str:
        word, target = found.groups()
        if not (target.startswith("/") and target.endswith("/")):
            return word
        if model.startswith("eleven_v4"):
            return target.translate(_MISAKI_TO_IPA)
        print(f"{model} reads no inline pronunciation: saying {word!r} as plain text", file=sys.stderr)
        return word
    return _MARKUP_PARTS.sub(translate, text)


def saved() -> dict:
    """What voices.py set saved, or nothing."""
    if not CONFIG.exists():
        return {}
    try:
        return json.loads(CONFIG.read_text())
    except json.JSONDecodeError as err:
        raise SystemExit(f"{CONFIG} is not valid JSON ({err}): fix it, or set the voice again") from err


def choose(cli_voice: str | None, demo: ModuleType) -> tuple[str, dict]:
    """The voice and its options: command line, then demo.py, then saved, then Kokoro."""
    config = saved()
    voice = cli_voice or getattr(demo, "VOICE", None) or config.get("voice") or DEFAULT_VOICE
    local = dict(getattr(demo, "VOICE_SETTINGS", None) or {})
    mine = saved_options(voice)  # settings saved for another voice would change how this one sounds
    model = local.pop("model", None) or mine.get("model")
    settings = {**mine.get("settings", {}), **local}
    return voice, {**({"model": model} if model else {}), **({"settings": settings} if settings else {})}


def saved_options(voice: str) -> dict:
    """The model and settings saved for *voice*, if it is the saved voice."""
    config = saved()
    return {k: config[k] for k in ("model", "settings") if k in config} if config.get("voice") == voice else {}


def _eleven_ref(voice: str) -> str:
    return voice.partition(":")[2] or ELEVEN_VOICE_ID


def _cached_path(line: str, voice: str, options: dict) -> Path:
    if is_eleven(voice):
        recipe = ["eleven", _eleven_ref(voice).casefold(), options.get("model", ELEVEN_MODEL),
                  options.get("settings", {}), elevenlabs.OUTPUT_FORMAT, line]
        suffix = ".wav"
    elif is_kokoro(voice):
        recipe, suffix = ["kokoro", KOKORO, voice, line], ".wav"
    else:
        recipe, suffix = ["say", voice, SAY_WPM, spoken(line)], ".aiff"
    digest = hashlib.sha256(json.dumps(recipe, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return CACHE / f"{digest}{suffix}"


def voice_lines(lines: list[str], voice: str, tmp: Path,
                options: dict | None = None) -> list[tuple[Path, float]]:
    """Each line's cached file and its seconds of speech, voicing only the lines not yet cached."""
    if not lines:
        return []
    options = options or {}
    wanted = {line: _cached_path(line, voice, options) for line in lines}
    missing = [line for line, path in wanted.items() if not path.exists()]
    if missing:
        CACHE.mkdir(parents=True, exist_ok=True)
        for line, raw in zip(missing, _voice(missing, voice, tmp, options), strict=True):
            if not raw.exists():
                raise SystemExit(f"the {voice} voice wrote no audio for: {spoken(line)!r}")
            _trim(raw, wanted[line])
    return [(wanted[line], duration(wanted[line])) for line in lines]


def _voice(lines: list[str], voice: str, tmp: Path, options: dict) -> Iterable[Path]:
    if is_eleven(voice):
        return _eleven(lines, voice, tmp, options)
    if is_kokoro(voice):
        return _kokoro(lines, voice, tmp)
    return [_say(line, voice, tmp / f"line-{i}.aiff") for i, line in enumerate(lines)]


def _eleven(lines: list[str], voice: str, tmp: Path, options: dict) -> Iterator[Path]:
    """One line at a time, so the caller caches each paid line before the next is asked for."""
    model, settings = options.get("model", ELEVEN_MODEL), options.get("settings", {})
    if "speed" in settings and model.startswith(NO_SPEED_MODELS):
        print(f"{model} accepts speed but ignores it (measured): the line's pace will not change. "
              "eleven_turbo_v2_5 honours it", file=sys.stderr)
    voice_id = elevenlabs.voice_id(_eleven_ref(voice))
    chars = sum(len(line) for line in lines)
    print(f"sending {len(lines)} new lines ({chars} characters) to ElevenLabs", file=sys.stderr)
    for i, line in enumerate(lines):
        raw = tmp / f"line-{i}.mp3"
        raw.write_bytes(elevenlabs.synthesize(eleven_text(line, model), voice_id, model, settings))
        yield raw


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


def _trim(src: Path, dst: Path) -> None:
    """Copy *src* to *dst* without the silence before and after the speech. Whole or not at all:
    a killed run must not leave a short line in the cache."""
    part = dst.with_name(f"{dst.stem}.part{dst.suffix}")
    done = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-af",
                           f"{SILENCE},areverse,{SILENCE},areverse", str(part)],
                          capture_output=True, text=True)
    try:
        audible = done.returncode == 0 and duration(part) > 0
    except (ValueError, subprocess.CalledProcessError):
        audible = False
    if not audible:
        part.unlink(missing_ok=True)
        raise SystemExit(f"no speech in {src.name}: all silence, or ffmpeg failed: {done.stderr.strip()}")
    part.rename(dst)

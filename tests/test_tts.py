"""The narration voice: which engine a voice name picks, the pronunciation markup, and one
Kokoro process for every line.

    uv run -q --no-project --with playwright --with pytest pytest .claude/skills/demo-video/tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tts  # noqa: E402


@pytest.mark.parametrize(("name", "kokoro"), [("af_heart", True), ("bf_emma", True), ("am_adam", True),
                                              ("Samantha", False), ("Ava (Premium)", False)],
                         ids=["american-female", "british-female", "american-male", "say", "say-premium"])
def test_a_kokoro_voice_name_picks_kokoro_and_anything_else_picks_say(name, kokoro):
    assert tts.is_kokoro(name) is kokoro, f"{name!r} should pick {'Kokoro' if kokoro else 'say'}"


def test_the_default_voice_is_kokoro():
    assert tts.is_kokoro(tts.DEFAULT_VOICE), f"default {tts.DEFAULT_VOICE!r} is not a Kokoro voice"


def test_spoken_text_keeps_the_word_and_drops_its_pronunciation():
    line = "Up top, its [frontmatter](/fɹˈʌntmætəɹ/) and [Kokoro](/kˈOkəɹO/) itself."
    assert tts.spoken(line) == "Up top, its frontmatter and Kokoro itself."


@pytest.mark.parametrize(("line", "words"), [
    ("See [the docs](https://x.io/a) now.", "See the docs now."),  # a link: Kokoro drops the URL
    ("It's [really](+1) good, [not](-0.5) bad.", "It's really good, not bad."),  # stress
], ids=["link", "stress"])
def test_spoken_text_drops_every_markup_target_the_way_kokoro_does(line, words):
    assert tts.spoken(line) == words


def test_spoken_text_leaves_an_ordinary_line_alone():
    assert tts.spoken("Version 1.1.0 moved (on purpose).") == "Version 1.1.0 moved (on purpose)."


def _fake_run(calls: list, *, writes: bool = True):
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if writes and "--with" in cmd:  # the Kokoro batch: one wav per job
            for job in json.loads(Path(cmd[-2]).read_text()):
                Path(job["out"]).write_bytes(b"wav")
        elif writes:  # say -o <file>
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"aiff")
        return subprocess.CompletedProcess(cmd, 0)
    return run


def test_kokoro_voices_every_line_in_one_process_with_the_markup_intact(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tts, "duration", lambda p: 2.5)
    lines = ["The short version.", "Its [frontmatter](/fɹˈʌntmætəɹ/)."]

    out = tts.voice_lines(lines, "af_heart", tmp_path)

    assert len(calls) == 1, f"one model load for the whole video, not one per line: {calls}"
    jobs = json.loads(Path(calls[0][0][-2]).read_text())
    assert [j["text"] for j in jobs] == lines, "Kokoro reads the pronunciation markup itself"
    assert [(p.suffix, s) for p, s in out] == [(".wav", 2.5), (".wav", 2.5)], out


def test_kokoro_runs_the_pinned_version_with_the_voice_and_the_mps_fallback(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tts, "duration", lambda p: 1.0)

    tts.voice_lines(["One line."], "bf_emma", tmp_path)

    (cmd, kwargs), = calls
    assert tts.KOKORO in cmd and cmd[-1] == "bf_emma", f"unpinned or wrong voice: {cmd}"
    assert kwargs["check"] is True, "a failed Kokoro run must stop the assemble"
    assert kwargs["env"]["PYTORCH_ENABLE_MPS_FALLBACK"] == "1", "Apple silicon needs the MPS fallback"


def test_say_voices_each_line_without_the_markup(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tts, "duration", lambda p: 1.0)

    out = tts.voice_lines(["Its [frontmatter](/fɹˈʌntmætəɹ/)."], "Samantha", tmp_path)

    (cmd, _), = calls
    assert cmd[:3] == ["say", "-v", "Samantha"], cmd
    assert cmd[-1] == "Its frontmatter.", f"say must get plain words, got {cmd[-1]!r}"
    assert [p.suffix for p, _ in out] == [".aiff"], out


def test_a_kokoro_run_that_writes_no_audio_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setattr(tts.subprocess, "run", _fake_run([], writes=False))
    with pytest.raises(SystemExit, match=r"no audio for: 'Its frontmatter\.'"):
        tts.voice_lines(["Its [frontmatter](/fɹˈʌntmætəɹ/)."], "af_heart", tmp_path)


def test_no_lines_starts_no_voice(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts.subprocess, "run", _fake_run(calls))

    out = tts.voice_lines([], "af_heart", tmp_path)

    assert out == [], out
    assert calls == [], f"a demo with no lines must not load the model: {calls}"

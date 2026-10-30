"""The narration voice: which engine a voice name picks, the pronunciation markup, and one
Kokoro process for every line.

    uv run -q --no-project --with playwright --with pytest pytest .claude/skills/demo-video/tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tts  # noqa: E402


@pytest.fixture(autouse=True)
def private_voice_cache(tmp_path, monkeypatch):
    """Every test gets an empty cache, and a trim that just copies (real trim: below)."""
    monkeypatch.setattr(tts, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(tts, "CONFIG", tmp_path / "no-config.json")
    monkeypatch.setattr(tts, "_trim", lambda src, dst: dst.write_bytes(src.read_bytes()))


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


def test_a_voiced_line_is_not_voiced_again(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tts, "duration", lambda p: 1.0)

    first = tts.voice_lines(["One line."], "af_heart", tmp_path)
    second = tts.voice_lines(["One line."], "af_heart", tmp_path)

    assert len(calls) == 1, f"the second run should come from the cache: {calls}"
    assert first == second


def test_kokoro_batches_only_the_lines_it_has_not_voiced(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tts, "duration", lambda p: 1.0)
    tts.voice_lines(["Old line."], "af_heart", tmp_path)

    out = tts.voice_lines(["Old line.", "New line."], "af_heart", tmp_path)

    assert [j["text"] for j in json.loads(Path(calls[1][0][-2]).read_text())] == ["New line."]
    assert len(out) == 2 and out[0][0] != out[1][0], out


def test_changing_the_voice_or_the_words_voices_again(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(tts.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(tts, "duration", lambda p: 1.0)

    for line, voice in (("One.", "af_heart"), ("One.", "bf_emma"), ("Two.", "af_heart")):
        tts.voice_lines([line], voice, tmp_path)

    assert len(calls) == 3, calls


@pytest.fixture
def eleven(monkeypatch):
    """A fake ElevenLabs account: one voice, and a record of every synthesis (the billed call)."""
    billed: list = []
    monkeypatch.setattr(tts.elevenlabs, "list_voices",
                        lambda: [{"voice_id": "v" * 20, "name": "Bella - Warm"}])

    def synthesize(text, voice_id, model, settings):
        billed.append((text, voice_id, model, settings))
        return b"mp3"

    monkeypatch.setattr(tts.elevenlabs, "synthesize", synthesize)
    monkeypatch.setattr(tts, "duration", lambda p: 2.0)
    return billed


@pytest.mark.parametrize(("name", "yes"), [("eleven:Bella", True), ("eleven:", True), ("eleven", True),
                                           ("af_heart", False), ("Samantha", False), ("Eleven Labs", False)])
def test_an_eleven_prefix_picks_elevenlabs(name, yes):
    assert tts.is_eleven(name) is yes


def test_elevenlabs_voices_a_line_with_the_model_and_settings_given(tmp_path, eleven):
    out = tts.voice_lines(["Hello."], "eleven:Bella", tmp_path,
                          {"model": "eleven_v3", "settings": {"speed": 1.1}})

    assert eleven == [("Hello.", "v" * 20, "eleven_v3", {"speed": 1.1})]
    assert out[0][1] == 2.0 and out[0][0].suffix == ".wav", out


def test_a_bare_eleven_uses_the_default_voice_and_model(tmp_path, monkeypatch, eleven):
    monkeypatch.setattr(tts.elevenlabs, "list_voices", lambda: pytest.fail("an id needs no lookup"))
    tts.voice_lines(["Hello."], "eleven", tmp_path)
    assert eleven == [("Hello.", tts.ELEVEN_VOICE_ID, tts.ELEVEN_MODEL, {})]


def test_a_cached_elevenlabs_line_makes_no_api_call_at_all(tmp_path, monkeypatch, eleven):
    tts.voice_lines(["Hello."], "eleven:Bella", tmp_path)
    monkeypatch.setattr(tts.elevenlabs, "list_voices", lambda: pytest.fail("looked up a cached voice"))

    tts.voice_lines(["Hello."], "eleven:Bella", tmp_path)

    assert len(eleven) == 1, f"billed twice for one line: {eleven}"


@pytest.mark.parametrize("options", [{"model": "eleven_v3"}, {"settings": {"speed": 1.1}}],
                         ids=["model", "settings"])
def test_changing_the_model_or_settings_voices_again(tmp_path, eleven, options):
    tts.voice_lines(["Hello."], "eleven:Bella", tmp_path)
    tts.voice_lines(["Hello."], "eleven:Bella", tmp_path, options)
    assert len(eleven) == 2, eleven


def test_v4_reads_a_pronunciation_inline_with_kokoros_shorthand_expanded():
    line = "Up top, [Kokoro](/kˈOkəɹO/) and [judge](/ʤˈʌʤ/)."
    assert tts.eleven_text(line, "eleven_v4") == "Up top, /kˈoʊkəɹoʊ/ and /dʒˈʌdʒ/."


def test_v4_drops_stress_marks_and_link_targets():
    assert tts.eleven_text("It's [really](+1) [here](https://x.io).", "eleven_v4") == "It's really here."


def test_other_models_say_the_plain_word_and_warn(capsys):
    assert tts.eleven_text("Its [frontmatter](/fɹˈʌntmætəɹ/).", "eleven_v3") == "Its frontmatter."
    assert "frontmatter" in capsys.readouterr().err


@pytest.mark.parametrize(("cli", "demo", "saved", "voice"), [
    ("bf_emma", "eleven:Demo", "eleven:Saved", "bf_emma"),
    (None, "eleven:Demo", "eleven:Saved", "eleven:Demo"),
    (None, None, "eleven:Saved", "eleven:Saved"),
    (None, None, None, tts.DEFAULT_VOICE),
], ids=["cli", "demo", "saved", "kokoro-default"])
def test_the_voice_comes_from_the_nearest_place_that_names_one(tmp_path, monkeypatch, cli, demo, saved, voice):
    if saved:
        monkeypatch.setattr(tts, "CONFIG", tmp_path / "voice.json")
        tts.CONFIG.write_text(json.dumps({"voice": saved}))
    module = SimpleNamespace(VOICE=demo) if demo else SimpleNamespace()
    assert tts.choose(cli, module)[0] == voice


def test_a_key_in_the_environment_never_switches_the_engine_on_its_own(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    assert tts.choose(None, SimpleNamespace())[0] == tts.DEFAULT_VOICE


def test_demo_settings_layer_over_saved_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "CONFIG", tmp_path / "voice.json")
    tts.CONFIG.write_text(json.dumps({"voice": "eleven:Bella", "model": "eleven_v3",
                                      "settings": {"stability": 0.4, "speed": 1.1}}))
    demo = SimpleNamespace(VOICE_SETTINGS={"model": "eleven_v4", "speed": 0.9})

    assert tts.choose(None, demo) == ("eleven:Bella", {"model": "eleven_v4",
                                                       "settings": {"stability": 0.4, "speed": 0.9}})


def _tone_between_silences(path: Path) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='if(between(t,1,3),0.5*sin(2*PI*440*t),0)':d=6:s=24000",
                    str(path)], check=True)


def test_trim_removes_the_silence_around_speech(tmp_path, ffmpeg, monkeypatch):
    monkeypatch.undo()  # the real trim, not the autouse copy
    src, dst = tmp_path / "in.wav", tmp_path / "out.wav"
    _tone_between_silences(src)

    tts._trim(src, dst)

    assert abs(tts.duration(dst) - 2.0) < 0.1, f"6 s with 2 s of tone trimmed to {tts.duration(dst)}"


def test_trim_refuses_audio_that_is_all_silence(tmp_path, ffmpeg, monkeypatch):
    monkeypatch.undo()
    src = tmp_path / "in.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", "2", str(src)], check=True)
    with pytest.raises(SystemExit, match="no speech"):
        tts._trim(src, tmp_path / "out.wav")


@pytest.mark.parametrize(("model", "warns"), [("eleven_v4", True), ("eleven_v3", True),
                                              ("eleven_turbo_v2_5", False)])
def test_a_speed_the_model_ignores_says_so(tmp_path, eleven, capsys, model, warns):
    tts.voice_lines(["Hello."], "eleven", tmp_path, {"model": model, "settings": {"speed": 1.1}})
    assert ("ignores" in capsys.readouterr().err) is warns


def test_a_run_that_fails_midway_keeps_the_lines_it_paid_for(tmp_path, monkeypatch, eleven):
    real = tts.elevenlabs.synthesize

    def fail_on_c(text, voice_id, model, settings):
        if text == "c":
            raise SystemExit("quota exceeded")
        return real(text, voice_id, model, settings)

    monkeypatch.setattr(tts.elevenlabs, "synthesize", fail_on_c)
    with pytest.raises(SystemExit, match="quota"):
        tts.voice_lines(["a", "b", "c"], "eleven:Bella", tmp_path)
    monkeypatch.setattr(tts.elevenlabs, "synthesize", real)

    tts.voice_lines(["a", "b", "c"], "eleven:Bella", tmp_path)

    assert [row[0] for row in eleven] == ["a", "b", "c"], f"a and b were billed twice: {eleven}"


def test_settings_saved_for_one_voice_do_not_change_another(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "CONFIG", tmp_path / "voice.json")
    tts.CONFIG.write_text(json.dumps({"voice": "eleven:Bella", "model": "eleven_v3",
                                      "settings": {"stability": 0.4}}))
    assert tts.choose("eleven:Matilda", SimpleNamespace()) == ("eleven:Matilda", {})
    assert tts.choose("eleven:Bella", SimpleNamespace())[1]["model"] == "eleven_v3"


def test_voicing_says_what_it_sends_and_a_cached_line_sends_nothing(tmp_path, eleven, capsys):
    tts.voice_lines(["Hello."], "eleven:Bella", tmp_path)
    assert "1 new lines (6 characters)" in capsys.readouterr().err
    tts.voice_lines(["Hello."], "eleven:Bella", tmp_path)
    assert "ElevenLabs" not in capsys.readouterr().err

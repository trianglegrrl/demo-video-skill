"""The voices command: saving a choice, and filtering the list.

    uv run -q --no-project --with playwright --with pytest pytest tests
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tts  # noqa: E402
import voices  # noqa: E402

VOICES = [
    {"voice_id": "a" * 20, "name": "Bella - Warm", "category": "premade",
     "labels": {"gender": "female", "accent": "american", "age": "middle_aged"}},
    {"voice_id": "b" * 20, "name": "George - Storyteller", "category": "premade",
     "labels": {"gender": "male", "accent": "british", "age": "middle_aged"}},
]


@pytest.fixture
def config(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "cfg" / "voice.json"
    monkeypatch.setattr(tts, "CONFIG", path)
    monkeypatch.setattr(voices.elevenlabs, "list_voices", lambda: VOICES)
    return path


def test_set_saves_the_voice_model_and_only_the_settings_given(config):
    voices.main(["set", "Bella", "--model", "eleven_v3", "--stability", "0.4"])
    assert json.loads(config.read_text()) == {
        "voice": "eleven:Bella", "model": "eleven_v3", "settings": {"stability": 0.4}}


def test_set_refuses_a_voice_that_does_not_exist_and_saves_nothing(config):
    with pytest.raises(SystemExit, match="voices.py list"):
        voices.main(["set", "Nobody"])
    assert not config.exists(), "a typo must not become the saved default"


def test_set_with_a_local_voice_needs_no_account(config, monkeypatch):
    monkeypatch.setattr(voices.elevenlabs, "list_voices", lambda: pytest.fail("no API for Kokoro"))
    voices.main(["set", "af_heart"])
    assert json.loads(config.read_text())["voice"] == "af_heart"


def test_set_keeps_an_earlier_setting_when_changing_another(config):
    voices.main(["set", "Bella", "--stability", "0.4"])
    voices.main(["set", "Bella", "--speed", "1.1"])
    assert json.loads(config.read_text())["settings"] == {"stability": 0.4, "speed": 1.1}


def test_set_on_another_voice_starts_its_settings_over(config):
    voices.main(["set", "Bella", "--stability", "0.4"])
    voices.main(["set", "George"])
    assert json.loads(config.read_text()) == {"voice": "eleven:George"}


def test_list_filters_by_label(config, capsys):
    voices.main(["list", "--accent", "british"])
    out = capsys.readouterr().out
    assert "George" in out and "Bella" not in out, out


def test_list_search_matches_the_name_in_any_case(config, capsys):
    voices.main(["list", "--search", "BELL"])
    out = capsys.readouterr().out
    assert "Bella" in out and "George" not in out, out


def test_get_shows_the_kokoro_default_before_anything_is_set(config, capsys):
    voices.main(["get"])
    assert tts.DEFAULT_VOICE in capsys.readouterr().out


def test_list_filters_ignore_case(config, capsys):
    voices.main(["list", "--gender", "MALE"])
    out = capsys.readouterr().out
    assert "George" in out and "Bella" not in out, out

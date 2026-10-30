"""The ElevenLabs client: finding the key, naming a voice, and what happens when the API says no.
No test here reaches the network: `_send` is the one function that does.

    uv run -q --no-project --with playwright --with pytest pytest tests
"""
from __future__ import annotations

import http.client
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import elevenlabs  # noqa: E402

KEY = "sk-test-not-a-real-key"
VOICES = [{"voice_id": "a" * 20, "name": "Bella - Professional, Bright, Warm"},
          {"voice_id": "b" * 20, "name": "Bill - Wise, Mature, Balanced"},
          {"voice_id": "c" * 20, "name": "Mellow Matt"}]


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)


def _http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "no", {}, io.BytesIO(body.encode()))


def test_the_environment_key_wins_over_the_key_file(tmp_path, monkeypatch):
    (tmp_path / "elevenlabs.env").write_text("ELEVENLABS_API_KEY=from-file\n")
    monkeypatch.setattr(elevenlabs, "KEY_FILE", tmp_path / "elevenlabs.env")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-env")
    assert elevenlabs.api_key() == "from-env"


@pytest.mark.parametrize("line", ["ELEVENLABS_API_KEY=abc123", 'ELEVENLABS_API_KEY="abc123"',
                                  "export ELEVENLABS_API_KEY='abc123'"],
                         ids=["bare", "double-quoted", "exported-single-quoted"])
def test_the_key_file_reads_the_usual_env_spellings(tmp_path, monkeypatch, line):
    (tmp_path / "elevenlabs.env").write_text(f"# a comment\nOTHER=1\n{line}\n")
    monkeypatch.setattr(elevenlabs, "KEY_FILE", tmp_path / "elevenlabs.env")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert elevenlabs.api_key() == "abc123"


def test_no_key_anywhere_says_how_to_add_one(tmp_path, monkeypatch):
    monkeypatch.setattr(elevenlabs, "KEY_FILE", tmp_path / "missing.env")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ELEVENLABS_API_KEY"):
        elevenlabs.api_key()


@pytest.mark.parametrize(("ref", "voice_id"), [
    ("Bella", "a" * 20), ("bella", "a" * 20), ("Mellow Matt", "c" * 20), ("mellow", "c" * 20),
    ("Bella - Professional, Bright, Warm", "a" * 20), ("b" * 20, "b" * 20),
], ids=["short-name", "any-case", "name-without-a-dash", "prefix", "full-name", "voice-id"])
def test_a_voice_is_found_by_any_natural_name(ref, voice_id):
    assert elevenlabs.resolve_voice(ref, VOICES) == voice_id


def test_a_name_matching_two_voices_fails_and_lists_them():
    with pytest.raises(SystemExit) as err:
        elevenlabs.resolve_voice("b", VOICES)
    assert "Bella" in str(err.value) and "Bill" in str(err.value), err.value


def test_an_unknown_name_points_at_the_voice_list():
    with pytest.raises(SystemExit, match="voices.py list"):
        elevenlabs.resolve_voice("Nobody", VOICES)


def test_an_id_outside_this_account_passes_through_for_the_api_to_judge():
    assert elevenlabs.resolve_voice("z" * 20, VOICES) == "z" * 20


def test_requests_carry_the_key_in_a_header(key, monkeypatch):
    seen = []

    def urlopen(req, timeout):
        seen.append(req)
        return io.BytesIO(b"{}")

    monkeypatch.setattr(elevenlabs.urllib.request, "urlopen", urlopen)
    elevenlabs.get_json("/v1/models")
    assert seen[0].get_header("Xi-api-key") == KEY and KEY not in seen[0].full_url


def test_a_refused_request_shows_the_apis_reason_but_never_the_key(key, monkeypatch):
    def urlopen(req, timeout):
        raise _http_error(422, '{"detail": "stability out of range"}')

    monkeypatch.setattr(elevenlabs.urllib.request, "urlopen", urlopen)
    with pytest.raises(SystemExit) as err:
        elevenlabs.get_json("/v1/models")
    assert "stability out of range" in str(err.value) and "422" in str(err.value), err.value
    assert KEY not in str(err.value), "the key leaked into an error message"


def test_a_rate_limit_is_retried_and_then_succeeds(key, monkeypatch):
    replies = [_http_error(429, "busy"), _http_error(503, "busy"), io.BytesIO(b'{"ok": 1}')]

    def urlopen(req, timeout):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(elevenlabs.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(elevenlabs.time, "sleep", lambda s: None)
    assert elevenlabs.get_json("/v1/x") == {"ok": 1} and not replies


def test_a_client_error_is_not_retried(key, monkeypatch):
    calls = []

    def urlopen(req, timeout):
        calls.append(req)
        raise _http_error(401, "bad key")

    monkeypatch.setattr(elevenlabs.urllib.request, "urlopen", urlopen)
    with pytest.raises(SystemExit):
        elevenlabs.get_json("/v1/x")
    assert len(calls) == 1, "a 401 costs nothing to report and will not improve on retry"


def test_retries_give_up_with_a_clear_error(key, monkeypatch):
    def urlopen(req, timeout):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(elevenlabs.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(elevenlabs.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit, match="no route"):
        elevenlabs.get_json("/v1/x")


def test_synthesis_with_no_overrides_sends_no_settings(monkeypatch):
    sent = []
    monkeypatch.setattr(elevenlabs, "_send", lambda path, body=None: sent.append((path, body)) or b"mp3")

    audio = elevenlabs.synthesize("Hello.", "v" * 20, "eleven_v4", {})

    assert audio == b"mp3" and len(sent) == 1, "no settings to read: one request"
    path, body = sent[0]
    assert path.startswith(f"/v1/text-to-speech/{'v' * 20}?output_format=")
    assert body == {"text": "Hello.", "model_id": "eleven_v4"}, body


def test_a_partial_override_keeps_the_voices_stored_settings(monkeypatch):
    """The API takes voice_settings as a whole, so one changed setting must not reset the rest."""
    sent = []

    def send(path, body=None):
        sent.append((path, body))
        return json.dumps({"stability": 0.3, "similarity_boost": 0.8}).encode() if body is None else b"mp3"

    monkeypatch.setattr(elevenlabs, "_send", send)

    elevenlabs.synthesize("Hello.", "v" * 20, "eleven_v4", {"speed": 1.1})

    assert sent[0] == (f"/v1/voices/{'v' * 20}/settings", None)
    assert sent[1][1]["voice_settings"] == {"stability": 0.3, "similarity_boost": 0.8, "speed": 1.1}


def test_every_page_of_voices_is_read(monkeypatch):
    pages = [{"voices": VOICES[:1], "has_more": True, "next_page_token": "t2"},
             {"voices": VOICES[1:], "has_more": False, "next_page_token": None}]
    paths = []
    monkeypatch.setattr(elevenlabs, "get_json", lambda path: paths.append(path) or pages.pop(0))

    assert elevenlabs.list_voices() == VOICES
    assert "next_page_token=t2" in paths[1], paths


@pytest.mark.parametrize("drop", [ConnectionResetError("reset"), http.client.RemoteDisconnected("gone"),
                                  http.client.IncompleteRead(b"")],
                         ids=["reset", "disconnected", "cut-off"])
def test_a_dropped_connection_is_retried(key, monkeypatch, drop):
    replies = [drop, io.BytesIO(b'{"ok": 1}')]

    def urlopen(req, timeout):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(elevenlabs.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(elevenlabs.time, "sleep", lambda s: None)
    assert elevenlabs.get_json("/v1/x") == {"ok": 1}

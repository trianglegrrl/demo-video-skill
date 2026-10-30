"""The ElevenLabs API, stdlib only: no dependency beyond what the takes already run with.

The key comes from ELEVENLABS_API_KEY, else from ~/.config/demo-video/elevenlabs.env. It travels
only in a request header, never in a URL, a command line or an error message. Voicing a line
sends its words to ElevenLabs and bills characters; listing voices is free. See tts.py, which
caches every voiced line so a re-assemble bills nothing.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.elevenlabs.io"
KEY_ENV = "ELEVENLABS_API_KEY"
KEY_FILE = Path.home() / ".config/demo-video/elevenlabs.env"
OUTPUT_FORMAT = "mp3_44100_128"  # every plan has it; 192 kbps and wav need a paid tier
TIMEOUT_S = 120
ATTEMPTS = 4  # one try and three retries, for a rate limit, a server error or a dropped network
_KEY_LINE = re.compile(rf"^\s*(?:export\s+)?{KEY_ENV}\s*=\s*[\"']?([^\"'\s]+)", re.M)
_VOICE_ID = re.compile(r"^[A-Za-z0-9]{20}$")


def api_key() -> str:
    key = os.environ.get(KEY_ENV)
    if key:
        return key
    found = _KEY_LINE.search(KEY_FILE.read_text()) if KEY_FILE.exists() else None
    if found:
        return found.group(1)
    raise SystemExit(f"no ElevenLabs key: set {KEY_ENV}, or put {KEY_ENV}=... in {KEY_FILE} (mode 600)")


def _send(path: str, body: dict | None = None) -> bytes:
    """GET, or POST when there is a *body*. Retries what can recover; reports what cannot."""
    data = None if body is None else json.dumps(body).encode()
    headers = {"xi-api-key": api_key(), "Content-Type": "application/json"}
    why = ""
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(2 ** attempt)
        req = urllib.request.Request(API + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as reply:
                return reply.read()
        except urllib.error.HTTPError as err:
            why = f"{err.code}: {err.read().decode(errors='replace')[:500]}"
            if err.code != 429 and err.code < 500:
                break
        except (OSError, http.client.HTTPException) as err:  # URLError, a reset, a cut-off reply
            why = str(getattr(err, "reason", err))
    raise SystemExit(f"ElevenLabs refused {path.split('?')[0]}: {why}")


def get_json(path: str) -> dict | list:
    return json.loads(_send(path))


def list_voices() -> list[dict]:
    """Every voice in the account (the /v2 list is paged)."""
    voices, token = [], None
    while True:
        query = "page_size=100" + (f"&next_page_token={urllib.parse.quote(token)}" if token else "")
        page = get_json(f"/v2/voices?{query}")
        voices += page["voices"]
        token = page.get("next_page_token")
        if not (page.get("has_more") and token):
            return voices


def is_voice_id(ref: str) -> bool:
    return bool(_VOICE_ID.match(ref))


def resolve_voice(ref: str, voices: list[dict]) -> str:
    """A voice id from an id, a name, the short name before " - ", or the start of a name."""
    wanted = ref.casefold()
    if any(v["voice_id"] == ref for v in voices):
        return ref
    names = [(v, v["name"].casefold()) for v in voices]
    for matches in ([v for v, n in names if n == wanted],
                    [v for v, n in names if n.split(" - ")[0] == wanted],
                    [v for v, n in names if n.startswith(wanted)]):
        if len(matches) == 1:
            return matches[0]["voice_id"]
        if matches:
            raise SystemExit(f"{ref!r} matches {len(matches)} voices: "
                             + "; ".join(v["name"] for v in matches))
    if is_voice_id(ref):  # a library voice, say: let the API judge it
        return ref
    raise SystemExit(f"no voice {ref!r} in this account: see voices.py list")


def voice_id(ref: str) -> str:
    return ref if is_voice_id(ref) else resolve_voice(ref, list_voices())


def synthesize(text: str, voice: str, model: str, settings: dict) -> bytes:
    """One line as audio. *settings* override the voice's stored ones; with none, none are sent."""
    body: dict = {"text": text, "model_id": model}
    if settings:  # the API takes voice_settings whole, so start from what the voice has stored
        stored = json.loads(_send(f"/v1/voices/{voice}/settings"))
        body["voice_settings"] = {**stored, **settings}
    return _send(f"/v1/text-to-speech/{voice}?output_format={OUTPUT_FORMAT}", body)

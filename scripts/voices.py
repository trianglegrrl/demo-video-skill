"""List, audition and choose narration voices.

    python voices.py list [--search TEXT] [--gender G] [--accent A]   # free
    python voices.py show <voice>                                     # free: details and settings
    python voices.py models                                           # free
    python voices.py quota                                            # free: characters used
    python voices.py say <voice> "A line." [--out file.wav]           # bills the line's characters
    python voices.py set <voice> [--model M] [--stability N] [--similarity N] [--style N]
                         [--speed N] [--speaker-boost | --no-speaker-boost]
    python voices.py get                                              # what assemble.py will use

A <voice> is an ElevenLabs name or id (`River`, `eleven:River`), or a Kokoro name (`af_heart`).
`set` saves to ~/.config/demo-video/voice.json: the voice every demo uses unless the command line
or VOICE in demo.py names another. Setting another voice starts its model and settings over. A
macOS `say` voice can't be saved: pass its name to assemble.py.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import elevenlabs
import tts

_SETTINGS = {"stability": "stability", "similarity": "similarity_boost", "style": "style",
             "speed": "speed", "speaker_boost": "use_speaker_boost"}


def _named(voice: str) -> str:
    """The voice's full spelling: anything that isn't Kokoro's is ElevenLabs'."""
    return voice if tts.is_kokoro(voice) or tts.is_eleven(voice) else f"eleven:{voice}"


def _row(voice: dict) -> str:
    labels = voice.get("labels") or {}
    about = " ".join(str(labels[k]) for k in ("gender", "age", "accent") if labels.get(k))
    use = labels.get("use_case") or labels.get("use case") or ""
    return f"{voice['voice_id']}  {voice['name']}  [{voice.get('category', '')}] {about} {use}".rstrip()


def _list(args: argparse.Namespace) -> None:
    for voice in elevenlabs.list_voices():
        labels = voice.get("labels") or {}
        if args.search and args.search.casefold() not in voice["name"].casefold():
            continue
        if args.gender and str(labels.get("gender", "")).casefold() != args.gender.casefold():
            continue
        if args.accent and args.accent.casefold() not in str(labels.get("accent", "")).casefold():
            continue
        print(_row(voice))


def _show(args: argparse.Namespace) -> None:
    ref = tts.ELEVEN_VOICE_ID if tts.is_eleven(args.voice) and ":" not in args.voice else args.voice
    voice_id = elevenlabs.voice_id(ref.removeprefix("eleven:"))
    voice = elevenlabs.get_json(f"/v1/voices/{voice_id}")
    print(_row(voice))
    print(json.dumps(elevenlabs.get_json(f"/v1/voices/{voice_id}/settings"), indent=2))


def _models(_: argparse.Namespace) -> None:
    for model in elevenlabs.get_json("/v1/models"):
        if model.get("can_do_text_to_speech"):
            cost = (model.get("model_rates") or {}).get("character_cost_multiplier")
            print(f"{model['model_id']}  {model.get('name', '')}  cost x{cost}  "
                  f"max {model.get('maximum_text_length_per_request')} chars")


def _quota(_: argparse.Namespace) -> None:
    sub = elevenlabs.get_json("/v1/user/subscription")
    print(f"{sub['character_count']} of {sub['character_limit']} characters used ({sub['tier']})")


def _say(args: argparse.Namespace) -> None:
    options = tts.saved_options(_named(args.voice))
    with tempfile.TemporaryDirectory() as tmp:
        ((path, seconds),) = tts.voice_lines([args.text], _named(args.voice), Path(tmp), options)
        shutil.copy(path, args.out)
    print(f"{args.out}  ({seconds:.1f} s of speech, {len(tts.spoken(args.text).split()) / seconds:.1f} words/s)")


def _set(args: argparse.Namespace) -> None:
    voice = _named(args.voice)
    settings = {key: getattr(args, name) for name, key in _SETTINGS.items()
                if getattr(args, name) is not None}
    if not tts.is_eleven(voice) and (settings or args.model):
        raise SystemExit("--model and the settings are for ElevenLabs voices")
    if tts.is_eleven(voice):
        elevenlabs.voice_id(voice.partition(":")[2] or tts.ELEVEN_VOICE_ID)  # a typo fails here
    old = tts.saved()
    keep = old if old.get("voice") == voice else {}
    model = args.model or keep.get("model")
    merged = {**keep.get("settings", {}), **settings}
    config = {"voice": voice, **({"model": model} if model else {}),
              **({"settings": merged} if merged else {})}
    tts.CONFIG.parent.mkdir(parents=True, exist_ok=True)
    part = tts.CONFIG.with_suffix(".part")
    part.write_text(json.dumps(config, indent=2) + "\n")
    part.rename(tts.CONFIG)
    print(f"saved to {tts.CONFIG}: {json.dumps(config)}")


def _get(_: argparse.Namespace) -> None:
    config = tts.saved()
    print(json.dumps(config, indent=2) if config else f"nothing saved: {tts.DEFAULT_VOICE} (Kokoro)")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List, audition and choose narration voices.")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--search")
    listing.add_argument("--gender")
    listing.add_argument("--accent")
    listing.set_defaults(run=_list)
    show = commands.add_parser("show")
    show.add_argument("voice")
    show.set_defaults(run=_show)
    commands.add_parser("models").set_defaults(run=_models)
    commands.add_parser("quota").set_defaults(run=_quota)
    say = commands.add_parser("say")
    say.add_argument("voice")
    say.add_argument("text")
    say.add_argument("--out", type=Path, default=Path("voice-preview.wav"))
    say.set_defaults(run=_say)
    chosen = commands.add_parser("set")
    chosen.add_argument("voice")
    chosen.add_argument("--model")
    for name in ("stability", "similarity", "style", "speed"):
        chosen.add_argument(f"--{name}", type=float)
    chosen.add_argument("--speaker-boost", action=argparse.BooleanOptionalAction)
    chosen.set_defaults(run=_set)
    commands.add_parser("get").set_defaults(run=_get)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()

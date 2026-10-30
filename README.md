# demo-video

A Claude Code skill for making narrated product demo videos **without screen capture**.

Playwright records each window (a terminal, a web app, a chat app) headless, as its own
stream on one clock. Only the stretches you mark are kept, so a 10-minute wait becomes a
"+10 min" cut. The windows are laid out on one desktop, a placeholder narration is voiced
with [Kokoro-82M](https://github.com/hexgrad/kokoro) (an open-weight voice that runs on your
Mac, so the script stays on it unless you pick an ElevenLabs voice), and you get a time-stamped script. A person then reads that script as the
real voice-over and finishes the edit in iMovie. Or name an [ElevenLabs](https://elevenlabs.io)
voice for a finished read, which sends the script to ElevenLabs (a saved voice does this for every later demo), and use `--fit` so the picture
doesn't play on in silence after a line ends.

It works with the Mac's screen locked, and re-recording one scene doesn't touch the others.

## Install

```bash
git clone <this repo's URL> ~/.claude/skills/demo-video
```

Then ask Claude Code for a demo video; the skill loads itself. `SKILL.md` is what Claude
reads; this README is for people.

## Requirements

macOS (for iMovie), [uv](https://docs.astral.sh/uv/), ffmpeg with `drawtext`, and tmux.
Homebrew's plain `ffmpeg` no longer has `drawtext`: use `brew install ffmpeg-full` and put
`$(brew --prefix ffmpeg-full)/bin` first on your `PATH`. Kokoro needs Python 3.10 to 3.12, which
uv fetches on its own; its first run downloads the model (about 330 MB). Any macOS `say` voice
still works if you pass its name instead. ElevenLabs is optional and needs a key (see below).
Check them:

```bash
bash ~/.claude/skills/demo-video/scripts/doctor.sh
```

### ElevenLabs key

Skip this if you're narrating with Kokoro. To use ElevenLabs:

1. On the [ElevenLabs Developers page](https://elevenlabs.io/app/developers), under API Keys,
   create a key. Restrict it to Text to Speech and Voices (read), and set a credit quota if you
   want a spending cap. `voices.py models` and `voices.py quota` need read access to models and
   to your user details as well; nothing else depends on those two commands.
2. Save it. Run this in your own terminal and paste the key at the prompt. It isn't shown or kept
   in your shell history, and the file is readable only by you:

   ```bash
   mkdir -p ~/.config/demo-video && (umask 077; printf "ElevenLabs key: "; read -rs key; echo; printf "ELEVENLABS_API_KEY=%s\n" "$key" > ~/.config/demo-video/elevenlabs.env)
   ```

   Or set `ELEVENLABS_API_KEY` in your environment, which wins over the file.
3. Check it. This is free, and prints River if the key works:

   ```bash
   uv run -q --no-project --with playwright python ~/.claude/skills/demo-video/scripts/voices.py list --search River
   ```

A key alone changes nothing: a demo uses ElevenLabs only when you name or save a voice.

## Smoke test

```bash
bash ~/.claude/skills/demo-video/examples/hello/run.sh
```

About three minutes. It records a terminal and a tiny web app, then writes
`~/Movies/demo-video/hello/final/hello.mp4` (about 21 s), plus `-script.md`,
`-picture.mp4` and `-preview.mp4`.

## What you get

| File | Use |
|---|---|
| `<out>.mp4` | The video with the placeholder narration, to hear the pacing |
| `<out>-picture.mp4` | The video without audio: record your voice-over over it |
| `<out>-script.md` | Each line with its start time and how many seconds it has |
| `<out>-preview.mp4` | A smaller copy for chat uploads |

The human voice-over and iMovie finish are manual: see
[voiceover-and-imovie.md](voiceover-and-imovie.md).

## Voices and pacing

```bash
python scripts/voices.py list --accent british     # every voice in your ElevenLabs account
python scripts/voices.py set River --stability 0.4 # save a voice and its settings
python scripts/fit.py <demo-folder> eleven:River   # how long does the picture outlast each line?
python scripts/assemble.py <demo-folder> out.mp4 eleven:River --fit   # cut it down to the lines
```

`SKILL.md` has the details. Voiced lines are cached in `~/.cache/demo-video/tts`, so only a
changed line is billed again.

## Layout

| Path | What |
|---|---|
| `SKILL.md` | The steps Claude follows |
| `scripts/` | `recorder.py` (record takes), `cut.py` (lay out shots), `assemble.py` (narrate and join), `tts.py` + `kokoro_lines.py` + `elevenlabs.py` (the voice), `voices.py` (list and choose voices), `fit.py` + `retime.py` (fit the picture to the narration), `stage.sh` + `term_mirror.py` (a clean terminal to record), `human.py` (a drawn cursor), `doctor.sh` |
| `examples/hello/` | The smoke test and the template to copy for your own demo |
| `troubleshooting.md` | Symptoms, causes and fixes |
| `tests/` | `uv run -q --no-project --with playwright --with pytest pytest tests` |

## License

MIT

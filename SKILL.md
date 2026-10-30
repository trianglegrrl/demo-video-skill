---
name: demo-video
description: Use when making a narrated product demo or screencast video of a product (terminal, web app, Teams or Slack windows), when real waits would bloat the video, when the Mac's screen is locked or OBS/screen capture records blank frames, when the narration should be an ElevenLabs voice, when the picture plays on in silence after a line ends, or when a person will record their own voice-over and finish the edit in iMovie.
---

# Demo video

A **headless recorder**: Playwright records every window (web app, terminal, chat) as its own
stream on one take clock; only the `clip` stretches are kept, laid out as windows on one
desktop; a voice reads the narration: Kokoro-82M (local, open-weight) as a placeholder, or an
ElevenLabs voice as the final read. For a placeholder, a person then reads the time-stamped
script as the real voice-over and finishes in iMovie. No screen capture: the Mac may be locked.

`SKILL` below means this skill's folder. Tools are in `SKILL/scripts/`.
`examples/hello/` is the smoke test and the template to copy.

## Running things

- Python: `export DEMO_VIDEO_SCRIPTS=SKILL/scripts` (required once a demo folder is
  copied out of the skill), and run every script, the skill's by full path, as
  `uv run -q --no-project --with playwright python <file>`. "`python`" below means that.
- Agent harness: tmux, local ports and Playwright need the sandbox off. Takes run for
  minutes: start them as background commands and wait for the completion notification
  (or watch the log with Monitor), never `sleep`.
- Stop what you start: `stage.sh stop <session>` and any local server you launched.

## Steps

1. **Preflight.** `bash SKILL/scripts/doctor.sh`, then `bash SKILL/examples/hello/run.sh`
   as is (it owns tmux `hellodemo`, ports 7692 and 8795, and `~/Movies/demo-video/hello`).
   Done when it prints `.../hello.mp4  (0:2x.x)`. If it fails, nothing else will work.
2. **Script first.** Copy `examples/hello/demo.py` and `scenes.py` (not `run.sh`, the
   smoke test's runner) into a folder of your own. In `demo.py` set `TITLE`, `OUT`,
   `PROFILES` (a folder of its own: two demos sharing one collide), `TMUX`, `STREAMS`
   (at most 4) and `SCENES`: one take per scene, **one line per clip** (`None` = silent).
   Budget ~2.7 words a second for Kokoro, ~3 for ElevenLabs (`fit.py` measures the voice you pick)
   against the length asked for. Write the lines
   in the voice of the person who will read them (their voice skill, if they have one): full
   spoken sentences, plain words, not captions. A word Kokoro gets wrong takes its
   pronunciation inline, `[frontmatter](/fɹˈʌntmætəɹ/)`; the script shows just the word.
   Public-facing: no customer or prospect names. Review the lines as an expert in the
   audience's job would ("Act as a <their role> with fifteen years in the job…"):
   wrong numbers, vague timings ("a few minutes"), claims a practitioner would doubt.
   Done when the person approves the lines. If you can't ask, go on and mark the lines
   **unapproved** in the handoff.
3. **Scenes.** One function per take in `scenes.py`. A `with t.clip(label, focus):` holds
   only what the viewer should see. Long waits (a job, a model answering) go **between**
   clips; a short wait for output to appear can sit inside a clip with
   `t.until(pattern, timeout, poll=0.3)`. A wait of a few seconds that shows progress (a
   spinner, "checking…") can stay on camera; cut it otherwise, and let the line say so
   ("six seconds later…"): only cuts of 20 s or more get an on-screen "+N s" tag. Before the first clip, off camera: reset what the
   last take left (stop jobs, mark notifications read; `Take` clears the tmux scrollback)
   and load slow apps. Point with `human` (headless draws no pointer): `human.cursor(page)`
   once per page, `human.click`/`human.move`/`human.hover` (curved, Fitts-timed, landing off-centre; a
   hover-only button: `human.reveal(page, parent)`, then `click(page, button, within=parent)`)
   and `human.wheel`; hold a reading shot with `human.idle(page, seconds)`, not `time.sleep`, so
   the cursor drifts a few pixels instead of freezing. A frozen page also stops the browser's
   recording early: Chromium writes a frame only when something changes. A stream behind a
   login either signs in once by hand (`python SKILL/scripts/recorder.py signin <demo-folder>
   <stream>`, for MFA) or in its `prepare` on every take.
4. **Record and look.** `bash SKILL/scripts/stage.sh start <session> <port> [cwd]
   [highlight-regex]` (a clean `$ ` shell plus its mirror; it refuses a busy session or port),
   start any local servers, run each take, then `python SKILL/scripts/cut.py <demo-folder>
   <take>` and pull frames from `OUT/<take>/<take>-desktop.mp4` (`ffmpeg -ss T -frames:v 1`). A take
   that fails keeps the previous good one; its partial recording is in `OUT/<take>.partial`.
   **Look at them.** Done when every shot shows what its line says: no blank terminal, no
   login page, no splash screen, text readable.
5. **Fit and assemble.** Each shot runs for its clip or its line, whichever is longer, so a line
   shorter than its footage leaves the picture playing in silence. Measure that first (see
   [Voices and fit](#voices-and-fit)): `python SKILL/scripts/fit.py <demo-folder> [voice]`.
   Where it says to add words, write them in the reader's voice and have the person approve them,
   as in step 2; where it says a last frame freezes, shorten the line. Voiced lines are cached, so
   re-running is quick and bills only changed lines. Then `python SKILL/scripts/assemble.py
   <demo-folder> <out.mp4> [voice] --fit`. The first Kokoro run downloads the model (~330 MB)
   and takes a minute; after that it voices faster than real time. Writes `<out>.mp4` (narrated),
   `-script.md` (each line's start and its seconds), `-picture.mp4` (no audio) and
   `-preview.mp4`. Too short: lengthen the holds inside clips and re-record those takes; `cut.py`
   prints a take's footage length. Done when the length is on target and a frame per scene
   shows its payoff: fitting cuts stills, so check nothing that matters was one.
6. **Hand off.** An ElevenLabs read can be the finished video: hand over `<out>.mp4`. For a human
   read: `-picture.mp4` (record over it), `-script.md`, the narrated `.mp4` (to hear the pacing
   once) and [voiceover-and-imovie.md](voiceover-and-imovie.md); assemble that one without `--fit`
   or with `--pause 2`, since a human reads slower than the voice it was fitted to. In chat, send
   `-preview.mp4` (uploads cap at 30 MB). The script's times hold for the voice used.

## Voices and fit

**Picking a voice.** `[voice]` is a Kokoro name (`af_heart`, the default; `bf_emma` is British),
`eleven:<name or id>` (`eleven:River`; plain `eleven` is River), or any other name for
`say -v '?'`. The order: the command line, `VOICE` in demo.py, the saved choice, Kokoro.
ElevenLabs sends the lines to a third party and bills characters, so a key alone never turns it
on: it runs only when named, and a saved voice counts, sending every later demo's lines. Never use
it for a script the person hasn't cleared to leave the Mac. It needs `ELEVENLABS_API_KEY`, or
that line in `~/.config/demo-video/elevenlabs.env` (mode 600).

    python SKILL/scripts/voices.py list [--search TEXT] [--gender G] [--accent A]
    python SKILL/scripts/voices.py say Matilda "A line to audition." --out try.wav  # bills the line
    python SKILL/scripts/voices.py set Matilda --stability 0.4     # saved for every demo
    python SKILL/scripts/voices.py get | show <voice> | models | quota

`set` takes `--model`, `--stability`, `--similarity`, `--style`, `--speed` and
`--speaker-boost`, for that voice only; one demo overrides them with `VOICE_SETTINGS = {"model": ..., "stability": ...}`
in demo.py. The default model, `eleven_v4`, ignores `--speed` (so does `eleven_v3`;
`eleven_turbo_v2_5` honours it), and it reads `[word](/ipa/)` inline: audition those words. A
voice cloned from a real person needs that person's permission: never pick one on your own.

**Fitting.** A shot should run for its speech plus `--pause` (1 s: a person changing gears).
`--fit` takes up the rest in order: cut what is still in the front window (`human.idle` drift
counts as still; clicks, moves and new text do not; a dimmed window behind it isn't looked at), then speed up what remains, to
`--max-speed` (1.5; a shot's own `speeds` is a floor). What's left is for the line: `fit.py` reports
it as words to add, and never writes them. A shot's last second is never cut. A shot with no line holds 3 s under `--fit`.

## Changing a shot later

Re-record only that take (step 4) and re-assemble; other takes are reused as recorded. A
wording change needs only step 5, and re-voices only that line.

## When it breaks

[troubleshooting.md](troubleshooting.md): blank terminal, wrong cue matched, Teams refusing
the browser, a shot rendering for minutes, ffmpeg filter errors, small text, a background
window that looks black.

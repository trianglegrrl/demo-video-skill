---
name: demo-video
description: Use when making a narrated product demo or screencast video of a product (terminal, web app, Teams or Slack windows), when real waits would bloat the video, when the Mac's screen is locked or OBS/screen capture records blank frames, or when a person will record their own voice-over and finish the edit in iMovie.
---

# Demo video

A **headless recorder**: Playwright records every window (web app, terminal, chat) as its own
stream on one take clock; only the `clip` stretches are kept, laid out as windows on one
desktop; Kokoro-82M (a local, open-weight voice) reads a placeholder narration; a person then reads the time-stamped
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
   Budget ~2.7 words a second (Kokoro's pace) against the length asked for. Write the lines
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
5. **Assemble.** `python SKILL/scripts/assemble.py <demo-folder> <out.mp4> [voice]`
   (voice: a Kokoro voice, default `af_heart`; `bf_emma` is British; any other name is a
   `say -v '?'` voice). The first Kokoro run downloads the model (~330 MB) and takes a
   minute; after that it voices faster than real time. Writes `<out>.mp4` (narrated),
   `-script.md` (each line's start and its seconds), `-picture.mp4` (no audio) and
   `-preview.mp4`. Too long: shorten **lines**, since a long line holds the shot's last
   frame. Too short: lengthen the holds inside clips and re-record those takes. Each shot runs for
   its clip or its line, whichever is longer; `cut.py` prints a take's footage length.
   Done when the length is on target and a frame per scene checks out.
6. **Hand off.** To the person: `-picture.mp4` (record over it), `-script.md`, the
   narrated `.mp4` (to hear the pacing once) and
   [voiceover-and-imovie.md](voiceover-and-imovie.md). In chat, send `-preview.mp4`
   (uploads cap at 30 MB). The script's times hold for Kokoro; a human reads slower, and
   iMovie absorbs that.

## Changing a shot later

Re-record only that take (step 4) and re-assemble; other takes are reused as recorded. A
wording change needs only step 5.

## When it breaks

[troubleshooting.md](troubleshooting.md): blank terminal, wrong cue matched, Teams refusing
the browser, a shot rendering for minutes, ffmpeg filter errors, small text, a background
window that looks black.

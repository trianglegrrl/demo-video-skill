# Troubleshooting

Each row was hit for real while making a 5-minute product demo with this pipeline.

## Recording

| Symptom | Cause | Fix |
|---|---|---|
| OBS or `screencapture` frames are blank; "Invalid target display ID" | the Mac's screen is locked | don't screen-capture: record headless with `recorder.Take` (this skill's whole design) |
| A browser recording opens signed out | a fresh browser context has no cookies | persistent profiles (`PROFILES` in demo.py); sign in once with `recorder.py signin`, or sign in off camera in the stream's `prepare` |
| The terminal window goes blank for the rest of a take | ttyd's xterm.js canvas stops repainting in headless Chromium after `clear` | use `term_mirror.py` (HTML page that polls `tmux capture-pane`), never ttyd |
| `goto` times out waiting for "networkidle" on the terminal | the mirror page polls forever | `Take` waits for "load"; don't add networkidle waits on a polling page |
| The shell prompt shows a user name, host or path; `until_prompt` never returns | the session runs the user's own shell and prompt | start the session with `stage.sh start` (bash, prompt `$ `) |
| A take's cue fires at once on the previous run's output | `until` reads the tmux scrollback | `Take` runs `clear` + `clear-history` on entry; call `t.clear_terminal()` before a second command in one take |
| A cue matches an old notification | the app keeps earlier takes' notices | mark everything read off camera before the first clip; match only unread items |
| A user never gets the notification you wait for | the system routes it to a different account than the one signed in | find who the job really belongs to; sign that stream in as them |
| `;` disappears from typed commands | tmux reads a lone `;` as its own separator | `t.type` escapes it; when calling `tmux send-keys` yourself, send `\;` |
| Text unreadable in the video | recorded at a large viewport, scale 1 | 1280×720 viewport at device scale 1.5 (the `recorder.py` default), upscaled to 1080p |
| No mouse pointer; clicks look robotic | headless draws no cursor | `human.cursor(page)` once per page, then `human.click`/`human.move`/`human.wheel` |
| The cursor fails to draw in one app | Trusted Types forbids `innerHTML` | `human.py` builds it with DOM calls already; keep it that way |
| Teams: "browser not supported"; the deep link stops at a launcher | Teams refuses a headless user agent; the link offers the desktop app | `desktop_ua: True` on the stream; click "Use the web app instead" |
| Teams: a reply or menu button is not found | the actions only appear on hover, at the message's top edge | scroll the message top into view, hover, then click |
| The wrong bot answers an @mention | the name matches a team or another environment's bot | type enough of the name to pick the exact app, and match the option by its full name |
| A slow app's splash screen is in the shot | it loaded on camera | load it in the off-camera setup, before the first clip |
| `ModuleNotFoundError: playwright` | ran with the system Python | `uv run -q --no-project --with playwright python <file>` |
| Background windows look like black rectangles | only their edges show from behind the front window, and they are dimmed: a dark page reads as black | expected; it reads as other windows on the desktop |
| The "+N s" tag covers a background window's title bar | the tag sits top right, over the top-right slot | cosmetic; left as is |
| A shot has a second or two of dead footage before its output | `t.until` polls every 2 s by default | inside a clip, pass `poll=0.3` |
| A port check says the port is in use | another server (or a previous mirror) holds it | stop it, or give the demo a different port; never record a stale server's page |

## Cutting and assembling

| Symptom | Cause | Fix |
|---|---|---|
| A 10 s shot renders for minutes; assembly runs 20+ min | `overlay=shortest=1` alone did not cap a long stream | `cut.render` caps with `-t` and asserts the length; keep both |
| ffmpeg: "No option name near …" | `:` (or `'`) in on-screen text | `cut._text` refuses them; use an em dash in titles |
| ffmpeg: "Input area … not within the padded area" | odd frame heights with yuv420p | heights computed even (`width * 9 // 32 * 2`); keep window widths from `SLOTS`/`FRONT` |
| `assemble.py`: "N shots but M lines" | a scene's clips and its lines drifted | one line per clip, `None` for a silent clip |
| The video runs over the target length | lines longer than their shots hold the last frame | shorten lines; `speeds` in a scene plays a long reading or typing shot faster (1.2–1.7) |
| A line sounds rushed | it needs well over 175 wpm for its shot | rewrite it shorter; don't speed the voice |
| `SyntaxError` in demo.py after an edit | an apostrophe inside a single-quoted string | write lines in double quotes |
| `say` mispronounces a word ("sweep" as "suite") | the TTS voice | leave it: the human voice-over replaces it |
| The full video is too big to send in chat (30 MB cap) | 1080p crf 18 | send `-preview.mp4` (crf 26, ~18 MB for 5 min) |

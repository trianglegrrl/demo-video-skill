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
| No mouse pointer; clicks look robotic (straight-line glide, dead-centre click, frozen cursor) | headless draws no cursor, and a CSS transition moves in a straight line at one speed | `human.cursor(page)` once per page, then `human.click`/`human.move`/`human.hover`/`human.wheel`: moves bow on a curve, take Fitts's-law time, ease in and out, overshoot and correct on long moves, stay on screen, and land in the middle 60% of the target's first line after a varied pause; the real mouse follows the path so hovers fire. Hold shots with `human.idle(page, s)`: any hold of 0.4 s or more drifts a few px. Moves are seeded per page URL (`cursor(page, seed=...)` to override), so a re-record moves the same way |
| `shot '…' rendered 2.3s, expected 3.8s` | the shot ends on a still page: Chromium's recorder writes a frame only when something changes, so the stream's file stops early | hold with `human.idle(page, s)`, not `time.sleep`; the drifting cursor keeps frames coming |
| The click lands off the drawn cursor, between the lines of wrapped text, or under a list's edge | `Locator.click()` clicks the element's centre (`position=` counts from inside the border); a wrapped link's box centre is empty space; a scroll container hides part of a box | `human.click` aims inside the first client rect, cut to what its scroll containers show, trial-checks that exact point with Playwright, and clicks it with `page.mouse.click`; keep it |
| `click target kept moving` | the element moved more than 2 px three times after the cursor reached it (a list still re-rendering) | wait off camera for the view to settle (a `wait_for` on the final content) before the clip |
| A hover-only button vanishes before the click (a message's hover toolbar) | the path to it bowed out of the element whose hover shows it, or Playwright scrolled that element away | `human.reveal(page, parent)`, `human.hover(page, msg, at=...)`, then `human.click(page, button, within=parent)`, where `parent` is the element that keeps the button shown. The path stays inside `parent`, straight, and Playwright never scrolls the button |
| Playwright loops "element is outside of the viewport … retrying click action (trial run)" on a hover toolbar | the message's top is scrolled off, so its toolbar is drawn off screen | `human.reveal(page, parent)` first: it scrolls the parent's top into view smoothly, waits in the page (up to 3 s) until it lands and holds still, accepts a list that can scroll no further, and fails loudly otherwise. Don't add a `Locator.hover()`/`click()` without `position=` after it: Playwright scrolls to the element's centre and undoes the reveal |
| `click target does not take the click at (x, y)` | Playwright's trial at the exact drawn point found something else on top (an overlay, a toast), even after one re-aim | close the overlay off camera, or wait for it to go, before the clip |
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
| A line sounds rushed | it needs well over ~2.7 words a second for its shot | rewrite it shorter; don't speed the voice |
| `SyntaxError` in demo.py after an edit | an apostrophe inside a single-quoted string | write lines in double quotes |
| Kokoro mispronounces a word (a term of art, a product name) | it isn't in Kokoro's dictionary | give it a pronunciation inline: `[frontmatter](/fɹˈʌntmætəɹ/)` (IPA, as in the Kokoro README); re-assemble |
| Assemble fails in `uv run … kokoro` | no network on the first run: the model downloads from Hugging Face, and misaki installs spaCy's `en_core_web_sm` (again whenever uv rebuilds Kokoro's environment); or no Python 3.12 for uv | run once online; `uv python install 3.12` |
| The picture plays on for seconds after a line ends | the shot runs for its footage, and the line is shorter | `fit.py` shows how much; `assemble.py --fit` cuts it down; add words where it says the picture can't absorb the rest |
| `--fit` cut something that mattered | it changed only a cursor-sized patch of the front window (a spinner, a one-character counter) or happened in a window behind it, so it read as still | keep that moment out of the cut: give the line more words, or assemble with a higher `--pause` |
| `doctor.sh`: MISSING ffmpeg drawtext filter | Homebrew's plain `ffmpeg` formula is built without freetype, so reinstalling it doesn't help | `brew install ffmpeg-full`, then put `$(brew --prefix ffmpeg-full)/bin` first on `PATH` |
| `no ElevenLabs key` | neither the environment nor the key file has it | follow "Setting up ElevenLabs" in [SKILL.md](SKILL.md#voices-and-fit) |
| `ElevenLabs refused …: 401` or `: 422` | a bad or restricted key, or an old `ELEVENLABS_API_KEY` in the environment hiding the file (401); a setting out of range or a wrong model (422: the message says which) | the key needs Text to Speech and Voices (read), and `voices.py models` and `quota` need read access to models and user details; `voices.py models` lists the model ids |
| `--speed` changes nothing | `eleven_v4` and `eleven_v3` accept it and ignore it | use `eleven_turbo_v2_5`, or change the words |
| An ElevenLabs voice says a word wrongly | the inline IPA varies by voice and phrase | audition with `voices.py say`; respell the word in the line (`trapezIi`) if IPA won't land |
| `voices.py quota` doesn't move after voicing | the counter lags | `/v1/history` is the live record |
| The full video is too big to send in chat (30 MB cap) | 1080p crf 18 | send `-preview.mp4` (crf 26, ~18 MB for 5 min) |

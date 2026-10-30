# Human voice-over and the iMovie finish

How a 5-minute demo made with this pipeline was finished: one person, iMovie on a Mac. The
pipeline hands over three files:

| File | Use |
|---|---|
| `<out>-picture.mp4` | The video, no audio. The master you record over. |
| `<out>-script.md` | What to say. `**1:42.5** (app, 6.1 s) Some jobs shouldn't…`: start at 1:42.5, about 6 s to say it. |
| `<out>.mp4` | The same video with the placeholder Kokoro voice: play it once to hear the pacing. |

## Record

1. iMovie → File → New Movie. Import `<out>-picture.mp4` and drag it to the timeline.
2. Open `-script.md` beside iMovie (a second screen or a printout).
3. Click the microphone under the viewer (Record Voiceover). In its options pick the mic
   and tick **Mute Project**.
4. Put the playhead at the start and record **one continuous take** of the whole script,
   starting each line near its time. Hitting the times roughly is enough: a line that runs
   long is fixed in the edit, not by rushing. Wording that reads badly aloud can change as
   you go.

A 5-minute video took one 5-minute recording.

## Edit

- **Re-record a line**: put the playhead at the line, record a short voiceover, then cut
  the old stretch out of the long take: select the voiceover clip, Modify → Split Clip
  (⌘B) at both ends, and delete the middle. Done this way for an intro and one
  mid-video line.
- **Dead space**: split the video clip around a pause no line covers and delete it. Move the
  voiceover clips left to close the gap.
- **A line longer than its shot**: split the video at the shot's last frame and drag the
  clip end longer (or Modify → Add Freeze Frame), so the picture waits for the voice.
- If you imported the narrated `<out>.mp4` instead of `-picture`, set its clip volume to 0
  (or Modify → Detach Audio and delete the placeholder track) so the voices do not overlap.

## Export

File → Share → File…, at 1080p (the size the pipeline renders). Save it wherever you like, e.g. the Desktop.

## Not automated

The human voice-over and the iMovie edit are manual by design: the person's read sets the
final pacing. The pipeline does not re-time the video to a recorded voice: `--fit` works from the
synthetic voice's timing, which leaves a slower human reader too little room, so assemble
`-picture.mp4` for a human read without it, or with `--pause 2`.

"""Fit to narration: the plan for one shot, finding the stills, and the report.

    uv run -q --no-project --with playwright --with pytest pytest tests
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cut  # noqa: E402
import fit  # noqa: E402
import retime  # noqa: E402
from cut import Shot  # noqa: E402


def _shot(seconds: float = 20.0, speed: float = 1.0, gap: float = 30.0) -> Shot:
    return Shot("x", "app", 100.0, 100.0 + seconds, gap, speed)


def _played(result: retime.Fit) -> float:
    return sum(p.length for p in result.pieces)


def test_a_shot_with_no_dead_air_is_left_exactly_as_it_was():
    shot = _shot(5.0)
    result = retime.plan(shot, [(100.0, 105.0)], target=6.0)
    assert result.pieces == (shot,) and result.dead < 0 and result.left == 0.0


def test_a_shot_within_the_slop_is_not_worth_a_cut():
    shot = _shot(6.1)
    assert retime.plan(shot, [(100.0, 106.1)], target=6.0).pieces == (shot,)


def test_stills_are_cut_first_and_nothing_is_sped_up_when_they_cover_it():
    result = retime.plan(_shot(20.0), [(105.0, 118.0)], target=10.0)
    assert result.speed == 1.0 and result.left == 0.0
    assert _played(result) == pytest.approx(10.0)
    assert result.cut == pytest.approx(10.0)


def test_motion_outside_the_stills_is_never_cut():
    result = retime.plan(_shot(20.0), [(105.0, 118.0)], target=10.0)
    kept = [(p.t0, p.t1) for p in result.pieces]
    assert kept[0][0] == 100.0 and kept[0][1] > 105.0, f"the motion before the still went: {kept}"
    assert kept[-1][1] == 120.0, f"the motion after the still went: {kept}"


def test_a_cut_still_keeps_a_beat_at_its_start():
    result = retime.plan(_shot(20.0), [(105.0, 118.0)], target=10.0)
    assert result.pieces[0].t1 >= 105.0 + retime.BEAT, result.pieces


def test_a_still_ending_the_shot_keeps_its_hold_so_the_payoff_is_seen():
    result = retime.plan(_shot(20.0), [(110.0, 120.0)], target=11.0)
    last = result.pieces[-1]
    assert last.t1 == 120.0 and last.t1 - last.t0 >= retime.END_HOLD, result.pieces


def test_a_still_the_scan_ends_just_short_of_the_shot_still_keeps_its_hold():
    """The scan steps a tenth of a second, so a still running to the end reads a little short.
    Treated as mid-shot, it lost the payoff and left a 0.01 s piece with no frames to render."""
    result = retime.plan(_shot(20.0), [(110.0, 119.99)], target=11.0)
    last = result.pieces[-1]
    assert last.t1 == 120.0 and last.t1 - last.t0 >= retime.END_HOLD, result.pieces


def test_a_final_still_split_by_a_keyframe_cannot_lose_the_shots_end():
    """A keyframe near the end splits the last still, so it looks like it ends mid-shot."""
    result = retime.plan(_shot(20.0), [(105.0, 119.6)], target=5.6)
    last = result.pieces[-1]
    assert last.t1 == 120.0 and last.t1 - last.t0 >= retime.END_HOLD, result.pieces


def test_a_tagged_shot_keeps_its_tag_on_screen():
    result = retime.plan(_shot(20.0, gap=45.0), [(100.0, 118.0)], target=5.0)
    assert result.pieces[0].t1 - result.pieces[0].t0 == pytest.approx(cut.TAG_S), result.pieces


def test_an_untagged_shot_can_cut_right_after_its_beat():
    result = retime.plan(_shot(20.0, gap=0.0), [(100.0, 118.0)], target=5.0)
    assert result.pieces[0].t1 == pytest.approx(100.0 + retime.BEAT), result.pieces


def test_the_longest_stills_are_cut_first():
    result = retime.plan(_shot(20.0), [(101.0, 103.0), (105.0, 118.0)], target=15.0)
    assert len(result.pieces) == 2, f"one cut, in the long still, covers it: {result.pieces}"
    assert result.pieces[0].t1 > 105.0


def test_speed_takes_up_what_the_stills_could_not():
    result = retime.plan(_shot(12.0), [], target=10.0)
    assert result.speed == pytest.approx(1.2) and result.left == 0.0
    assert _played(result) == pytest.approx(10.0)


def test_speed_stops_at_the_cap_and_the_rest_is_reported_for_words():
    result = retime.plan(_shot(30.0), [], target=10.0, max_speed=1.5)
    assert result.speed == 1.5, result
    assert result.left == pytest.approx(10.0), "30 s at 1.5x is 20 s, 10 s over the target"


def test_an_authors_speed_is_the_floor():
    result = retime.plan(_shot(10.0, speed=2.0), [], target=4.0, max_speed=1.5)
    assert result.speed == 2.0, "fit must never slow a shot the author sped up"
    assert result.left == pytest.approx(1.0)


def test_an_authors_speed_counts_toward_the_dead_air():
    shot = _shot(10.0, speed=2.0)
    assert retime.plan(shot, [], target=5.0).pieces == (shot,), "10 s at 2x already plays in 5 s"


def test_cuts_are_measured_in_footage_when_the_author_sped_the_shot():
    result = retime.plan(_shot(20.0, speed=2.0), [(102.0, 118.0)], target=5.0)
    assert _played(result) == pytest.approx(5.0)
    assert result.speed == 2.0 and result.cut == pytest.approx(10.0)


def test_only_the_first_piece_carries_the_cut_wait_tag():
    result = retime.plan(_shot(20.0, gap=45.0), [(105.0, 118.0)], target=10.0)
    assert [p.gap for p in result.pieces] == [45.0] + [0.0] * (len(result.pieces) - 1)


def test_a_cut_too_small_to_matter_is_skipped():
    result = retime.plan(_shot(10.0), [(102.0, 102.0 + retime.BEAT + 0.1)], target=8.0)
    assert len(result.pieces) == 1 and result.cut == 0.0, result


def test_a_still_past_the_shot_is_ignored():
    result = retime.plan(_shot(10.0), [(150.0, 170.0)], target=8.0)
    assert result.cut == 0.0 and result.pieces[0].t1 == 110.0, result


def test_pieces_are_in_order_and_do_not_overlap():
    result = retime.plan(_shot(40.0), [(102.0, 110.0), (115.0, 125.0), (130.0, 138.0)], target=12.0)
    spans = [(p.t0, p.t1) for p in result.pieces]
    assert spans == sorted(spans) and all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), spans


@pytest.mark.parametrize(("speech", "pause", "target"), [(4.0, 1.0, 5.0), (4.0, 1.5, 5.5), (None, 1.0, 3.0)],
                         ids=["line", "longer-pause", "silent-shot"])
def test_the_target_is_the_speech_plus_the_pause_or_a_short_silent_hold(speech, pause, target):
    assert retime.target_for(speech, pause) == target


def _clip(path: Path) -> None:
    """Six seconds of a dark page: a cursor-sized box blinking throughout (a drifting cursor), and
    a wide bar of text on screen from 2 s to 3 s only."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=0x1b1e24:s=1280x720:r=25:d=6", "-vf",
                    "drawbox=x=600:y=300:w=16:h=16:color=white:t=fill:enable='lt(mod(t,0.8),0.4)',"
                    "drawbox=x=100:y=500:w=900:h=30:color=white:t=fill:enable='between(t,2,3)'",
                    "-c:v", "libvpx", "-b:v", "2M", str(path)], check=True)


def test_stills_are_found_around_real_changes_and_through_cursor_drift(tmp_path, ffmpeg):
    video = tmp_path / "app.webm"
    _clip(video)
    found = retime.stills(video, 0.0, 6.0)
    assert len(found) == 3 or len(found) == 2, f"split at the bar's arrival and exit: {found}"
    assert found[0][0] < 0.5 and 1.7 < found[0][1] < 2.3, f"the first still ends as the bar arrives: {found}"
    assert found[-1][1] > 5.5 and 2.7 < found[-1][0] < 3.5, f"the last starts as the bar leaves: {found}"


def test_stills_are_measured_from_the_start_asked_for(tmp_path, ffmpeg):
    video = tmp_path / "app.webm"
    _clip(video)
    found = retime.stills(video, 3.5, 2.0)
    assert found and found[0][0] < 0.3 and found[-1][1] > 1.6, f"offsets from 3.5 s, not from 0: {found}"


def _report_rows() -> list[fit.Row]:
    return [fit.Row("s1", 0, _shot(20.0), "One two three four five six.", 2.0,
                    retime.plan(_shot(20.0), [(105.0, 118.0)], target=3.0)),
            fit.Row("s1", 1, _shot(2.0), "A line far too long for its footage to carry.", 6.0,
                    retime.plan(_shot(2.0), [], target=7.0))]


def test_the_report_turns_what_the_picture_cannot_absorb_into_a_word_count():
    assert fit.words_to_add(4.0, words_per_second=3.0) == 12
    assert fit.words_to_add(0.0, words_per_second=3.0) == 0


def test_the_pace_is_measured_from_this_voices_own_lines():
    assert fit.pace(_report_rows()) == pytest.approx((6 + 10) / (2.0 + 6.0))


def test_the_report_shows_each_shots_dead_air_and_flags_a_frozen_frame():
    text = fit.report(_report_rows())
    assert "s1 #0" in text and "s1 #1" in text, text
    assert "17.0" in text, f"20 s of footage against a 3 s target: {text}"
    assert "freezes" in text, f"a line longer than its footage must be flagged: {text}"


def test_a_pause_too_short_for_the_air_around_a_line_is_refused():
    with pytest.raises(SystemExit, match="--pause"):
        retime.Pacing(pause=0.2)


def test_a_max_speed_below_one_is_refused():
    with pytest.raises(SystemExit, match="--max-speed"):
        retime.Pacing(max_speed=0.5)


def test_a_fitted_shot_renders_to_the_planned_length(tmp_path, drawtext):
    for name in ("term", "app"):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc=size=320x180:rate=30:duration=20", "-c:v", "libvpx",
                        str(tmp_path / f"{name}.webm")], check=True)
    demo = SimpleNamespace(DESKTOP_LABEL="Test desktop",
                           STREAMS={"term": {"title": "Terminal"}, "app": {"title": "App"}})
    bg, out = tmp_path / "bg.png", tmp_path / "shot.mp4"
    cut.wallpaper(demo, bg)
    result = retime.plan(Shot("x", "app", 2.0, 18.0, 0.0), [(5.0, 15.0)], target=9.0)
    assert len(result.pieces) == 2, result

    retime.render_pieces(demo, tmp_path, result.pieces, {"term": 0.0, "app": 0.0}, bg, out)

    assert abs(cut.duration(out) - 9.0) < 0.3, cut.duration(out)

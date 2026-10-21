"""The demo-video pipeline's own logic: shots from a take's events, the cut-wait tag, on-screen
text, the pre-render check, and one real render against ffmpeg.

    uv run -q --no-project --with playwright --with pytest pytest tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import assemble  # noqa: E402
import cut  # noqa: E402
from recorder import load_demo  # noqa: E402


def _events(*rows: tuple) -> list[dict]:
    return [{"t": t, "kind": kind, **fields} for t, kind, fields in rows]


def test_shots_keep_only_clips_and_measure_the_cut_wait_before_each():
    events = _events((0.2, "start", {"stream": "term"}), (2.0, "clip", {"label": "a", "focus": "term"}),
                     (5.0, "clipend", {"label": "a"}), (45.0, "clip", {"label": "b", "focus": "term"}),
                     (48.0, "clipend", {"label": "b"}))
    a, b = cut.shots(events, {"b": 1.5})
    assert (a.t0, a.t1, a.gap, a.length) == (2.0, 5.0, 0.0, 3.0)
    assert (b.gap, b.speed, b.length) == (40.0, 1.5, 2.0)


def test_an_unclosed_clip_is_not_a_shot():
    events = _events((1.0, "clip", {"label": "a", "focus": "term"}), (9.0, "end", {}))
    assert cut.shots(events) == []


@pytest.mark.parametrize(("gap", "tag"), [(24.4, "+24 s"), (89.4, "+89 s"), (90.0, "+2 min"),
                                          (600.0, "+10 min")])
def test_the_cut_wait_tag_says_seconds_under_a_minute_and_a_half(gap, tag):
    assert cut.jump(gap) == tag


@pytest.mark.parametrize("text", ["a: b", "it's", "50%", "back\\slash"])
def test_on_screen_text_refuses_what_ffmpeg_filters_would_misread(text):
    with pytest.raises(ValueError):
        cut._text(text)


def test_on_screen_text_passes_an_em_dash_title():
    assert cut._text("Terminal — build") == "Terminal — build"


def _demo(tmp_path: Path, lines: list) -> SimpleNamespace:
    take = tmp_path / "s1"
    take.mkdir()
    rows = [{"t": 0.1, "kind": "start", "stream": "term"},
            {"t": 1.0, "kind": "clip", "label": "x", "focus": "term"},
            {"t": 3.0, "kind": "clipend", "label": "x"}]
    (take / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return SimpleNamespace(OUT=tmp_path, SCENES=[{"take": "s1", "lines": lines}])


def test_check_refuses_a_scene_whose_lines_do_not_match_its_clips(tmp_path):
    with pytest.raises(SystemExit, match="1 shots but 2 lines"):
        assemble.check(_demo(tmp_path, ["one", "two"]))


def test_check_refuses_a_take_that_was_never_recorded(tmp_path):
    demo = _demo(tmp_path, ["one"])
    demo.SCENES.append({"take": "s2", "lines": ["two"]})
    with pytest.raises(SystemExit, match="s2: not recorded"):
        assemble.check(demo)


def test_check_passes_one_line_per_clip(tmp_path):
    assemble.check(_demo(tmp_path, ["one"]))


def test_load_demo_finds_demo_py_from_a_scene_file_and_its_helpers(tmp_path):
    (tmp_path / "helper.py").write_text("VALUE = 7\n")
    (tmp_path / "demo.py").write_text("from helper import VALUE\nOUT = '~/x'\nN = VALUE\n")
    demo = load_demo(tmp_path / "scenes.py")
    assert demo.N == 7 and demo.OUT == Path.home() / "x"


def test_the_stamp_reads_minutes_and_tenths():
    assert assemble.stamp(3.25) == "0:03.2" and assemble.stamp(122.5) == "2:02.5"


def test_render_caps_a_shot_at_its_clip_length_even_when_a_stream_runs_long(tmp_path, ffmpeg):
    """A 30 s stream behind a 2 s clip must render 2 s, not run on (overlay's shortest=1 alone
    once let a 10 s shot render 348 s)."""
    for name, seconds in (("term", 30), ("app", 30)):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"testsrc=size=320x180:rate=30:duration={seconds}", "-c:v", "libvpx",
                        str(tmp_path / f"{name}.webm")], check=True)
    demo = SimpleNamespace(DESKTOP_LABEL="Test desktop",
                           STREAMS={"term": {"title": "Terminal"}, "app": {"title": "App"}})
    bg, out = tmp_path / "bg.png", tmp_path / "shot.mp4"
    cut.wallpaper(demo, bg)
    shot = cut.Shot("x", "app", 5.0, 7.0, 30.0)
    cut.render(demo, tmp_path, shot, {"term": 0.0, "app": 0.0}, bg, out)
    assert abs(cut.duration(out) - 2.0) < 0.2


def _blank_demo(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(OUT=tmp_path / "takes", PROFILES=tmp_path / "profiles", TMUX="",
                           STREAMS={"app": {"title": "App"}})


def test_a_take_that_fails_keeps_the_last_good_take(tmp_path, chromium_launches):
    """Re-recording one take must not cost the good one when the new attempt dies."""
    from recorder import Take
    demo = _blank_demo(tmp_path)
    with Take("s1", demo) as t:
        with t.clip("good", "app"):
            pass
    good = (demo.OUT / "s1" / "events.jsonl").read_text()
    with pytest.raises(TimeoutError):
        with Take("s1", demo) as t:
            raise TimeoutError("the cue never came")
    assert (demo.OUT / "s1" / "events.jsonl").read_text() == good
    assert (demo.OUT / "s1.partial" / "events.jsonl").exists()


def test_a_take_that_ends_cleanly_replaces_the_old_one(tmp_path, chromium_launches):
    from recorder import Take
    demo = _blank_demo(tmp_path)
    for label in ("first", "second"):
        with Take("s1", demo) as t:
            with t.clip(label, "app"):
                pass
    assert "second" in (demo.OUT / "s1" / "events.jsonl").read_text()
    assert (demo.OUT / "s1" / "app.webm").exists() and not (demo.OUT / "s1.partial").exists()

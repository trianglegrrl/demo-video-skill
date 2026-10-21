"""The on-camera cursor: curved, Fitts-timed paths, landing inside the target, idle drift, eased
scrolling. The path planner is pure; move/click/idle/wheel run against a fake page that records
what a real Playwright page would be asked to do (no browser, no real sleeps).

    uv run -q --no-project --with playwright --with pytest pytest .claude/skills/demo-video/tests
"""
from __future__ import annotations

import itertools
import math
import random
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import human  # noqa: E402
from playwright.sync_api import TimeoutError as PlaywrightTimeout  # noqa: E402

SEEDS = range(40)


def _perp_and_along(path, start, end):
    """Each point's distance off the start-end line, and how far along it it sits."""
    (sx, sy), (ex, ey) = start, end
    d = math.hypot(ex - sx, ey - sy)
    ux, uy = (ex - sx) / d, (ey - sy) / d
    return [(abs((x - sx) * uy - (y - sy) * ux), (x - sx) * ux + (y - sy) * uy) for _, x, y in path]


def _plan(start, end, seed, w=40, h=40):
    return human.plan_path(start, end, target_w=w, target_h=h, rng=random.Random(seed))


# --- plan_path -------------------------------------------------------------------------------

@pytest.mark.parametrize("end", [(700, 430), (180, 120), (1200, 650)])
def test_a_path_starts_at_the_start_and_ends_exactly_on_the_target(end):
    for seed in SEEDS:
        path = _plan((100, 100), end, seed)

        assert path[0][1:] == (100, 100), f"seed {seed}: path starts at {path[0][1:]}, not (100, 100)"
        assert path[-1][1:] == end, f"seed {seed}: path ends at {path[-1][1:]}, not on the target {end}"


def test_timestamps_start_at_zero_and_strictly_increase():
    for seed in SEEDS:
        times = [t for t, _, _ in _plan((50, 600), (900, 80), seed)]

        assert times[0] == 0
        bad = [(a, b) for a, b in itertools.pairwise(times) if b <= a]
        assert not bad, f"seed {seed}: timestamps go backwards or repeat at {bad[:3]}"


def test_a_path_bows_off_the_straight_line():
    """A straight line is the robot look the owner called out."""
    for seed in SEEDS:
        start, end = (100, 400), (600, 400)
        deviation = max(p for p, _ in _perp_and_along(_plan(start, end, seed), start, end))

        assert deviation >= 0.02 * 500, f"seed {seed}: path strays only {deviation:.1f}px off a 500px line"


@pytest.mark.parametrize("end", [(400, 300), (1100, 650)])
def test_a_path_stays_inside_a_narrow_corridor_around_the_straight_line(end):
    start = (80, 90)
    d = math.hypot(end[0] - start[0], end[1] - start[1])
    for seed in SEEDS:
        rows = _perp_and_along(_plan(start, end, seed), start, end)

        widest = max(p for p, _ in rows)
        assert widest <= 0.10 * d + 1.5, f"seed {seed}: strays {widest:.1f}px off a {d:.0f}px line"
        assert min(a for _, a in rows) >= -1.5, f"seed {seed}: path starts by moving backwards"
        assert max(a for _, a in rows) <= d + 30, f"seed {seed}: overshoots by more than 30px"


def test_only_long_moves_overshoot_and_then_come_back():
    for seed in SEEDS:
        short_start, short_end = (100, 100), (380, 100)
        long_start, long_end = (100, 100), (800, 500)
        short = _perp_and_along(_plan(short_start, short_end, seed), short_start, short_end)
        long_ = _perp_and_along(_plan(long_start, long_end, seed), long_start, long_end)
        long_d = math.hypot(700, 400)

        assert max(a for _, a in short) <= 280 + 1.0, f"seed {seed}: a 280px move overshot"
        assert max(a for _, a in long_) >= long_d + 4, f"seed {seed}: an 806px move did not overshoot"


@pytest.mark.parametrize(("d", "w"), [(2, 400), (30, 200), (5000, 4)])
def test_the_duration_stays_within_the_clamps(d, w):
    for seed in SEEDS:
        ms = _plan((10, 10), (10 + d, 10), seed, w=w, h=w)[-1][0]

        assert human.MIN_MOVE_MS <= ms <= human.MAX_MOVE_MS, f"seed {seed}: {d}px over {w}px took {ms:.0f} ms"


def test_a_longer_move_or_a_smaller_target_takes_longer():
    """Fitts's law, on average over seeds (each move has a little random jitter)."""
    def mean_ms(d, w):
        return sum(_plan((0, 0), (d, 0), s, w=w, h=w)[-1][0] for s in SEEDS) / len(SEEDS)

    near, mid, far = mean_ms(80, 40), mean_ms(300, 40), mean_ms(900, 40)
    big, small = mean_ms(300, 160), mean_ms(300, 12)

    assert near < mid < far, f"80/300/900px took {near:.0f}/{mid:.0f}/{far:.0f} ms"
    assert big < small, f"a 160px target took {big:.0f} ms, a 12px one {small:.0f} ms"


def test_the_same_seed_plans_the_same_path_and_another_seed_a_different_one():
    a, b, c = _plan((10, 20), (700, 300), 7), _plan((10, 20), (700, 300), 7), _plan((10, 20), (700, 300), 8)

    assert a == b, "plan_path with the same seed planned two different paths"
    assert a != c, "seeds 7 and 8 planned the identical path"


def test_moving_to_where_the_cursor_already_is_is_a_single_point():
    assert _plan((300, 300), (300, 300), 1) == [(0.0, 300, 300)]


# --- landing_point ---------------------------------------------------------------------------

def test_the_landing_point_is_inside_the_middle_sixty_percent_and_not_dead_centre():
    box = {"x": 200, "y": 100, "width": 120, "height": 30}
    points = [human.landing_point(box, random.Random(s)) for s in range(200)]

    for x, y in points:
        assert 200 + 0.2 * 120 <= x <= 200 + 0.8 * 120, f"landed at x={x:.1f}, outside the middle 60%"
        assert 100 + 0.2 * 30 <= y <= 100 + 0.8 * 30, f"landed at y={y:.1f}, outside the middle 60%"
    assert len({(round(x), round(y)) for x, y in points}) > 20, "every click lands on the same spot"




def test_a_tiny_target_is_aimed_at_its_centre():
    box = {"x": 300, "y": 50, "width": 4, "height": 30}

    x, _ = human.landing_point(box, random.Random(1))

    assert x == 302, f"a 4px-wide target aimed at x={x}, not its centre 302"


def test_a_bounded_path_never_leaves_its_bounds_even_overshooting():
    """Overshoot, bow and tremor stay on screen (the viewport minus the cursor's size)."""
    bounds = (0, 0, 1280 - 26, 720 - 26)
    for seed in SEEDS:
        path = human.plan_path((100, 100), (1250, 690), target_w=40, target_h=30,
                               rng=random.Random(seed), bounds=bounds)

        outside = [(x, y) for _, x, y in path if not (0 <= x <= 1254 and 0 <= y <= 694)]
        assert not outside, f"seed {seed}: path left the screen at {outside[:3]}"
        assert path[-1][1:] == (1250, 690)


# --- move / click / hover / idle / wheel against a fake page ---------------------------------

VIEWPORT = {"width": 1280, "height": 720}


class FakeMouse:
    def __init__(self, log):
        self.log = log

    def move(self, x, y):
        self.log.append(("mouse", x, y))

    def click(self, x, y):
        self.log.append(("mouse", x, y))
        self.log.append(("mouseclick", x, y))

    def wheel(self, dx, dy):
        self.log.append(("wheel", dx, dy))


class FakePage:
    url = "http://127.0.0.1:8795/app.html"
    viewport_size = VIEWPORT

    def __init__(self):
        self.log: list[tuple] = []
        self.mouse = FakeMouse(self.log)
        self.watch: list = []  # targets a parent's reveal is meant to bring into view

    def evaluate(self, script, arg=None):
        self.log.append(("evaluate", script, arg))

    def wait_for_timeout(self, ms):
        assert ms >= 0, f"asked to wait {ms} ms"
        self.log.append(("wait", ms))

    def wait_for_function(self, script, arg=None, timeout=None, polling=None):
        assert timeout is not None and timeout <= 5000, f"waited {timeout} ms for a scroll"
        element, band = arg
        self.log.append(("waitfn", timeout))
        if not element.evaluate(human._REVEALED, band):
            raise PlaywrightTimeout("Timeout exceeded (wait_for_function)")

    # what the tests read
    def mouse_moves(self):
        return [(e[1], e[2]) for e in self.log if e[0] == "mouse"]

    def clicks(self):
        return [(e[1], e[2]) for e in self.log if e[0] == "mouseclick"]

    def animations(self):
        return [e[2] for e in self.log if e[0] == "evaluate" and e[1] == human._ANIMATE]

    def drawn_at(self):
        return tuple(self.animations()[-1][-1][1:])

    def waited(self):
        return sum(e[1] for e in self.log if e[0] == "wait")


class FakeLocator:
    """An element on the fake page. *boxes*: what successive bounding_box() calls return (the
    last repeats), so an element can move after the first read. *first*: its first client rect
    as (dx, dy, w, h) from the box's corner (wrapped text); default the whole box. *border*:
    px of border; Playwright's position= counts from inside it (the padding box). *clip*: the
    visible rect of its scrolling ancestors. *refuse*: how many exact-point trials fail the way
    Playwright does when another element covers the point. *revealed*: the boxes the element
    has once its parent is scrolled into view (None: scrolling does not help)."""

    def __init__(self, page, *boxes, first=None, border=0, clip=None, refuse=0, revealed=None,
                 unrendered=False, in_view=False, flicker=0):
        self.page, self.boxes, self.reads, self.border = page, list(boxes), 0, border
        self.first, self.clip, self.refuse, self.revealed = first, clip, refuse, revealed
        self.trials, self.real_clicks, self.scrolls, self.reveals = [], [], 0, 0
        self.unrendered, self.in_view, self.waits, self.flicker = unrendered, in_view, [], flicker
        self.frame, self.handles, self.disposed = None, 0, 0

    def wait_for(self, state="visible", timeout=None):
        assert timeout is not None and timeout <= 10000, "wait_for must not wait Playwright's 30 s"
        self.waits.append(state)
        self.unrendered = False  # what a hover toolbar does a moment after the hover

    def element_handle(self, timeout=None):
        assert timeout is not None and timeout <= 10000, "element_handle must not wait 30 s"
        self.handles += 1
        return self

    def owner_frame(self):
        return self.frame or self.page

    def dispose(self):
        self.disposed += 1

    def _box(self):
        return self.boxes[min(self.reads, len(self.boxes)) - 1] if self.reads else self.boxes[0]

    def scroll_into_view_if_needed(self):
        self.scrolls += 1

    def bounding_box(self):
        if self.unrendered:
            return None
        if self.flicker:  # re-rendered by a virtualized list just after wait_for said visible
            self.flicker -= 1
            return None
        self.reads += 1
        return dict(self._box())

    def evaluate(self, script, arg=None):
        if script == human._REVEAL:
            self.reveals += 1
            return not self.in_view  # true: it scrolled
        if script == human._REVEALED:
            return all(self._visible(t) for t in self.page.watch)
        assert script == human._FIRST_RECT, "unexpected script"
        if self.unrendered:
            return None
        box = self._box()
        dx, dy, w, h = self.first or (0, 0, box["width"], box["height"])
        clip = None
        if self.clip:
            x0, y0, x1, y1 = self.clip
            clip = [x0 - box["x"], y0 - box["y"], x1 - box["x"], y1 - box["y"]]
        return {"bx": 0, "by": 0, "x": dx, "y": dy, "width": w, "height": h,
                "bl": self.border, "bt": self.border, "clip": clip}

    def _visible(self, target):
        return target.revealed is None or target.boxes == target.revealed

    def _trial(self, kind, position, timeout):
        assert timeout is not None and timeout <= 10000, "a trial must not wait Playwright's 30 s"
        self.trials.append((kind, position))
        if position is not None and self.refuse > 0:
            self.refuse -= 1
            raise PlaywrightTimeout("element intercepts pointer events; retrying (trial run)")

    def click(self, position=None, trial=False, timeout=None):
        if trial:
            self._trial("click", position, timeout)
            return
        box = self._box()
        hit = (box["x"] + self.border + position["x"], box["y"] + self.border + position["y"])
        self.real_clicks.append(hit)
        self.page.log.append(("mouseclick", *hit))

    def hover(self, position=None, trial=False, timeout=None):
        if not trial:
            raise AssertionError("hover() without trial moves the real mouse to its own point")
        self._trial("hover", position, timeout)


def _box(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def _middle(box):
    return (box["x"] + 0.2 * box["width"], box["x"] + 0.8 * box["width"],
            box["y"] + 0.2 * box["height"], box["y"] + 0.8 * box["height"])


def _inside(point, zone, slack=0.01):
    (x, y), (x0, x1, y0, y1) = point, zone
    return x0 - slack <= x <= x1 + slack and y0 - slack <= y <= y1 + slack


def test_move_animates_once_and_walks_the_real_mouse_through_intermediate_points():
    page = FakePage()
    human.cursor(page)

    human.move(page, 1000, 150)

    (points,) = page.animations()
    moves = page.mouse_moves()
    assert len(moves) >= 5, f"the real mouse moved {len(moves)} times; hover states need the path"
    assert moves[-1] == (1000, 150), f"the real mouse ended at {moves[-1]}"
    assert tuple(points[-1][1:]) == (1000, 150), f"the drawn cursor ends at {points[-1][1:]}"
    en_route = [m for m in moves if m not in ((640, 420), (1000, 150))]
    assert len(en_route) >= 3, f"the real mouse only visited the endpoints: {moves}"


def test_move_takes_about_its_planned_time():
    page = FakePage()
    human.cursor(page)

    human.move(page, 120, 650)

    (points,) = page.animations()
    planned = points[-1][0]
    assert abs(page.waited() - planned) <= 40, f"waited {page.waited():.0f} ms for a {planned:.0f} ms path"


def test_the_animation_data_is_plain_numbers():
    """The cursor moves by a script fed JSON numbers, never by building markup (Trusted Types)."""
    page = FakePage()
    human.cursor(page)

    human.move(page, 300, 300)

    (points,) = page.animations()
    assert all(isinstance(v, (int, float)) for row in points for v in row)
    for script in (human._CURSOR, human._ANIMATE, human._RIPPLE):
        assert not re.search(r"\.(inner|outer)HTML\b|insertAdjacentHTML|document\.write", script)


def test_click_lands_inside_the_target_and_pauses_before_clicking():
    for seed in range(30):
        page = FakePage()
        human.cursor(page, seed=seed)
        box = _box(400, 300, 90, 28)
        target = FakeLocator(page, box)

        human.click(page, target, settle=500)

        (at,) = page.clicks()
        assert _inside(at, _middle(box)), f"seed {seed}: clicked at {at}, outside the middle 60%"
        assert at == page.drawn_at(), f"seed {seed}: clicked {at}, the drawn cursor is at {page.drawn_at()}"
        assert not target.real_clicks, "the click must go through page.mouse"
        i = next(i for i, e in enumerate(page.log) if e[0] == "mouseclick")
        pause = sum(e[1] for e in page.log[:i] if e[0] == "wait") - sum(a[-1][0] for a in page.animations())
        assert 110 <= pause <= 321, f"seed {seed}: paused {pause:.0f} ms before clicking"


def test_a_bordered_target_is_clicked_exactly_under_the_drawn_cursor():
    """Locator.click(position=) measures from the padding box: a 6px border put the click
    6px off the drawn cursor."""
    page = FakePage()
    human.cursor(page, seed=2)
    target = FakeLocator(page, _box(500, 200, 120, 40), border=6)

    human.click(page, target)

    assert page.clicks() == [page.drawn_at()], f"clicked {page.clicks()}, cursor drawn at {page.drawn_at()}"


def test_some_clicks_micro_adjust_before_clicking_and_some_do_not():
    adjusted = 0
    for seed in range(40):
        page = FakePage()
        human.cursor(page, seed=seed)
        human.click(page, FakeLocator(page, _box(500, 200, 100, 40)))
        adjusted += len(page.animations()) == 2

    assert 4 <= adjusted <= 30, f"{adjusted}/40 clicks micro-adjusted; expected some, not all"


def test_a_target_that_moves_during_the_approach_is_re_aimed():
    """A list that re-renders while the cursor travels: the click follows the element."""
    page = FakePage()
    human.cursor(page, seed=4)
    before, after = _box(300, 200, 100, 30), _box(300, 260, 100, 30)
    target = FakeLocator(page, before, after)

    human.click(page, target)

    (at,) = page.clicks()
    assert _inside(at, _middle(after)), f"clicked {at}; the element had moved to {after}"
    assert at == page.drawn_at()


def test_a_target_that_never_stops_moving_fails_loudly():
    page = FakePage()
    human.cursor(page, seed=4)
    target = FakeLocator(page, *[_box(300, 100 + 40 * i, 100, 30) for i in range(20)])

    with pytest.raises(RuntimeError, match="kept moving"):
        human.click(page, target)

    assert not page.clicks(), "clicked a target that was still moving"


def test_wrapped_text_is_clicked_inside_its_first_line():
    """A link wrapped over two lines: its bounding box's middle is empty space between them."""
    page = FakePage()
    human.cursor(page, seed=5)
    box = _box(100, 100, 400, 40)
    target = FakeLocator(page, box, first=(300, 0, 100, 20))

    human.click(page, target)

    (at,) = page.clicks()
    assert _inside(at, _middle(_box(400, 100, 100, 20))), f"clicked {at}, outside the first line's text"


def test_a_thin_target_is_clicked_at_its_centre_line():
    page = FakePage()
    human.cursor(page, seed=6)
    target = FakeLocator(page, _box(600, 300, 3, 80))

    human.click(page, target)

    (at,) = page.clicks()
    assert at[0] == 601.5, f"a 3px-wide target clicked at x={at[0]}"


def test_a_target_at_the_viewport_edge_is_clicked_on_screen_and_the_path_stays_on_screen():
    for seed in range(20):
        page = FakePage()
        human.cursor(page, seed=seed)
        box = _box(1240, 690, 80, 60)  # half off the bottom-right corner
        target = FakeLocator(page, box)

        human.click(page, target)

        (at,) = page.clicks()
        assert _inside(at, _middle(_box(1240, 690, 40, 30))), f"seed {seed}: clicked {at}, off screen"
        for a in page.animations():  # a leg may end on the target, past the screen bound
            x_max = max(1280 - 26, a[0][1], a[-1][1])
            y_max = max(720 - 26, a[0][2], a[-1][2])
            off = [p for _, *p in a if not (0 <= p[0] <= x_max and 0 <= p[1] <= y_max)]
            assert not off, f"seed {seed}: the cursor went off screen at {off[:3]}"


def test_hover_puts_the_drawn_cursor_and_the_real_mouse_on_the_same_point():
    page = FakePage()
    human.cursor(page, seed=7)
    msg = FakeLocator(page, _box(200, 300, 600, 120))

    human.hover(page, msg, at=(560, 340))

    assert page.drawn_at() == (560, 340) and page.mouse_moves()[-1] == (560, 340)
    assert msg.trials[-1] == ("hover", {"x": 360, "y": 40}), f"hover checked {msg.trials}, not its point"


def test_hover_refuses_a_point_outside_the_element():
    page = FakePage()
    human.cursor(page)
    msg = FakeLocator(page, _box(200, 300, 600, 120))

    with pytest.raises(ValueError, match="outside"):
        human.hover(page, msg, at=(100, 340))


def test_a_click_within_a_hovered_parent_never_leaves_it():
    """A hover-only button (Teams' reply action): a path that bows out of the message un-hovers
    it and the button disappears before the click."""
    for seed in range(30):
        page = FakePage()
        human.cursor(page, seed=seed)
        msg = FakeLocator(page, _box(200, 300, 600, 60))
        reply = FakeLocator(page, _box(740, 302, 28, 24))
        human.hover(page, msg, at=(260, 350))
        start = len(page.log)
        after = FakePage()

        human.click(page, reply, within=msg)

        after.log = page.log[start:]
        out = [m for m in after.mouse_moves() if not (200 <= m[0] <= 800 and 300 <= m[1] <= 360)]
        drawn = [p for a in after.animations() for _, *p in a if not (200 <= p[0] <= 800 and 300 <= p[1] <= 360)]
        assert not out and not drawn, f"seed {seed}: left the message at {(out or drawn)[:3]}"


def test_idle_drifts_a_few_pixels_and_fills_its_time():
    page = FakePage()
    human.cursor(page, seed=3)
    human.move(page, 500, 300)
    before = len(page.log)

    human.idle(page, 5.0)

    tail = FakePage()
    tail.log = page.log[before:]
    assert tail.animations(), "the cursor sat statue-still for 5 s"
    for x, y in tail.mouse_moves():
        assert math.hypot(x - 500, y - 300) <= human.IDLE_RADIUS_PX + 1, f"idle wandered to ({x:.0f}, {y:.0f})"
    assert abs(tail.waited() - 5000) <= 60, f"idle(5.0) waited {tail.waited():.0f} ms"


@pytest.mark.parametrize("seconds", [0.4, 0.8, 1.0])
def test_a_short_hold_still_drifts(seconds):
    """Most holds in the examples are under 1.15 s; a frozen cursor there is the common case."""
    for seed in range(20):
        page = FakePage()
        human.cursor(page, seed=seed)

        human.idle(page, seconds)

        assert page.animations(), f"seed {seed}: idle({seconds}) never moved"
        assert abs(page.waited() - seconds * 1000) <= 30, f"seed {seed}: idle({seconds}) waited {page.waited():.0f} ms"


def test_a_very_short_idle_just_waits():
    page = FakePage()
    human.cursor(page)

    human.idle(page, 0.3)

    assert not page.animations() and abs(page.waited() - 300) < 1


def test_wheel_scrolls_the_whole_distance_faster_in_the_middle():
    page = FakePage()
    human.cursor(page)

    human.wheel(page, 300, steps=6)

    steps = [e[2] for e in page.log if e[0] == "wheel"]
    waits = [e[1] for e in page.log if e[0] == "wait"]
    assert abs(sum(steps) - 300) < 1e-6, f"scrolled {sum(steps)} of 300"
    assert steps[2] > steps[0] and steps[3] > steps[5], f"steps not eased: {steps}"
    assert len({round(w) for w in waits}) > 1, f"every interval identical: {waits}"


# --- round 2: the exact-point trial, a parent-bound path, scroll containers -------------------

def test_the_click_is_trial_checked_at_the_drawn_point_measured_from_the_padding_box():
    page = FakePage()
    human.cursor(page, seed=8)
    box = _box(500, 200, 120, 40)
    target = FakeLocator(page, box, border=6)

    human.click(page, target)

    (at,) = page.clicks()
    kind, pos = target.trials[-1]
    assert kind == "click" and pos == {"x": at[0] - 500 - 6, "y": at[1] - 200 - 6}, (
        f"last trial {target.trials[-1]} is not the drawn point {at} less box and border")


def test_a_point_that_does_not_receive_the_click_is_re_aimed_once():
    page = FakePage()
    human.cursor(page, seed=8)
    target = FakeLocator(page, _box(500, 200, 120, 40), refuse=1)

    human.click(page, target)

    refused, taken = [pos for _, pos in target.trials if pos]
    assert len(page.clicks()) == 1 and page.clicks()[0] == page.drawn_at()
    assert refused != taken, f"retried the refused point {refused} instead of re-aiming"


def test_a_point_that_never_receives_the_click_fails_loudly():
    page = FakePage()
    human.cursor(page, seed=8)
    target = FakeLocator(page, _box(500, 200, 120, 40), refuse=99)

    with pytest.raises(RuntimeError, match="does not take the click"):
        human.click(page, target)

    assert not page.clicks(), "clicked a point the trial refused"


def test_a_hover_point_that_is_covered_fails_loudly():
    page = FakePage()
    human.cursor(page, seed=8)
    msg = FakeLocator(page, _box(200, 300, 600, 120), refuse=99)

    with pytest.raises(RuntimeError, match="does not take the hover"):
        human.hover(page, msg, at=(560, 340))


# Measured on the live Teams channel: the reply action is a body-level portal drawn at the
# message item's top edge, 2 px above the item; the item is the hover parent.
TEAMS_ITEM = _box(420, 530, 846, 86)
TEAMS_CONTENT = _box(474, 565, 620, 44)
TEAMS_REPLY = _box(1037, 528, 32, 32)


def test_a_hover_only_target_is_reached_on_a_straight_path_inside_its_parent():
    for seed in range(30):
        page = FakePage()
        human.cursor(page, seed=seed)
        item, content = FakeLocator(page, TEAMS_ITEM), FakeLocator(page, TEAMS_CONTENT)
        reply = FakeLocator(page, TEAMS_REPLY)
        human.hover(page, content, at=(846, 587))
        start, after = len(page.log), FakePage()

        human.click(page, reply, within=item)

        after.log = page.log[start:]
        x0, y0, x1, y1 = 420, 530, 1266, 616
        out = [m for m in after.mouse_moves() if not (x0 <= m[0] <= x1 and y0 <= m[1] <= y1)]
        assert not out, f"seed {seed}: the real mouse left the hovered item at {out[:3]}"
        (reach, *_) = after.animations()
        s, e = tuple(reach[0][1:]), tuple(reach[-1][1:])
        bow = max(p for p, _ in _perp_and_along([tuple(r) for r in reach], s, e))
        assert bow <= 1.5, f"seed {seed}: the path to a hover-only target bowed {bow:.1f}px"
        assert reply.scrolls == 0, "Playwright scrolling a hover-only target scrolls its parent away"


def test_a_hover_only_target_out_of_view_has_its_parent_revealed_first():
    page = FakePage()
    human.cursor(page, seed=1)
    item = FakeLocator(page, TEAMS_ITEM)
    reply = FakeLocator(page, _box(1037, -30, 32, 32), revealed=None)
    reply.revealed = [_box(1037, 200, 32, 32)]

    def reveal_moves_reply(script, arg=None, _orig=item.evaluate):
        if script == human._REVEAL:
            reply.boxes = [_box(1037, 200, 32, 32)]
        return _orig(script, arg)
    item.evaluate = reveal_moves_reply
    page.watch = [reply]

    human.click(page, reply, within=item)

    assert item.reveals == 1, "the parent was not scrolled into view"
    (at,) = page.clicks()
    assert 200 <= at[1] <= 232, f"clicked at {at}, not on the revealed button"


def test_a_hover_only_target_that_stays_out_of_view_fails_loudly():
    page = FakePage()
    human.cursor(page, seed=1)
    item = FakeLocator(page, TEAMS_ITEM)
    reply = FakeLocator(page, _box(1037, -30, 32, 32))

    with pytest.raises(RuntimeError, match="outside the visible area"):
        human.click(page, reply, within=item)

    assert not page.clicks()


def test_a_target_under_a_scroll_containers_edge_is_aimed_at_its_visible_part():
    """The message list ends at y=618; a button half below it is half hidden, not half on screen."""
    for seed in range(20):
        page = FakePage()
        human.cursor(page, seed=seed)
        target = FakeLocator(page, _box(500, 600, 100, 40), clip=(388, 109, 1280, 618))

        human.click(page, target)

        (at,) = page.clicks()
        assert _inside(at, _middle(_box(500, 600, 100, 18))), f"seed {seed}: clicked {at}, under the list's edge"


def test_a_path_along_the_hovered_parents_edge_never_trembles_out_of_it():
    """Teams' hover point sits near the item's top edge; a sub-pixel tremor past it un-hovers."""
    for seed in range(40):
        page = FakePage()
        human.cursor(page, seed=seed)
        item, reply = FakeLocator(page, TEAMS_ITEM), FakeLocator(page, TEAMS_REPLY)
        human.hover(page, item, at=(470, 530.2))
        start, after = len(page.log), FakePage()

        human.click(page, reply, within=item)

        after.log = page.log[start:]
        above = [m for m in after.mouse_moves() if m[1] < 530]
        assert not above, f"seed {seed}: the real mouse left the item's top edge at {above[:3]}"


# --- round 3: hover's own trial, reveal's wait, a target not rendered yet ---------------------

def test_hover_at_a_point_runs_no_trial_but_the_one_at_that_point():
    """A position-less trial hit-tests the centre and may scroll, undoing a reveal."""
    page = FakePage()
    human.cursor(page, seed=7)
    msg = FakeLocator(page, _box(200, 300, 600, 120))

    human.hover(page, msg, at=(560, 340))

    assert msg.trials == [("hover", {"x": 360, "y": 40})], f"trials: {msg.trials}"


def test_hover_without_a_point_waits_for_the_element_instead_of_a_centre_trial():
    page = FakePage()
    human.cursor(page, seed=7)
    msg = FakeLocator(page, _box(200, 300, 600, 120))

    human.hover(page, msg)

    assert msg.waits == ["visible"], f"waits: {msg.waits}"
    assert all(pos is not None for _, pos in msg.trials), f"a centre trial ran: {msg.trials}"


def test_reveal_of_an_element_already_in_view_does_not_scroll_or_fail():
    page = FakePage()
    item = FakeLocator(page, TEAMS_ITEM, in_view=True)

    human.reveal(page, item)

    assert item.reveals == 1 and ("waitfn", human.REVEAL_TIMEOUT_MS) in page.log


def test_reveal_waits_on_the_page_for_the_scroll_to_land_not_a_fixed_time():
    page = FakePage()
    item = FakeLocator(page, TEAMS_ITEM)
    reply = FakeLocator(page, _box(1037, 200, 32, 32), revealed=[_box(1037, 200, 32, 32)])
    page.watch = [reply]

    human.reveal(page, item)

    assert not [e for e in page.log if e[0] == "wait"], "reveal slept a fixed time"
    assert ("waitfn", human.REVEAL_TIMEOUT_MS) in page.log


def test_reveal_that_never_lands_fails_loudly():
    page = FakePage()
    item = FakeLocator(page, TEAMS_ITEM)
    page.watch = [FakeLocator(page, _box(1037, -30, 32, 32), revealed=[_box(1037, 200, 32, 32)])]

    with pytest.raises(RuntimeError, match="could not scroll"):
        human.reveal(page, item)


def test_a_hover_only_target_not_rendered_yet_is_waited_for_not_refused():
    page = FakePage()
    human.cursor(page, seed=2)
    item, content = FakeLocator(page, TEAMS_ITEM), FakeLocator(page, TEAMS_CONTENT)
    reply = FakeLocator(page, TEAMS_REPLY, unrendered=True)
    human.hover(page, content, at=(846, 587))

    human.click(page, reply, within=item)

    assert reply.waits == ["visible"] and len(page.clicks()) == 1


# --- reveal's in-view test, run in a real Chromium page ---------------------------------------

_LIST = """<div id=list style="position:absolute;top:100px;left:0;width:600px;height:500px;overflow-y:auto">
  <div id=first style="height:60px;background:#222">first</div>
  <div style="height:2000px"></div>
  <div id=near style="height:44px;background:#444">near</div>
  <div style="height:300px"></div>
  <div id=tall style="height:900px;background:#333">tall</div>
  <div id=short style="height:44px;background:#555">short</div>
</div>"""


@pytest.fixture(scope="module")
def chromium_page(chromium_launches):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 720})
    yield page
    browser.close()
    pw.stop()


def _scroll_to(page, where):
    page.set_content(_LIST)
    page.evaluate("(w) => { const l = document.getElementById('list'); l.scrollTop = w === 'end' ? l.scrollHeight : 0; }", where)


def test_reveal_accepts_the_newest_short_post_at_the_bottom_of_a_list_at_max_scroll(chromium_page):
    """The live failure: the last item cannot rise into the band; the list is already at its end."""
    _scroll_to(chromium_page, "end")
    short = chromium_page.locator("#short")

    human.reveal(chromium_page, short)

    top = short.bounding_box()["y"]
    assert 100 <= top <= 600, f"the short item's top is at {top}, off its list"


def test_reveal_scrolls_a_tall_posts_top_into_view(chromium_page):
    """A tall notice whose top is scrolled off above: its toolbar would be drawn off screen."""
    _scroll_to(chromium_page, "end")
    tall = chromium_page.locator("#tall")
    assert tall.bounding_box()["y"] < 100, "fixture: the tall item's top should start above the list"

    human.reveal(chromium_page, tall)

    top = tall.bounding_box()["y"]
    assert 100 + human.REVEAL_BAND["top"] <= top <= 600 - human.REVEAL_BAND["bottom"], f"top at {top}"


def test_reveal_accepts_the_first_post_of_a_list_scrolled_to_its_top(chromium_page):
    """The list cannot scroll up any further: the first item is as revealed as it gets."""
    _scroll_to(chromium_page, "top")
    first = chromium_page.locator("#first")

    human.reveal(chromium_page, first)

    assert first.bounding_box()["y"] == 100


def test_a_hover_only_target_re_rendered_after_its_wait_falls_through_to_reveal():
    page = FakePage()
    human.cursor(page, seed=2)
    item, content = FakeLocator(page, TEAMS_ITEM), FakeLocator(page, TEAMS_CONTENT)
    reply = FakeLocator(page, TEAMS_REPLY, flicker=1)
    human.hover(page, content, at=(846, 587))

    human.click(page, reply, within=item)

    assert item.reveals == 1 and len(page.clicks()) == 1


def test_reveal_leaves_a_short_post_near_the_lists_bottom_where_it_is(chromium_page):
    """Room to hover a 44 px post is 44 px, not the full margin: no needless scroll on camera."""
    chromium_page.set_content(_LIST)
    chromium_page.evaluate("""() => { const l = document.getElementById('list');
        l.scrollTop = document.getElementById('near').offsetTop - 440; }""")
    before = chromium_page.evaluate("() => document.getElementById('list').scrollTop")

    human.reveal(chromium_page, chromium_page.locator("#near"))

    after = chromium_page.evaluate("() => document.getElementById('list').scrollTop")
    assert after == before, f"scrolled {after - before}px for a post already in view"


def test_hover_at_a_point_follows_its_element_when_it_moves():
    """Live Teams: the list re-anchors after a reveal and the message slides 68 px; a hover
    point measured before that lands above the message."""
    page = FakePage()
    human.cursor(page, seed=3)
    msg = FakeLocator(page, _box(458, 196, 456, 578), _box(458, 264, 456, 578))

    human.hover(page, msg, at=(732, 236))

    assert page.drawn_at() == (732, 304), f"hovered {page.drawn_at()}, not the point moved with its element"
    assert msg.trials[-1] == ("hover", {"x": 274, "y": 40}), f"last trial {msg.trials[-1]}"


_SHIFTING = """<div id=list style="position:absolute;top:100px;left:0;width:600px;height:500px;
     overflow-y:auto;overflow-anchor:none">
  <div style="height:2000px"></div>
  <div id=tall style="height:900px;background:#333">tall</div>
</div>
<script>
  // What Teams' virtualized list does after a scroll: re-anchor, sliding the item 68 px.
  document.getElementById('list').addEventListener('scrollend', () => setTimeout(() => {
    document.getElementById('tall').style.marginTop = '68px'; }, 250), {once: true});
</script>"""


def test_reveal_returns_only_once_the_element_has_stopped_moving(chromium_page):
    chromium_page.set_content(_SHIFTING)
    chromium_page.evaluate("() => { const l = document.getElementById('list'); l.scrollTop = l.scrollHeight; }")
    tall = chromium_page.locator("#tall")

    human.reveal(chromium_page, tall)
    landed = tall.bounding_box()["y"]
    chromium_page.wait_for_timeout(500)

    assert tall.bounding_box()["y"] == landed, f"moved from {landed} to {tall.bounding_box()['y']} after reveal"


# --- round 4: reveal's handle and frame --------------------------------------------------------

def test_reveal_waits_in_the_elements_own_frame_and_disposes_its_handle():
    page, frame = FakePage(), FakePage()  # an iframe: its own wait_for_function
    item = FakeLocator(page, TEAMS_ITEM, in_view=True)
    item.frame = frame

    human.reveal(page, item)

    assert [e for e in frame.log if e[0] == "waitfn"] and not [e for e in page.log if e[0] == "waitfn"]
    assert item.handles == item.disposed == 1, f"{item.handles} handles, {item.disposed} disposed"


def test_reveal_disposes_its_handle_when_the_wait_fails():
    page = FakePage()
    item = FakeLocator(page, TEAMS_ITEM)
    page.watch = [FakeLocator(page, _box(1037, -30, 32, 32), revealed=[_box(1037, 200, 32, 32)])]

    with pytest.raises(RuntimeError, match="could not scroll"):
        human.reveal(page, item)

    assert item.handles == item.disposed == 1

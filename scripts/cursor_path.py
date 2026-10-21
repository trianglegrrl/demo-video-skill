"""The on-camera cursor's path, as pure functions: where it goes, how fast, where it lands.

A move is a shallow cubic Bezier bowed to one side, timed by Fitts's law, eased on min-jerk
timing (slow start, fast middle, slow landing), with a small overshoot and correction on long
moves; a click lands in the middle 60% of its target. Nothing here touches a page: human.py
plays these paths. Every random choice comes from the `random.Random` passed in.
"""
from __future__ import annotations

import math
import random

Point = tuple[float, float, float]  # (t_ms, x, y)
Bounds = tuple[float, float, float, float]  # (x0, y0, x1, y1)

# Fitts's law: ms = A + B * log2(distance / width + 1), then clamped.
FITTS_A_MS, FITTS_B_MS = 230.0, 125.0
MIN_MOVE_MS, MAX_MOVE_MS = 250.0, 1100.0
DURATION_JITTER = (0.92, 1.08)
BOW = (0.03, 0.12)                # control-point offset, as a fraction of the distance
OVERSHOOT_FROM_PX = 350.0         # only moves longer than this overshoot
OVERSHOOT = (0.025, 0.05)         # past the target, as a fraction of the distance ...
OVERSHOOT_MAX_PX = 24.0           # ... and never more than this
CORRECTION_MS = (110.0, 170.0)
TREMOR_PX = 0.6
FRAME_MS = 1000.0 / 60
MOUSE_STEP_MS = 45.0              # the real mouse follows every ~3rd frame
LANDING = (0.2, 0.8)              # click inside the middle 60% of the target box ...
TINY_PX = 6.0                     # ... or, on an axis thinner than this, its centre


def fitts_ms(distance: float, width: float) -> float:
    ms = FITTS_A_MS + FITTS_B_MS * math.log2(distance / max(width, 1.0) + 1)
    return min(MAX_MOVE_MS, max(MIN_MOVE_MS, ms))


def _min_jerk(u: float) -> float:
    """Position along a reach for time fraction u: slow start, fast middle, slow landing."""
    return u * u * u * (10 - 15 * u + 6 * u * u)


def clamp(x: float, y: float, bounds: Bounds | None) -> tuple[float, float]:
    if bounds is None:
        return x, y
    x0, y0, x1, y1 = bounds
    return min(x1, max(x0, x)), min(y1, max(y0, y))


def grow(bounds: Bounds | None, *points: tuple[float, float]) -> Bounds | None:
    """*bounds* stretched to hold *points* (the path's own start and end always fit)."""
    if bounds is None:
        return None
    x0, y0, x1, y1 = bounds
    for x, y in points:
        x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
    return x0, y0, x1, y1


def curve(start: tuple[float, float], end: tuple[float, float], ms: float, bow: float,
           rng: random.Random, bounds: Bounds | None = None) -> list[Point]:
    """A cubic Bezier from start to end, both control points pushed *bow* px to one side,
    sampled once a frame on min-jerk timing. Interior points carry a sub-pixel tremor and are
    clamped into *bounds* (grown to hold start and end)."""
    (sx, sy), (ex, ey) = start, end
    bounds = grow(bounds, start, end)
    d = math.hypot(ex - sx, ey - sy) or 1.0
    nx, ny = -(ey - sy) / d * bow, (ex - sx) / d * bow
    c1 = (sx + (ex - sx) * 0.3 + nx, sy + (ey - sy) * 0.3 + ny)
    c2 = (sx + (ex - sx) * 0.7 + nx, sy + (ey - sy) * 0.7 + ny)
    n = max(2, math.ceil(ms / FRAME_MS))
    points: list[Point] = [(0.0, sx, sy)]
    for k in range(1, n):
        u = k / n
        s = _min_jerk(u)
        a, b, c, e = (1 - s) ** 3, 3 * (1 - s) ** 2 * s, 3 * (1 - s) * s * s, s ** 3
        x = a * sx + b * c1[0] + c * c2[0] + e * ex + rng.uniform(-TREMOR_PX, TREMOR_PX)
        y = a * sy + b * c1[1] + c * c2[1] + e * ey + rng.uniform(-TREMOR_PX, TREMOR_PX)
        points.append((ms * u, *clamp(x, y, bounds)))
    points.append((float(ms), ex, ey))
    return points


def plan_path(start: tuple[float, float], end: tuple[float, float], *, target_w: float,
              target_h: float, rng: random.Random, bounds: Bounds | None = None,
              curved: bool = True) -> list[Point]:
    """The cursor's path from *start* to *end* as (t_ms, x, y), t from 0, ending exactly on
    *end*. Bowed by up to 9% of the distance (side chosen at random), Fitts-timed for a
    target_w x target_h target, and on moves over OVERSHOOT_FROM_PX a few percent past the
    target followed by a short correction back onto it. Every point stays inside *bounds*
    (x0, y0, x1, y1), grown to hold start and end: the screen, or a hovered parent.
    *curved* False: no bow and no overshoot (inside a hovered parent the path must not
    wander); the timing is the same."""
    (sx, sy), (ex, ey) = start, end
    d = math.hypot(ex - sx, ey - sy)
    if d < 0.5:
        return [(0.0, ex, ey)]
    ms = min(MAX_MOVE_MS, max(MIN_MOVE_MS,
                              fitts_ms(d, min(target_w, target_h)) * rng.uniform(*DURATION_JITTER)))
    bow = rng.choice((-1, 1)) * rng.uniform(*BOW) * d
    if not curved:
        return curve(start, end, ms, 0.0, rng, bounds)
    if d <= OVERSHOOT_FROM_PX:
        return curve(start, end, ms, bow, rng, bounds)
    over = min(OVERSHOOT_MAX_PX, d * rng.uniform(*OVERSHOOT))
    aim = clamp(ex + (ex - sx) / d * over, ey + (ey - sy) / d * over, grow(bounds, start, end))
    fix_ms = rng.uniform(*CORRECTION_MS)
    reach = curve(start, aim, ms - fix_ms, bow, rng, bounds)
    fix = curve(aim, end, fix_ms, 0.0, rng, bounds)
    return reach + [(reach[-1][0] + t, x, y) for t, x, y in fix[1:]]


def zone(box: dict) -> Bounds:
    """Where a click may land on *box*: its middle 60%; on an axis under TINY_PX, the centre."""
    def span(lo: float, size: float) -> tuple[float, float]:
        if size < TINY_PX:
            return lo + size / 2, lo + size / 2
        return lo + size * LANDING[0], lo + size * LANDING[1]
    (x0, x1), (y0, y1) = span(box["x"], box["width"]), span(box["y"], box["height"])
    return x0, y0, x1, y1


def landing_point(box: dict, rng: random.Random) -> tuple[float, float]:
    """Where a person's click lands on *box*: anywhere in its middle 60%, not dead centre."""
    x0, y0, x1, y1 = zone(box)
    return x0 + (x1 - x0) * rng.random(), y0 + (y1 - y0) * rng.random()


def mouse_samples(path: list[Point]) -> list[Point]:
    """The points the real mouse visits: one every MOUSE_STEP_MS, always the last."""
    picked: list[Point] = []
    next_t = MOUSE_STEP_MS
    for p in path[1:-1]:
        if p[0] >= next_t:
            picked.append(p)
            next_t = p[0] + MOUSE_STEP_MS
    return picked + [path[-1]]

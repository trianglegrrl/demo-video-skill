"""Human-paced pointer for headless takes: a drawn cursor that moves like a hand, hovers, clicks.

Headless Chromium draws no mouse pointer, and Playwright clicks land instantly; both read as
a robot on camera. Each move follows a path from cursor_path.py (a shallow curve, Fitts-timed,
eased, overshooting a little on long moves). The drawn cursor plays it in the page
(requestAnimationFrame over the points) while the real Playwright mouse walks a sparser copy,
so hover states fire on the way; every point stays on screen. `click` lands in the middle of
the target's first line (cut to what its scroll containers show), follows it if it moves,
pauses, sometimes nudges, checks with Playwright that the exact point takes the click, shows a
ripple and clicks there. `hover` does the same without the click; `within=` keeps the path to
a hover-only button inside the element that keeps it shown. `idle` drifts a few pixels during
a reading hold. `reveal` scrolls an element's top into view.

Every random choice comes from one `random.Random` per page, seeded from the page's first URL
(or `cursor(page, seed=...)`): a re-recorded take moves the same way, and no two moves match.
"""
from __future__ import annotations

import math
import random
import time
import weakref
import zlib
from collections.abc import Callable
from typing import TYPE_CHECKING

from cursor_path import (  # noqa: F401  (re-exported: the module's public API)
    LANDING,
    MAX_MOVE_MS,
    MIN_MOVE_MS,
    TINY_PX,
    Bounds,
    Point,
    clamp,
    curve,
    fitts_ms,
    landing_point,
    mouse_samples,
    plan_path,
    zone,
)
from playwright.sync_api import Error as PlaywrightError

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

DEFAULT_TARGET_PX = 40.0          # move() to a bare point: aim as if at a button-sized target
CURSOR_PX = 26.0                  # the drawn cursor's size: it stays wholly on screen
REAIM_TOLERANCE_PX = 2.0          # a target that moved more than this is re-aimed at ...
MAX_REAIMS = 3                    # ... at most this many times, then the click fails
REAIM_MS = (140.0, 200.0)
TRIAL_TIMEOUT_MS = 5000.0         # Playwright's actionability check, not its 30 s default
PRE_CLICK_MS = (120.0, 320.0)
MICRO_ADJUST_P = 0.35
MICRO_ADJUST_PX, MICRO_ADJUST_MS = 3.0, (70.0, 110.0)
IDLE_RADIUS_PX = 6.0
IDLE_MIN_S = 0.4                  # a hold this long or longer drifts at least once
IDLE_FIRST_REST_MS = (60.0, 300.0)
IDLE_REST_MS = (700.0, 1900.0)
IDLE_FIT = 0.95                   # a first drift squeezed into a short hold leaves this much
IDLE_DRIFT_MS = (450.0, 900.0)
WHEEL_INTERVAL_MS = 160.0
# reveal(): an element is in view when its top sits at least `top` px below its scroller's
# top (room for a toolbar drawn above it) and `bottom` px above its bottom (room to hover
# inside it); otherwise it is scrolled so its top sits at `aim` of the scroller's height.
REVEAL_BAND = {"top": 48, "bottom": 80, "aim": 0.25}
REVEAL_TIMEOUT_MS = 3000.0        # a smooth scroll (and Teams' list re-anchoring) lands by then
REVEAL_POLL_MS = 100.0
REVEAL_STABLE_POLLS = 3           # ... and the element then holds still for this many polls
HOME = (640.0, 420.0)

_CURSOR = """(at) => {
  if (document.getElementById('__cur')) return;
  const c = document.createElement('div');
  c.id = '__cur';
  c.style.cssText = 'position:fixed;width:26px;height:26px;z-index:2147483647;pointer-events:none;';
  c.style.left = at.x + 'px'; c.style.top = at.y + 'px';
  // DOM calls, not innerHTML: Teams enforces Trusted Types and refuses an HTML string.
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', '26'); svg.setAttribute('height', '26');
  svg.setAttribute('viewBox', '0 0 24 24');
  const path = document.createElementNS(NS, 'path');
  path.setAttribute('d', 'M4 2l6.5 19 2.7-7.6L21 11z');
  path.setAttribute('fill', 'white'); path.setAttribute('stroke', '#111');
  path.setAttribute('stroke-width', '1.4'); path.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(path); c.appendChild(svg);
  document.body.appendChild(c);
  const r = document.createElement('div');
  r.id = '__rip';
  r.style.cssText = 'position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;'
    + 'border:3px solid rgba(116,192,252,.9);opacity:0;z-index:2147483646;pointer-events:none;';
  document.body.appendChild(r);
}"""

# Plays [[t_ms, x, y], ...] on the drawn cursor, linear between points, one rAF per frame.
_ANIMATE = """(pts) => {
  const c = document.getElementById('__cur');
  if (!c) throw new Error('demo-video: no cursor on the page; call human.cursor(page) first');
  if (window.__curRaf) cancelAnimationFrame(window.__curRaf);
  const place = (x, y) => { c.style.left = x + 'px'; c.style.top = y + 'px'; };
  const last = pts[pts.length - 1];
  const t0 = performance.now();
  let i = 0;
  const step = (now) => {
    const t = now - t0;
    while (i < pts.length - 1 && pts[i + 1][0] <= t) i++;
    if (i >= pts.length - 1) { place(last[1], last[2]); window.__curRaf = 0; return; }
    const [ta, xa, ya] = pts[i], [tb, xb, yb] = pts[i + 1];
    const f = Math.min(1, Math.max(0, (t - ta) / (tb - ta)));
    place(xa + (xb - xa) * f, ya + (yb - ya) * f);
    window.__curRaf = requestAnimationFrame(step);
  };
  window.__curRaf = requestAnimationFrame(step);
}"""

_RIPPLE = """(at) => {
  const r = document.getElementById('__rip');
  r.style.transition = 'none'; r.style.left = at.x + 'px'; r.style.top = at.y + 'px';
  r.style.transform = 'scale(.4)'; r.style.opacity = '1'; r.offsetWidth;
  r.style.transition = 'transform .45s ease-out, opacity .45s ease-out';
  r.style.transform = 'scale(1.6)'; r.style.opacity = '0';
}"""

# The element's first client rect; its bounding rect to translate by (iframes); its border
# (Playwright's position= counts from the padding box); and what its scrolling ancestors show.
_FIRST_RECT = """(el) => {
  const b = el.getBoundingClientRect(), r = el.getClientRects()[0];
  if (!r) return null;
  const s = getComputedStyle(el);
  let c = [-1e9, -1e9, 1e9, 1e9], clipped = false;
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const o = getComputedStyle(p);
    if (!/(auto|scroll|hidden|clip)/.test(o.overflowX + ' ' + o.overflowY)) continue;
    const q = p.getBoundingClientRect(), x = q.left + p.clientLeft, y = q.top + p.clientTop;
    c = [Math.max(c[0], x), Math.max(c[1], y),
         Math.min(c[2], x + p.clientWidth), Math.min(c[3], y + p.clientHeight)];
    clipped = true;
  }
  return {bx: b.x, by: b.y, x: r.x, y: r.y, width: r.width, height: r.height,
          bl: parseFloat(s.borderLeftWidth) || 0, bt: parseFloat(s.borderTopWidth) || 0,
          clip: clipped ? c : null};
}"""

_SCROLLER = """const scroller = (el) => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const o = getComputedStyle(p).overflowY;
      if (/(auto|scroll)/.test(o) && p.scrollHeight > p.clientHeight) return p;
    }
    return null;
  };
  const sc = scroller(el), s = sc ? sc.getBoundingClientRect() : {top: 0, height: innerHeight};
  const r = el.getBoundingClientRect(), top = r.top;
  // Room to hover below the top: `bottom` px, or the whole element if it is shorter.
  const inBand = top >= s.top + band.top && top <= s.top + s.height - Math.min(band.bottom, r.height);
  const dy = top - (s.top + s.height * band.aim);
  const t = sc || document.scrollingElement;
  // The newest post at the end of a list can rise no further: as revealed as it gets.
  const stuck = dy > 0 ? t.scrollTop + t.clientHeight >= t.scrollHeight - 1 : t.scrollTop <= 0;
  const ok = inBand || (stuck && top >= s.top && top < s.top + s.height);"""

# Scrolls the element's top into the upper part of its scroller, smoothly; true if it scrolled.
_REVEAL = """(el, band) => {
  window.__demoReveal = null;
  """ + _SCROLLER + """
  if (ok) return false;
  (sc || window).scrollBy({top: dy, behavior: 'smooth'});
  return true;
}"""

_REVEALED = """(el, band) => {
  """ + _SCROLLER + """
  return ok;
}"""

# In view AND holding still: Teams' list re-anchors after a scroll ends, sliding the item.
_REVEAL_SETTLED = """([el, band]) => {
  const ok = (""" + _REVEALED + """)(el, band), top = el.getBoundingClientRect().top;
  const st = window.__demoReveal || (window.__demoReveal = {top: null, n: 0});
  st.n = st.top !== null && Math.abs(st.top - top) < 0.5 ? st.n + 1 : 0;
  st.top = top;
  return ok && st.n >= """ + str(REVEAL_STABLE_POLLS) + """;
}"""


# Keyed by the page object itself: a later page reusing a dead page's id() starts fresh.
_last: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_rngs: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _rng(page: Page) -> random.Random:
    if page not in _rngs:
        _rngs[page] = random.Random(zlib.crc32(page.url.encode()))
    return _rngs[page]


def _where(page: Page) -> tuple[float, float]:
    return _last.get(page, HOME)


def _viewport(page: Page) -> dict:
    size = page.viewport_size
    if size is None:
        raise RuntimeError("demo-video: the page has no fixed viewport; open it with recorder.open_stream")
    return size


def _screen(page: Page) -> Bounds:
    """Where the cursor may go: the viewport, less the cursor's own size at the right and bottom."""
    size = _viewport(page)
    return 0.0, 0.0, size["width"] - CURSOR_PX, size["height"] - CURSOR_PX


def _box_of(target: Locator) -> dict:
    """The target's FIRST client rect in page coordinates (a wrapped link's bounding box is
    mostly the gap between its lines), plus its bounding-box corner and border (for
    position=) and its scroll containers' visible rect ("clip"), all in page coordinates."""
    box = target.bounding_box()
    rect = target.evaluate(_FIRST_RECT)
    if box is None or rect is None:
        raise RuntimeError("click target is not visible")
    # bounding_box is in the page's frame, client rects in the element's own (an iframe).
    dx, dy = box["x"] - rect["bx"], box["y"] - rect["by"]
    clip = rect["clip"]
    return {"x": rect["x"] + dx, "y": rect["y"] + dy, "width": rect["width"],
            "height": rect["height"], "bx": box["x"], "by": box["y"], "bl": rect["bl"],
            "bt": rect["bt"],
            "clip": None if clip is None else (clip[0] + dx, clip[1] + dy, clip[2] + dx, clip[3] + dy)}


def _visible_part(page: Page, box: dict) -> dict:
    """*box* cut to the viewport and to what its scroll containers show."""
    size = _viewport(page)
    x0, y0, x1, y1 = box["clip"] or (0.0, 0.0, size["width"], size["height"])
    x0, y0 = max(box["x"], x0, 0.0), max(box["y"], y0, 0.0)
    x1 = min(box["x"] + box["width"], x1, size["width"])
    y1 = min(box["y"] + box["height"], y1, size["height"])
    if x1 <= x0 or y1 <= y0:
        raise RuntimeError(f"click target at {box['x']:.0f},{box['y']:.0f} is outside the visible area")
    return {**box, "x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def _aim_box(page: Page, target: Locator) -> dict:
    return _visible_part(page, _box_of(target))


def _wholly_in_view(page: Page, target: Locator) -> bool:
    """A hover-only button half cut off by the screen or its list is as good as gone."""
    try:
        box = _box_of(target)
        seen = _visible_part(page, box)
    except RuntimeError:  # not rendered yet, or off screen
        return False
    return seen["width"] >= box["width"] - 1 and seen["height"] >= box["height"] - 1


def _bounds(page: Page, parent: Locator | None) -> Bounds:
    """The path's bounds: the screen, or (a hover-only target) the hovered parent's box."""
    screen = _screen(page)
    if parent is None:
        return screen
    p = parent.bounding_box()
    if p is None:
        raise RuntimeError("the hovered parent is not visible")
    return (max(p["x"], screen[0]), max(p["y"], screen[1]),
            min(p["x"] + p["width"], screen[2]), min(p["y"] + p["height"], screen[3]))


def _point(box: dict, frac: tuple[float, float]) -> tuple[float, float]:
    x0, y0, x1, y1 = zone(box)
    return x0 + (x1 - x0) * frac[0], y0 + (y1 - y0) * frac[1]


def cursor(page: Page, seed: int | None = None) -> None:
    """Put the cursor on the page (again, after a navigation) where it last was. *seed* fixes
    this page's moves; by default they are seeded from the page's URL on first use."""
    if seed is not None:
        _rngs[page] = random.Random(seed)
    x, y = _where(page)
    page.evaluate(_CURSOR, {"x": x, "y": y})


def reveal(page: Page, element: Locator) -> None:
    """Scroll *element*'s top into the upper part of its scroll container, smoothly, unless it
    is there already; fail loudly if it does not get there (a hover toolbar drawn at an
    element's top edge is off screen while that top is)."""
    element.evaluate(_REVEAL, REVEAL_BAND)
    handle = element.element_handle(timeout=TRIAL_TIMEOUT_MS)
    try:
        frame = handle.owner_frame()  # an element inside an iframe is polled in that frame
        if frame is None:
            raise RuntimeError("the element to reveal is not in a frame")
        # Poll in the page until the scroll lands and the element holds still, not a sleep.
        frame.wait_for_function(_REVEAL_SETTLED, arg=[handle, REVEAL_BAND],
                                polling=REVEAL_POLL_MS, timeout=REVEAL_TIMEOUT_MS)
    except PlaywrightError as err:
        raise RuntimeError(f"could not scroll the element's top into view: {err}") from err
    finally:
        handle.dispose()


def _play(page: Page, path: list[Point]) -> None:
    """Animate the drawn cursor along *path* and walk the real mouse along it, in about the
    path's planned time."""
    page.evaluate(_ANIMATE, [[t, x, y] for t, x, y in path])
    t0, waited = time.monotonic(), 0.0
    for t, x, y in mouse_samples(path):
        # Behind schedule (slow mouse.move calls): wait less. Never wait past the plan.
        wait = t - max(waited, (time.monotonic() - t0) * 1000)
        if wait > 0:
            page.wait_for_timeout(wait)
            waited += wait
        page.mouse.move(x, y)
    _last[page] = path[-1][1:]


def _travel(page: Page, to: tuple[float, float], box: dict, bounds: Bounds,
            curved: bool = True) -> None:
    _play(page, plan_path(_where(page), to, target_w=box["width"], target_h=box["height"],
                          rng=_rng(page), bounds=bounds, curved=curved))


def _step(page: Page, to: tuple[float, float], bounds: Bounds) -> None:
    """A short, straight correction (a re-aim)."""
    rng = _rng(page)
    _play(page, curve(_where(page), to, rng.uniform(*REAIM_MS), 0.0, rng, bounds))


def move(page: Page, x: float, y: float, *, target_w: float = DEFAULT_TARGET_PX,
         target_h: float = DEFAULT_TARGET_PX) -> None:
    cursor(page)
    _travel(page, (x, y), {"width": target_w, "height": target_h}, _screen(page))


Aim = Callable[[dict], tuple[float, float]]  # a target's visible box -> the point to go to


def _confirm(page: Page, target: Locator, kind: str, at: tuple[float, float], retarget: Aim,
             bounds: Bounds) -> tuple[float, float]:
    """Ask Playwright whether the exact drawn point takes the click (or hover): its trial run
    hit-tests that point. If not, re-aim once at *retarget*'s point on a fresh read of the
    box (a new landing spot for a click; the same spot on the element for a hover point),
    then fail loudly rather than click elsewhere."""
    failure: PlaywrightError | None = None
    for attempt in range(2):
        box = _box_of(target)
        pos = {"x": at[0] - box["bx"] - box["bl"], "y": at[1] - box["by"] - box["bt"]}
        try:
            getattr(target, kind)(trial=True, position=pos, timeout=TRIAL_TIMEOUT_MS)
            return at
        except PlaywrightError as err:
            failure = err
        if attempt == 0:
            at = retarget(_aim_box(page, target))
            _step(page, at, bounds)
    raise RuntimeError(f"{kind} target does not take the {kind} at "
                       f"({at[0]:.0f}, {at[1]:.0f}): {failure}")


def hover(page: Page, target: Locator, at: tuple[float, float] | None = None) -> None:
    """Move onto *target* (to *at*, a page point inside it, or a landing point) and leave the
    real mouse exactly under the drawn cursor. Not Locator.hover(), which hovers its centre.
    If the element moves on the way (a list re-anchoring), the point moves with it."""
    cursor(page)
    # No position-less trial: it hit-tests the centre and may scroll, undoing a reveal.
    # _confirm checks the exact point once the cursor is there.
    target.wait_for(state="visible", timeout=TRIAL_TIMEOUT_MS)
    box = _aim_box(page, target)
    if at is None:
        at = landing_point(box, _rng(page))
    elif not (box["x"] <= at[0] <= box["x"] + box["width"]
              and box["y"] <= at[1] <= box["y"] + box["height"]):
        raise ValueError(f"hover point {at} is outside its element's visible part")
    dx, dy = at[0] - box["x"], at[1] - box["y"]

    def same_spot(b: dict) -> tuple[float, float]:
        return b["x"] + dx, b["y"] + dy

    bounds = _screen(page)
    _travel(page, at, box, bounds)
    _settle_on(page, target, box, same_spot, bounds)
    _confirm(page, target, "hover", _where(page), same_spot, bounds)


def _settle_on(page: Page, target: Locator, box: dict, aim: Aim, bounds: Bounds) -> dict:
    """After the approach, follow a target that moved (a list re-rendering under the cursor):
    re-read its box, re-aim at the same spot on it, and fail loudly if it never holds still."""
    for attempt in range(MAX_REAIMS + 1):
        now = _aim_box(page, target)
        if max(abs(now["x"] - box["x"]), abs(now["y"] - box["y"])) <= REAIM_TOLERANCE_PX:
            return box
        if attempt == MAX_REAIMS:
            raise RuntimeError(f"target kept moving: {MAX_REAIMS} re-aims, last at "
                               f"{now['x']:.0f},{now['y']:.0f}")
        box = now
        _step(page, aim(box), bounds)
    return box


def _nudge(box: dict, at: tuple[float, float], rng: random.Random) -> tuple[float, float]:
    """A pre-click correction of a pixel or three, still inside the landing zone."""
    x = at[0] + rng.uniform(-MICRO_ADJUST_PX, MICRO_ADJUST_PX)
    y = at[1] + rng.uniform(-MICRO_ADJUST_PX, MICRO_ADJUST_PX)
    return clamp(x, y, zone(box))


def _ready(page: Page, target: Locator, within: Locator | None) -> None:
    """Before the approach. A plain target: Playwright scrolls it into view and checks it is
    actionable. A hover-only one (*within*): no Playwright scroll, which would scroll the
    hovered parent away and hide it; if it is out of view, reveal the parent ourselves."""
    if within is None:
        target.scroll_into_view_if_needed()
        target.click(trial=True, timeout=TRIAL_TIMEOUT_MS)
        return
    target.wait_for(state="visible", timeout=TRIAL_TIMEOUT_MS)  # a toolbar renders late
    if _wholly_in_view(page, target):
        return
    reveal(page, within)
    if not _wholly_in_view(page, target):
        raise RuntimeError("hover-only click target is outside the visible area, even with its "
                           "parent scrolled into view")


def click(page: Page, target: Locator, settle: int = 900, *, within: Locator | None = None) -> None:
    """Move onto *target* like a hand and click exactly where the drawn cursor is. *within*:
    the element whose hover keeps a hover-only target shown; the path stays inside it, does
    not bow and does not overshoot."""
    cursor(page)
    _ready(page, target, within)
    rng = _rng(page)
    box = _aim_box(page, target)  # raises if it is still out of view
    frac = (rng.random(), rng.random())
    bounds = _bounds(page, within)
    _travel(page, _point(box, frac), box, bounds, curved=within is None)
    box = _settle_on(page, target, box, lambda b: _point(b, frac), bounds)
    at = _where(page)
    page.wait_for_timeout(rng.uniform(*PRE_CLICK_MS))  # a person settles before clicking
    if rng.random() < MICRO_ADJUST_P:
        to = _nudge(box, at, rng)
        _play(page, curve(at, to, rng.uniform(*MICRO_ADJUST_MS), 0.0, rng, bounds))
        at = to
    at = _confirm(page, target, "click", at, lambda b: _point(b, (rng.random(), rng.random())),
                  bounds)
    page.evaluate(_RIPPLE, {"x": at[0], "y": at[1]})
    # page.mouse at the drawn point, not Locator.click(position=): that counts from the
    # padding box, and a bordered target would be clicked off the drawn cursor.
    page.mouse.click(*at)
    page.wait_for_timeout(settle)
    cursor(page)  # a click that navigated drops the cursor; put it back


def idle(page: Page, seconds: float) -> None:
    """Hold on the shot for *seconds* while the cursor drifts slowly, a few pixels at a time,
    around where it rests; a hand on a mouse is never perfectly still. Holds from
    IDLE_MIN_S drift at least once: the first drift comes early and shrinks to fit."""
    cursor(page)
    rng, anchor, bounds = _rng(page), _where(page), _screen(page)
    left, first = seconds * 1000, True
    while left >= IDLE_MIN_S * 1000:
        rest = rng.uniform(*(IDLE_FIRST_REST_MS if first else IDLE_REST_MS))
        drift = rng.uniform(*IDLE_DRIFT_MS)
        if rest + drift > left:
            if not first:
                break
            scale = left * IDLE_FIT / (rest + drift)
            rest, drift = rest * scale, drift * scale
        page.wait_for_timeout(rest)
        angle, r = rng.uniform(0, 2 * math.pi), rng.uniform(2.0, IDLE_RADIUS_PX)
        to = clamp(anchor[0] + r * math.cos(angle), anchor[1] + r * math.sin(angle), bounds)
        _play(page, curve(_where(page), to, drift, rng.uniform(-1.0, 1.0), rng, bounds))
        left -= rest + drift
        first = False
    if left > 0:
        page.wait_for_timeout(left)


def wheel(page: Page, dy: int, steps: int = 4) -> None:
    """Scroll *dy* in *steps* flicks, bigger in the middle, at slightly uneven intervals."""
    rng = _rng(page)
    weights = [math.sin(math.pi * (i + 0.5) / steps) for i in range(steps)]
    total = sum(weights)
    for w in weights:
        page.mouse.wheel(0, dy * w / total)
        page.wait_for_timeout(WHEEL_INTERVAL_MS * rng.uniform(0.8, 1.25))

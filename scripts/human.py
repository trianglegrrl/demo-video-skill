"""Human-paced pointer for headless takes: a drawn cursor that glides, hovers, clicks.

Headless Chromium draws no mouse pointer, and Playwright clicks land instantly; both read as
a robot on camera. `click(page, locator)` moves a visible cursor to the target over ~0.7 s,
rests, shows a click ripple, clicks, then lets the result settle.
"""
from __future__ import annotations

from playwright.sync_api import Locator, Page

_CURSOR = """(() => {
  if (document.getElementById('__cur')) return;
  const c = document.createElement('div');
  c.id = '__cur';
  c.style.cssText = 'position:fixed;left:%(x)dpx;top:%(y)dpx;width:26px;height:26px;'
    + 'z-index:2147483647;pointer-events:none;'
    + 'transition:left .7s cubic-bezier(.3,.1,.2,1),top .7s cubic-bezier(.3,.1,.2,1);';
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
  r.style.cssText = 'position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%%;'
    + 'border:3px solid rgba(116,192,252,.9);opacity:0;z-index:2147483646;pointer-events:none;'
    + 'transition:transform .45s ease-out,opacity .45s ease-out;';
  document.body.appendChild(r);
})()"""

_last = {}


def cursor(page: Page) -> None:
    """Put the cursor on the page (again, after a navigation) where it last was."""
    x, y = _last.get(id(page), (640, 420))
    page.evaluate(_CURSOR % {"x": x, "y": y})


def move(page: Page, x: float, y: float) -> None:
    cursor(page)
    page.evaluate(f"(() => {{ const c = document.getElementById('__cur');"
                  f" c.style.left = '{x}px'; c.style.top = '{y}px'; }})()")
    page.wait_for_timeout(750)
    page.mouse.move(x, y)
    _last[id(page)] = (x, y)


def click(page: Page, target: Locator, settle: int = 900) -> None:
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    if box is None:
        raise RuntimeError("click target is not visible")
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    move(page, x, y)
    page.wait_for_timeout(350)  # a person settles on the target before clicking
    page.evaluate(f"(() => {{ const r = document.getElementById('__rip');"
                  f" r.style.transition = 'none'; r.style.left = '{x}px'; r.style.top = '{y}px';"
                  f" r.style.transform = 'scale(.4)'; r.style.opacity = '1'; r.offsetWidth;"
                  f" r.style.transition = 'transform .45s ease-out, opacity .45s ease-out';"
                  f" r.style.transform = 'scale(1.6)'; r.style.opacity = '0'; }})()")
    target.click()
    page.wait_for_timeout(settle)
    cursor(page)  # a click that navigated drops the cursor; put it back


def wheel(page: Page, dy: int, steps: int = 4) -> None:
    for _ in range(steps):
        page.mouse.wheel(0, dy / steps)
        page.wait_for_timeout(160)

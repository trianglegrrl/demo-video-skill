"""Shared guards for the demo-video tests: what they need from the machine.

Locally a missing browser or ffmpeg skips the tests that need it (doctor.sh says how to
install them). CI sets DEMO_VIDEO_TESTS_STRICT=1, where a missing one FAILS instead: a test
that skips in CI is a test that never runs.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

STRICT = os.environ.get("DEMO_VIDEO_TESTS_STRICT") == "1"


def need(ok: bool, what: str) -> None:
    """Skip (fail, under DEMO_VIDEO_TESTS_STRICT=1) a test whose requirement is missing."""
    if ok:
        return
    if STRICT:
        pytest.fail(f"DEMO_VIDEO_TESTS_STRICT=1 and this test needs {what}")
    pytest.skip(f"needs {what}")


@pytest.fixture(scope="session")
def chromium_launches() -> None:
    """Playwright's Chromium starts on this machine (Take and the in-page tests need it)."""
    from playwright.sync_api import Error, sync_playwright
    pw = sync_playwright().start()
    try:
        pw.chromium.launch().close()
        ok, why = True, ""
    except Error as err:
        ok, why = False, str(err).splitlines()[0]
    finally:
        pw.stop()
    need(ok, f"Playwright Chromium ({why})")


@pytest.fixture
def ffmpeg() -> None:
    need(bool(shutil.which("ffmpeg")), "ffmpeg")


@pytest.fixture
def drawtext() -> None:
    """ffmpeg can draw text: every rendered shot needs it, and Homebrew's plain ffmpeg can't."""
    filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True,
                             text=True).stdout if shutil.which("ffmpeg") else ""
    need(" drawtext " in filters, "ffmpeg with drawtext (see doctor.sh)")

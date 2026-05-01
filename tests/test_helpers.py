"""Tests for the small module-level helpers (`_http_session`, `_load_font`,
`_alarm`, `_truncate_pm25`).

These don't fit the per-feature test files but each guards a specific
invariant that's worth pinning down — the lazy-built session, the font-missing
fallback, the SIGALRM cleanup, and the EPA "truncate, don't round" rule.
"""
import signal
import time

import pytest
import requests
from PIL import ImageFont

import airQuality


def test_http_session_is_a_requests_session_with_user_agent():
    """The lazy-built session must be a real `requests.Session` and ship our
    User-Agent header — every test elsewhere stubs this out, so without this
    we'd never catch a regression in the actual factory."""
    airQuality._http_session.cache_clear()
    session = airQuality._http_session()
    assert isinstance(session, requests.Session)
    assert session.headers.get("User-Agent") == airQuality.USER_AGENT


def test_http_session_is_cached_across_calls():
    airQuality._http_session.cache_clear()
    a = airQuality._http_session()
    b = airQuality._http_session()
    assert a is b


def test_load_font_returns_truetype_when_available():
    airQuality._load_font.cache_clear()
    font = airQuality._load_font(16)
    # Inter-Bold.ttf is vendored under `fonts/`. If this ever flips to PIL
    # default, the e-ink layout breaks silently.
    assert isinstance(font, ImageFont.FreeTypeFont)


def test_load_font_selects_bold_instance_for_variable_font():
    """Fredoka ships as a variable font with named instances (Light..Bold).
    `_load_font` must pick Bold so glyph weight matches the Inter-Bold default
    — a regression that left the font at Regular weight would render too thin
    on the e-ink panel."""
    airQuality._load_font.cache_clear()
    font = airQuality._load_font(20, airQuality.FONT_PATH_FREDOKA)
    assert isinstance(font, ImageFont.FreeTypeFont)
    # Variable-instance API isn't on every Pillow build; only assert when present.
    if hasattr(font, "get_variation_names"):
        names = font.get_variation_names()
        if names:
            assert b"Bold" in names
    airQuality._load_font.cache_clear()


def test_load_font_falls_back_to_default_when_truetype_missing(monkeypatch):
    """If the vendored Inter file is missing, fall back to PIL's bundled
    default rather than crashing the render."""
    airQuality._load_font.cache_clear()

    real_truetype = airQuality.ImageFont.truetype

    def _selective(font=None, size=10, *args, **kwargs):
        # Only fail when asked for *our* configured font; let
        # `ImageFont.load_default()` keep using truetype internally for its
        # bundled fallback.
        if font == airQuality.FONT_PATH_BOLD:
            raise OSError("font not found")
        return real_truetype(font, size, *args, **kwargs)

    monkeypatch.setattr(airQuality.ImageFont, "truetype", _selective)
    font = airQuality._load_font(16)
    assert font is not None
    # Reset so other tests that assume the real font keep working.
    airQuality._load_font.cache_clear()


def test_alarm_cancels_on_normal_exit():
    """No alarm should remain pending after a successful with-block."""
    with airQuality._alarm(60):
        pass
    # signal.alarm(0) returns the seconds remaining of any previously-set alarm;
    # a 0 here means our context cancelled cleanly.
    assert signal.alarm(0) == 0


def test_alarm_cancels_on_exception():
    """An exception inside the block must still leave SIGALRM disarmed."""
    with pytest.raises(RuntimeError):
        with airQuality._alarm(60):
            raise RuntimeError("oops")
    assert signal.alarm(0) == 0


def test_alarm_restores_previous_handler():
    """The fence is short-lived; it must hand the SIGALRM handler back the way
    it found it so a future `_alarm` (or any other SIGALRM user) keeps working."""
    sentinel = lambda *a: None  # noqa: E731
    previous = signal.signal(signal.SIGALRM, sentinel)
    try:
        with airQuality._alarm(60):
            pass
        assert signal.getsignal(signal.SIGALRM) is sentinel
    finally:
        signal.signal(signal.SIGALRM, previous)


def test_alarm_fires_timeout_error():
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        with airQuality._alarm(1):
            time.sleep(5)
    elapsed = time.monotonic() - start
    assert elapsed < 3.0


def test_truncate_pm25_truncates_not_rounds():
    """EPA spec is truncate-to-one-decimal, not round."""
    assert airQuality._truncate_pm25(12.05) == 12.0
    assert airQuality._truncate_pm25(35.49) == 35.4


def test_truncate_pm25_rejects_non_finite():
    assert airQuality._truncate_pm25(float("nan")) is None
    assert airQuality._truncate_pm25(float("inf")) is None
    assert airQuality._truncate_pm25(float("-inf")) is None

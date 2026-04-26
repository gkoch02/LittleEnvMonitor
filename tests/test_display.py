"""Tests for `display_air_quality` end-to-end against the FakeEPD stub.

These do real PIL rendering (DejaVuSans-Bold is present on Ubuntu CI runners
via fonts-dejavu-core, and on the Pi via the deploy script). They cover the
SR1 (`epd.init() == -1`) and SR2 (alarm watchdog) reliability fences.
"""
import time

import pytest

import airQuality
from waveshare_epd import epd2in13b_V4


def _payload():
    return {"PM2.5": 12.0, "PM10": 18.0, "Temp": 70, "Humidity": 45, "Time": "12:00 PM"}


@pytest.fixture(autouse=True)
def _reset_epd_class(monkeypatch):
    """Reset FakeEPD class-level overrides between tests."""
    original_init = epd2in13b_V4.EPD.init
    original_display = epd2in13b_V4.EPD.display
    yield
    epd2in13b_V4.EPD.init = original_init
    epd2in13b_V4.EPD.display = original_display


def test_normal_render_drives_panel_lifecycle():
    captured = []

    def _record_display(self, *args, **kwargs):
        captured.append(self.calls[-1])  # latest call before display

    # Hold a reference to the EPD instance the function constructs by capturing
    # via a wrapper class attr.
    instances = []
    original_new = epd2in13b_V4.EPD.__new__

    def _tracking_new(cls, *args, **kwargs):
        inst = original_new(cls)
        instances.append(inst)
        return inst

    epd2in13b_V4.EPD.__new__ = _tracking_new
    try:
        airQuality.display_air_quality(
            _payload(), alert=False, trend_symbol="+", category="Good",
            cat_color="black", city="Campbell",
        )
    finally:
        epd2in13b_V4.EPD.__new__ = original_new

    assert instances, "display_air_quality should have constructed an EPD"
    calls = [c[0] for c in instances[0].calls]
    # init, Clear, two getbuffer (black + red), display, sleep
    assert calls == ["init", "Clear", "getbuffer", "getbuffer", "display", "sleep"]


def test_init_minus_one_raises_but_still_sleeps():
    epd2in13b_V4.EPD.init = lambda self: (self.calls.append(("init",)) or -1)

    instances = []
    original_new = epd2in13b_V4.EPD.__new__

    def _tracking_new(cls, *args, **kwargs):
        inst = original_new(cls)
        instances.append(inst)
        return inst

    epd2in13b_V4.EPD.__new__ = _tracking_new
    try:
        with pytest.raises(RuntimeError, match="epd.init failed"):
            airQuality.display_air_quality(
                _payload(), alert=False, trend_symbol="+", category="Good",
                cat_color="black", city="Campbell",
            )
    finally:
        epd2in13b_V4.EPD.__new__ = original_new

    # Panel sleep invariant: even on init failure, sleep still runs.
    calls = [c[0] for c in instances[0].calls]
    assert calls == ["init", "sleep"]


def test_stuck_display_triggers_alarm_timeout(monkeypatch):
    monkeypatch.setattr(airQuality, "DISPLAY_TIMEOUT_SEC", 1)

    def _hang(self, *args, **kwargs):
        self.calls.append(("display_hang",))
        time.sleep(5)  # > timeout

    epd2in13b_V4.EPD.display = _hang

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        airQuality.display_air_quality(
            _payload(), alert=False, trend_symbol="-", category="Good",
            cat_color="black", city="Campbell",
        )
    elapsed = time.monotonic() - start
    # Should fire well before the 5s sleep would naturally finish.
    assert elapsed < 3.0


def test_stale_render_does_not_raise():
    # Just confirm the [CACHED] branch executes cleanly with the same fake EPD.
    airQuality.display_air_quality(
        _payload(), alert=False, trend_symbol="?", category="Moderate",
        cat_color="black", city="Campbell", stale=True,
    )


def test_alert_render_does_not_raise():
    airQuality.display_air_quality(
        _payload(), alert=True, trend_symbol="+", category="Unhealthy",
        cat_color="red", city="Campbell",
    )

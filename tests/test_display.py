"""Tests for `display_air_quality` end-to-end against the FakeEPD stub.

These do real PIL rendering (the Space Grotesk variable font is vendored at
`fonts/SpaceGrotesk-VariableFont_wght.ttf`, so they work on any host without
needing system fonts installed). They are the only coverage of the SR1
(`epd.init() == -1`) and SR2 (alarm watchdog) reliability fences — keeping them
in the suite is what gets the project from ~70 % coverage of `airQuality.py`
to ~91 %.
"""
import time

import pytest

import airQuality
from waveshare_epd import epd2in13b_V4


def _payload():
    return {"PM2.5": 12.0, "PM10": 18.0, "Temp": 70, "Humidity": 45, "Time": "12:00 PM"}


@pytest.fixture(autouse=True)
def _clear_epd_instances():
    """Reset the shared FakeEPD instance log between tests."""
    epd2in13b_V4.EPD.instances.clear()


def test_normal_render_drives_panel_lifecycle():
    airQuality.display_air_quality(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell",
    )
    assert len(epd2in13b_V4.EPD.instances) == 1
    calls = [c[0] for c in epd2in13b_V4.EPD.instances[0].calls]
    # init, Clear, two getbuffer (black + red), display, sleep
    assert calls == ["init", "Clear", "getbuffer", "getbuffer", "display", "sleep"]


def test_init_minus_one_raises_but_still_sleeps(monkeypatch):
    monkeypatch.setattr(
        epd2in13b_V4.EPD, "init",
        lambda self: (self.calls.append(("init",)) or -1),
    )
    with pytest.raises(RuntimeError, match="epd.init failed"):
        airQuality.display_air_quality(
            _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
            cat_color="black", city="Campbell",
        )
    # Panel sleep invariant: even on init failure, sleep still runs.
    calls = [c[0] for c in epd2in13b_V4.EPD.instances[0].calls]
    assert calls == ["init", "sleep"]


def test_stuck_display_triggers_alarm_timeout(monkeypatch):
    monkeypatch.setattr(airQuality, "DISPLAY_TIMEOUT_SEC", 1)

    def _hang(self, *args, **kwargs):
        self.calls.append(("display_hang",))
        time.sleep(5)  # > timeout

    monkeypatch.setattr(epd2in13b_V4.EPD, "display", _hang)

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        airQuality.display_air_quality(
            _payload(), alert=False, trend_symbol="-", aqi_value=50, category="Good",
            cat_color="black", city="Campbell",
        )
    elapsed = time.monotonic() - start
    # Should fire well before the 5s sleep would naturally finish.
    assert elapsed < 3.0
    # And the panel-sleep invariant must still have run via the finally.
    calls = [c[0] for c in epd2in13b_V4.EPD.instances[0].calls]
    assert calls[-1] == "sleep"


def test_stuck_sleep_is_also_fenced(monkeypatch):
    """SR2 follow-up: SIGALRM is one-shot, so the finally re-arms its own
    alarm. A hung `epd.sleep()` must still time out."""
    monkeypatch.setattr(airQuality, "SLEEP_TIMEOUT_SEC", 1)

    def _hang_sleep(self):
        self.calls.append(("sleep_hang",))
        time.sleep(5)

    monkeypatch.setattr(epd2in13b_V4.EPD, "sleep", _hang_sleep)

    start = time.monotonic()
    # The TimeoutError from the second alarm bubbles out through the finally;
    # display_air_quality logs it via log.exception in the wrapper. We expect
    # the call to return within ~SLEEP_TIMEOUT_SEC, not hang for 5s.
    airQuality.display_air_quality(
        _payload(), alert=False, trend_symbol="-", aqi_value=50, category="Good",
        cat_color="black", city="Campbell",
    )
    elapsed = time.monotonic() - start
    assert elapsed < 3.0


def test_stale_render_does_not_raise():
    airQuality.display_air_quality(
        _payload(), alert=False, trend_symbol="?", aqi_value=75, category="Moderate",
        cat_color="black", city="Campbell", stale=True,
    )


def test_alert_render_does_not_raise():
    airQuality.display_air_quality(
        _payload(), alert=True, trend_symbol="+", aqi_value=160, category="Unhealthy",
        cat_color="red", city="Campbell",
    )


def test_render_handles_aqi_value_none():
    """Sanity check: pre-AQI cache entries can land on the display path."""
    airQuality.display_air_quality(
        _payload(), alert=False, trend_symbol="-", aqi_value=None, category="Good",
        cat_color="black", city="Campbell",
    )

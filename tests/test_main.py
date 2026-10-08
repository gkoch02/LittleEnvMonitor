"""Integration tests for the `main()` orchestration paths.

These cover the branches the unit tests don't reach: live success, weather
fallback wiring, cache-fallback rendering, the "bad config exits before the
try" invariant, the trend / "AQI Rising!" rules, and stale-sample handling.
The display function is replaced with a recorder fixture — the e-ink draw is
exercised in its own dedicated tests, not here.
"""
import json
import logging
import time
from datetime import datetime, timezone

import pytest
from conftest import network_down

import airQuality


@pytest.fixture
def conf(tmp_path, monkeypatch):
    """Write a valid airquality.conf and point the script at it."""
    path = tmp_path / "airquality.conf"
    path.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 12345\n"
        "[weather]\nlatitude = 37.5\nlongitude = -121.9\n"
    )
    monkeypatch.setattr(airQuality, "CONF_PATH", str(path))
    return path


@pytest.fixture
def display_recorder(monkeypatch):
    """Replace display_air_quality with a recorder so tests can assert what got drawn."""
    calls = []

    def _record(
        data, alert, trend_symbol, aqi_value, category, cat_color, city, stale=False,
        theme=airQuality.DEFAULT_THEME,
    ):
        calls.append({
            "data": dict(data),
            "alert": alert,
            "trend_symbol": trend_symbol,
            "aqi_value": aqi_value,
            "category": category,
            "cat_color": cat_color,
            "city": city,
            "stale": stale,
            "theme": theme,
        })

    monkeypatch.setattr(airQuality, "display_air_quality", _record)
    return calls


def _purple_payload(pm25=20.0, pm10=22.0, temp=70, humidity=40, last_seen_epoch=...):
    # `...` sentinel (rather than None) lets callers explicitly request
    # last_seen_epoch=None (missing) without accidentally getting "fresh now".
    if last_seen_epoch is ...:
        last_seen_epoch = time.time()
    return {
        "PM2.5": pm25,
        "PM10": pm10,
        "Temp": temp,
        "Humidity": humidity,
        "Time": "12:00 PM",
        "LastSeenEpoch": last_seen_epoch,
    }


def _fetch_returns(monkeypatch, **payload_kwargs):
    monkeypatch.setattr(
        airQuality, "fetch_purpleair_data",
        lambda *a, **kw: _purple_payload(**payload_kwargs),
    )


def _summary_lines(caplog):
    return [m for m in caplog.messages if m.startswith("summary path=")]


def test_live_success_writes_cache_and_heartbeat(state_dir, conf, display_recorder, monkeypatch):
    _fetch_returns(monkeypatch)

    rc = airQuality.main([])

    assert rc == 0
    assert len(display_recorder) == 1
    assert display_recorder[0]["stale"] is False
    assert display_recorder[0]["alert"] is False  # no prior cache → no rising banner
    # AQI threading: PM2.5=20.0 should land in the Moderate band (51-100).
    assert display_recorder[0]["aqi_value"] == airQuality.pm25_to_aqi(20.0)
    assert 51 <= display_recorder[0]["aqi_value"] <= 100
    assert display_recorder[0]["category"] == "Moderate"
    cached = json.loads((state_dir / "airquality" / "last_reading.json").read_text())
    assert cached["PM2.5"] == 20.0
    assert (state_dir / "airquality" / "heartbeat").is_file()


def test_purpleair_fails_with_cache_renders_stale(
    state_dir, seed_cache, conf, display_recorder, monkeypatch
):
    seed_cache(_purple_payload(pm25=15.0))
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", network_down)

    rc = airQuality.main([])

    assert rc == 1
    assert len(display_recorder) == 1
    assert display_recorder[0]["stale"] is True
    assert display_recorder[0]["alert"] is False  # banner suppressed in stale renders
    # Heartbeat should NOT be touched on cache fallback.
    assert not (state_dir / "airquality" / "heartbeat").exists()


def test_purpleair_fails_no_cache_returns_one(state_dir, conf, display_recorder, monkeypatch):
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", network_down)

    rc = airQuality.main([])

    assert rc == 1
    assert display_recorder == []  # nothing drawn at all
    assert not (state_dir / "airquality" / "heartbeat").exists()


def test_weather_fallback_fills_missing_temp_humidity(
    state_dir, conf, display_recorder, monkeypatch
):
    _fetch_returns(monkeypatch, temp="N/A", humidity="N/A")
    monkeypatch.setattr(
        airQuality, "fetch_local_weather",
        lambda lat, lon, **kw: {"Temp": 65, "Humidity": 55},
    )

    rc = airQuality.main([])

    assert rc == 0
    assert display_recorder[0]["data"]["Temp"] == 65
    assert display_recorder[0]["data"]["Humidity"] == 55


def test_weather_fallback_failure_logs_but_does_not_raise(
    state_dir, conf, display_recorder, monkeypatch, caplog
):
    _fetch_returns(monkeypatch, temp="N/A", humidity="N/A")

    def _weather_boom(*a, **kw):
        raise RuntimeError("openmeteo down")

    monkeypatch.setattr(airQuality, "fetch_local_weather", _weather_boom)

    with caplog.at_level(logging.ERROR, logger="airquality"):
        rc = airQuality.main([])

    assert rc == 0
    assert display_recorder[0]["data"]["Temp"] == "N/A"
    assert display_recorder[0]["data"]["Humidity"] == "N/A"
    assert "Local weather fallback failed" in caplog.messages


def test_rising_banner_fires_at_or_above_threshold(
    state_dir, seed_cache, conf, display_recorder, monkeypatch
):
    seed_cache(_purple_payload(pm25=10.0))
    # Delta = 5.0 == TREND_THRESHOLD → banner fires.
    _fetch_returns(monkeypatch, pm25=15.0)

    airQuality.main([])

    assert display_recorder[0]["alert"] is True
    assert display_recorder[0]["trend_symbol"] == "+"


def test_rising_banner_silent_below_threshold(
    state_dir, seed_cache, conf, display_recorder, monkeypatch
):
    seed_cache(_purple_payload(pm25=10.0))
    # Delta = 4.99 < threshold → trend marker still '+', but no banner.
    _fetch_returns(monkeypatch, pm25=14.99)

    airQuality.main([])

    assert display_recorder[0]["alert"] is False
    assert display_recorder[0]["trend_symbol"] == "+"


def test_trend_symbol_minus_when_pm25_holds_or_drops(
    state_dir, seed_cache, conf, display_recorder, monkeypatch
):
    """Equal PM2.5 must yield '-'. This is the test that catches `>` being
    loosened to `>=` in the trend rule."""
    seed_cache(_purple_payload(pm25=20.0))
    _fetch_returns(monkeypatch, pm25=20.0)

    airQuality.main([])

    assert display_recorder[0]["trend_symbol"] == "-"
    assert display_recorder[0]["alert"] is False


def test_trend_symbol_plus_on_tiny_increase(
    state_dir, seed_cache, conf, display_recorder, monkeypatch
):
    """Any strict increase, however small, yields '+' — there's no dead band."""
    seed_cache(_purple_payload(pm25=20.0))
    _fetch_returns(monkeypatch, pm25=20.0001)

    airQuality.main([])

    assert display_recorder[0]["trend_symbol"] == "+"


def test_bad_config_exits_before_try_block(tmp_path, display_recorder, monkeypatch):
    # A bad config raises SystemExit *outside* the cache-fallback try, so the
    # broad except in main() doesn't swallow it.
    bad = tmp_path / "airquality.conf"
    bad.write_text("[purpleair]\napi_key = YOUR_PURPLEAIR_API_KEY\nsensor_id = 1\n")
    monkeypatch.setattr(airQuality, "CONF_PATH", str(bad))

    with pytest.raises(SystemExit):
        airQuality.main([])
    assert display_recorder == []  # never even reached the try


def test_cache_write_failure_does_not_trigger_stale_render(
    state_dir, conf, display_recorder, monkeypatch
):
    """A persistence error after a successful display must not flip the run
    into the cache-fallback branch — the user already saw fresh data."""
    _fetch_returns(monkeypatch)

    def _boom(_data):
        raise OSError("disk full")

    monkeypatch.setattr(airQuality, "write_cache", _boom)

    rc = airQuality.main([])

    assert rc == 0  # not 1 — fresh display still happened
    assert len(display_recorder) == 1  # and no second [CACHED] render
    assert display_recorder[0]["stale"] is False


def test_heartbeat_failure_does_not_trigger_stale_render(
    state_dir, conf, display_recorder, monkeypatch
):
    _fetch_returns(monkeypatch)

    def _boom():
        raise OSError("read-only fs")

    monkeypatch.setattr(airQuality, "write_heartbeat", _boom)

    rc = airQuality.main([])

    assert rc == 0
    assert len(display_recorder) == 1
    assert display_recorder[0]["stale"] is False


def test_heartbeat_content_is_iso8601_utc(state_dir, conf, display_recorder, monkeypatch):
    """Operators alert on heartbeat staleness; the file must be parseable as UTC."""
    _fetch_returns(monkeypatch)

    rc = airQuality.main([])

    assert rc == 0
    raw = (state_dir / "airquality" / "heartbeat").read_text()
    parsed = datetime.fromisoformat(raw)
    assert parsed.tzinfo is not None
    # Within a minute of "now" — not a frozen string.
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 60


def test_missing_temp_humidity_with_no_weather_section_logs_and_continues(
    tmp_path, state_dir, display_recorder, monkeypatch, caplog
):
    """PurpleAir drops Temp/Humidity but conf has no [weather] section.
    We log and render N/A — we do NOT pull stale temp/humidity from cache."""
    conf_path = tmp_path / "airquality.conf"
    conf_path.write_text("[purpleair]\napi_key = real-key\nsensor_id = 12345\n")
    monkeypatch.setattr(airQuality, "CONF_PATH", str(conf_path))
    _fetch_returns(monkeypatch, temp="N/A", humidity="N/A")

    with caplog.at_level(logging.INFO):
        rc = airQuality.main([])

    assert rc == 0
    assert display_recorder[0]["data"]["Temp"] == "N/A"
    assert display_recorder[0]["data"]["Humidity"] == "N/A"
    assert any("no [weather] coords configured" in m for m in caplog.messages)


def test_live_path_with_unparseable_cached_pm25_treats_trend_as_first_run(
    state_dir, seed_cache, conf, display_recorder, monkeypatch
):
    """Cache exists but PM2.5 is junk: the trend behaves like a fresh start."""
    seed_cache({"PM2.5": "junk", "PM10": 0, "Temp": 0, "Humidity": 0, "Time": "x"})
    _fetch_returns(monkeypatch, pm25=20.0)

    rc = airQuality.main([])

    assert rc == 0
    assert display_recorder[0]["trend_symbol"] == "-"
    assert display_recorder[0]["alert"] is False


def test_cache_fallback_with_unparseable_pm25_returns_one_without_drawing(
    state_dir, seed_cache, conf, display_recorder, monkeypatch
):
    """Live fetch fails and the cached PM2.5 isn't a number: exit 1 without
    drawing garbage."""
    seed_cache({"PM2.5": "junk", "PM10": 0, "Temp": 0, "Humidity": 0, "Time": "x"})
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", network_down)

    rc = airQuality.main([])

    assert rc == 1
    assert display_recorder == []
    assert not (state_dir / "airquality" / "heartbeat").exists()


def test_weather_fallback_fills_only_missing_temp(
    state_dir, conf, display_recorder, monkeypatch
):
    """Only Temp is N/A — Humidity from PurpleAir must be preserved."""
    _fetch_returns(monkeypatch, temp="N/A", humidity=40)
    monkeypatch.setattr(
        airQuality, "fetch_local_weather",
        lambda lat, lon, **kw: {"Temp": 65, "Humidity": 99},
    )

    rc = airQuality.main([])

    assert rc == 0
    assert display_recorder[0]["data"]["Temp"] == 65      # filled from weather
    assert display_recorder[0]["data"]["Humidity"] == 40  # kept from PurpleAir


def test_weather_fallback_fills_only_missing_humidity(
    state_dir, conf, display_recorder, monkeypatch
):
    """Only Humidity is N/A — Temp from PurpleAir must be preserved."""
    _fetch_returns(monkeypatch, temp=70, humidity="N/A")
    monkeypatch.setattr(
        airQuality, "fetch_local_weather",
        lambda lat, lon, **kw: {"Temp": 99, "Humidity": 55},
    )

    rc = airQuality.main([])

    assert rc == 0
    assert display_recorder[0]["data"]["Temp"] == 70      # kept from PurpleAir
    assert display_recorder[0]["data"]["Humidity"] == 55  # filled from weather


def test_numeric_string_pm25_in_cache_computes_trend(
    state_dir, seed_cache, conf, display_recorder, monkeypatch
):
    """A cache that stores PM2.5 as a numeric string must still drive the trend."""
    seed_cache({"PM2.5": "10.0", "PM10": 0, "Temp": 0, "Humidity": 0, "Time": "x"})
    _fetch_returns(monkeypatch, pm25=20.0)

    rc = airQuality.main([])

    assert rc == 0
    # Delta = 10 >= TREND_THRESHOLD (5) → rising banner and '+' marker.
    assert display_recorder[0]["alert"] is True
    assert display_recorder[0]["trend_symbol"] == "+"


def test_cache_fallback_swallows_display_exception(
    state_dir, seed_cache, conf, display_recorder, monkeypatch, caplog
):
    """Cached data is valid but the panel errors during the [CACHED] render.
    We log, don't crash, and still return 1."""
    seed_cache(_purple_payload(pm25=15.0))

    def _display_boom(*a, **kw):
        raise RuntimeError("panel exploded")

    monkeypatch.setattr(airQuality, "fetch_purpleair_data", network_down)
    monkeypatch.setattr(airQuality, "display_air_quality", _display_boom)

    with caplog.at_level(logging.ERROR):
        rc = airQuality.main([])

    assert rc == 1
    assert any("Failed to display cached data" in m for m in caplog.messages)


# --- `summary path=...` log line --------------------------------------------
# Operators grep journalctl for this line; each exit path gets its own tag.


def test_summary_logs_live_branch_on_success(
    state_dir, conf, display_recorder, monkeypatch, caplog
):
    _fetch_returns(monkeypatch)

    with caplog.at_level(logging.INFO, logger="airquality"):
        airQuality.main([])

    summary_msgs = _summary_lines(caplog)
    assert len(summary_msgs) == 1
    assert "path=live" in summary_msgs[0]
    assert "pm25=" in summary_msgs[0]
    assert "rising=" in summary_msgs[0]


def test_summary_logs_cache_fallback_branch(
    state_dir, seed_cache, conf, display_recorder, monkeypatch, caplog
):
    seed_cache(_purple_payload(pm25=15.0))
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", network_down)

    with caplog.at_level(logging.INFO, logger="airquality"):
        rc = airQuality.main([])

    assert rc == 1
    summary_msgs = _summary_lines(caplog)
    assert len(summary_msgs) == 1
    assert "path=cache_fallback" in summary_msgs[0]
    assert "pm25=15.0" in summary_msgs[0]


def test_summary_logs_fail_branch_when_no_cache(
    state_dir, conf, display_recorder, monkeypatch, caplog
):
    """No cache on disk → `path=fail`, distinct from `cache_fallback` because
    monitoring should alert harder here (nothing on the panel at all)."""
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", network_down)

    with caplog.at_level(logging.INFO, logger="airquality"):
        rc = airQuality.main([])

    assert rc == 1
    summary_msgs = _summary_lines(caplog)
    assert len(summary_msgs) == 1
    assert "path=fail" in summary_msgs[0]


def test_summary_logs_dry_run_branch_on_success(
    tmp_path, state_dir, conf, monkeypatch, caplog
):
    _fetch_returns(monkeypatch)

    with caplog.at_level(logging.INFO, logger="airquality"):
        rc = airQuality.main(["--dry-run", str(tmp_path / "preview.png")])

    assert rc == 0
    summary_msgs = _summary_lines(caplog)
    assert len(summary_msgs) == 1
    assert "path=dry_run " in summary_msgs[0]


def test_summary_logs_dry_run_failed_branch_on_fetch_error(
    tmp_path, state_dir, conf, monkeypatch, caplog
):
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", network_down)

    with caplog.at_level(logging.INFO, logger="airquality"):
        rc = airQuality.main(["--dry-run", str(tmp_path / "preview.png")])

    assert rc == 1
    summary_msgs = _summary_lines(caplog)
    assert len(summary_msgs) == 1
    assert "path=dry_run_failed" in summary_msgs[0]


# --- Stale PurpleAir sample handling ----------------------------------------
# The freshness policy itself is unit-tested via `_is_fresh` in
# test_fetch_purpleair.py; these cover main()'s wiring of it.


def test_stale_purpleair_sample_falls_back_to_cache(
    state_dir, seed_cache, conf, display_recorder, monkeypatch
):
    """A `last_seen` older than FRESHNESS_THRESHOLD_SEC must not be treated as
    a live update: no heartbeat, no advancing the cache to the stale payload,
    and the previous cached reading gets rendered as [CACHED]."""
    cache_path = seed_cache(_purple_payload(pm25=11.0))
    stale_epoch = time.time() - airQuality.FRESHNESS_THRESHOLD_SEC - 1
    _fetch_returns(monkeypatch, pm25=99.0, last_seen_epoch=stale_epoch)

    rc = airQuality.main([])

    assert rc == 1
    assert len(display_recorder) == 1
    assert display_recorder[0]["stale"] is True
    # The [CACHED] render shows the *previous* good reading, not the stale
    # PM2.5=99.0 payload that just came back.
    assert display_recorder[0]["data"]["PM2.5"] == 11.0
    assert not (state_dir / "airquality" / "heartbeat").exists()
    # A stale sample must never overwrite the cache.
    assert json.loads(cache_path.read_text())["PM2.5"] == 11.0


def test_stale_purpleair_sample_no_cache_returns_one_without_drawing(
    state_dir, conf, display_recorder, monkeypatch
):
    stale_epoch = time.time() - airQuality.FRESHNESS_THRESHOLD_SEC - 1
    _fetch_returns(monkeypatch, last_seen_epoch=stale_epoch)

    rc = airQuality.main([])

    assert rc == 1
    assert display_recorder == []
    assert not (state_dir / "airquality" / "heartbeat").exists()


def test_fresh_purpleair_sample_at_threshold_boundary_is_accepted(
    state_dir, conf, display_recorder, monkeypatch
):
    """Exactly at FRESHNESS_THRESHOLD_SEC is still fresh (<=, not <)."""
    # Pin time.time() so main() and this test agree on "now" to the microsecond.
    fixed_now = 1_700_010_000.0
    monkeypatch.setattr(airQuality.time, "time", lambda: fixed_now)
    _fetch_returns(monkeypatch, last_seen_epoch=fixed_now - airQuality.FRESHNESS_THRESHOLD_SEC)

    rc = airQuality.main([])

    assert rc == 0
    assert display_recorder[0]["stale"] is False
    assert (state_dir / "airquality" / "heartbeat").is_file()


def test_stale_sample_summary_logs_cache_fallback_branch(
    state_dir, seed_cache, conf, display_recorder, monkeypatch, caplog
):
    """A stale-sample skip logs the same summary path as an ordinary fetch
    failure, so monitoring doesn't need a third code path to watch."""
    seed_cache(_purple_payload(pm25=15.0))
    stale_epoch = time.time() - airQuality.FRESHNESS_THRESHOLD_SEC - 1
    _fetch_returns(monkeypatch, pm25=50.0, last_seen_epoch=stale_epoch)

    with caplog.at_level(logging.INFO, logger="airquality"):
        rc = airQuality.main([])

    assert rc == 1
    summary_msgs = _summary_lines(caplog)
    assert len(summary_msgs) == 1
    assert "path=cache_fallback" in summary_msgs[0]
    assert "pm25=15.0" in summary_msgs[0]

"""Integration tests for the `main()` orchestration paths.

These cover the branches the unit tests don't reach: live success, weather
fallback wiring, cache-fallback rendering, the "bad config exits before the
try" CLAUDE.md invariant, and the trend / "AQI Rising!" rules. The display
function is replaced with a recorder fixture — the e-ink draw is exercised in
its own dedicated tests (or on hardware), not here.
"""
import json

import pytest

import airQuality


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(airQuality, "CACHE_PATH", str(state / "airquality" / "last_reading.json"))
    monkeypatch.setattr(airQuality, "HEARTBEAT_PATH", str(state / "airquality" / "heartbeat"))
    return state


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
        })

    monkeypatch.setattr(airQuality, "display_air_quality", _record)
    return calls


def _purple_payload(pm25=20.0, pm10=22.0, temp=70, humidity=40):
    return {
        "PM2.5": pm25,
        "PM10": pm10,
        "Temp": temp,
        "Humidity": humidity,
        "Time": "12:00 PM",
    }


def test_live_success_writes_cache_and_heartbeat(state_dir, conf, display_recorder, monkeypatch):
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", lambda *a, **kw: _purple_payload())

    rc = airQuality.main()

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


def test_purpleair_fails_with_cache_renders_stale(state_dir, conf, display_recorder, monkeypatch):
    cache_dir = state_dir / "airquality"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_reading.json").write_text(json.dumps(_purple_payload(pm25=15.0)))

    def _boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(airQuality, "fetch_purpleair_data", _boom)

    rc = airQuality.main()

    assert rc == 1
    assert len(display_recorder) == 1
    assert display_recorder[0]["stale"] is True
    assert display_recorder[0]["alert"] is False  # banner suppressed in stale renders
    # Heartbeat should NOT be touched on cache fallback.
    assert not (state_dir / "airquality" / "heartbeat").exists()


def test_purpleair_fails_no_cache_returns_one(state_dir, conf, display_recorder, monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(airQuality, "fetch_purpleair_data", _boom)

    rc = airQuality.main()

    assert rc == 1
    assert display_recorder == []  # nothing drawn at all
    assert not (state_dir / "airquality" / "heartbeat").exists()


def test_weather_fallback_fills_missing_temp_humidity(
    state_dir, conf, display_recorder, monkeypatch
):
    monkeypatch.setattr(
        airQuality, "fetch_purpleair_data",
        lambda *a, **kw: _purple_payload(temp="N/A", humidity="N/A"),
    )
    monkeypatch.setattr(
        airQuality, "fetch_local_weather",
        lambda lat, lon, **kw: {"Temp": 65, "Humidity": 55},
    )

    rc = airQuality.main()

    assert rc == 0
    assert display_recorder[0]["data"]["Temp"] == 65
    assert display_recorder[0]["data"]["Humidity"] == 55


def test_weather_fallback_failure_logs_but_does_not_raise(
    state_dir, conf, display_recorder, monkeypatch, caplog
):
    monkeypatch.setattr(
        airQuality, "fetch_purpleair_data",
        lambda *a, **kw: _purple_payload(temp="N/A", humidity="N/A"),
    )

    def _weather_boom(*a, **kw):
        raise RuntimeError("openmeteo down")

    monkeypatch.setattr(airQuality, "fetch_local_weather", _weather_boom)

    rc = airQuality.main()

    assert rc == 0
    assert display_recorder[0]["data"]["Temp"] == "N/A"
    assert display_recorder[0]["data"]["Humidity"] == "N/A"


def test_rising_banner_fires_at_or_above_threshold(state_dir, conf, display_recorder, monkeypatch):
    cache_dir = state_dir / "airquality"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_reading.json").write_text(json.dumps(_purple_payload(pm25=10.0)))

    # Delta = 5.0 == TREND_THRESHOLD → banner fires.
    monkeypatch.setattr(
        airQuality, "fetch_purpleair_data",
        lambda *a, **kw: _purple_payload(pm25=15.0),
    )

    airQuality.main()

    assert display_recorder[0]["alert"] is True
    assert display_recorder[0]["trend_symbol"] == "+"


def test_rising_banner_silent_below_threshold(state_dir, conf, display_recorder, monkeypatch):
    cache_dir = state_dir / "airquality"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_reading.json").write_text(json.dumps(_purple_payload(pm25=10.0)))

    # Delta = 4.99 < threshold → trend marker still '+', but no banner.
    monkeypatch.setattr(
        airQuality, "fetch_purpleair_data",
        lambda *a, **kw: _purple_payload(pm25=14.99),
    )

    airQuality.main()

    assert display_recorder[0]["alert"] is False
    assert display_recorder[0]["trend_symbol"] == "+"


def test_trend_symbol_minus_when_pm25_holds_or_drops(
    state_dir, conf, display_recorder, monkeypatch
):
    cache_dir = state_dir / "airquality"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_reading.json").write_text(json.dumps(_purple_payload(pm25=20.0)))

    # Same value → '-' per CLAUDE.md trend rule.
    monkeypatch.setattr(
        airQuality, "fetch_purpleair_data",
        lambda *a, **kw: _purple_payload(pm25=20.0),
    )

    airQuality.main()

    assert display_recorder[0]["trend_symbol"] == "-"
    assert display_recorder[0]["alert"] is False


def test_bad_config_exits_before_try_block(tmp_path, display_recorder, monkeypatch):
    # CLAUDE.md invariant: a bad config raises SystemExit *outside* the cache-fallback try.
    # Verifies that load_config's SystemExit isn't caught by the broad except in main().
    bad = tmp_path / "airquality.conf"
    bad.write_text("[purpleair]\napi_key = YOUR_PURPLEAIR_API_KEY\nsensor_id = 1\n")
    monkeypatch.setattr(airQuality, "CONF_PATH", str(bad))

    with pytest.raises(SystemExit):
        airQuality.main()
    assert display_recorder == []  # never even reached the try


def test_cache_write_failure_does_not_trigger_stale_render(
    state_dir, conf, display_recorder, monkeypatch
):
    """Regression: a persistence error after a successful display must not flip
    the run into the cache-fallback branch — the user already saw fresh data."""
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", lambda *a, **kw: _purple_payload())

    def _boom(_data):
        raise OSError("disk full")

    monkeypatch.setattr(airQuality, "write_cache", _boom)

    rc = airQuality.main()

    assert rc == 0  # not 1 — fresh display still happened
    assert len(display_recorder) == 1
    assert display_recorder[0]["stale"] is False
    # And no second [CACHED] render was issued.
    assert all(call["stale"] is False for call in display_recorder)


def test_heartbeat_failure_does_not_trigger_stale_render(
    state_dir, conf, display_recorder, monkeypatch
):
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", lambda *a, **kw: _purple_payload())

    def _boom():
        raise OSError("read-only fs")

    monkeypatch.setattr(airQuality, "write_heartbeat", _boom)

    rc = airQuality.main()

    assert rc == 0
    assert len(display_recorder) == 1
    assert display_recorder[0]["stale"] is False


def test_heartbeat_content_is_iso8601_utc(state_dir, conf, display_recorder, monkeypatch):
    """Operators alert on heartbeat staleness; the file must be parseable as UTC."""
    from datetime import datetime, timezone

    monkeypatch.setattr(airQuality, "fetch_purpleair_data", lambda *a, **kw: _purple_payload())

    rc = airQuality.main()

    assert rc == 0
    raw = (state_dir / "airquality" / "heartbeat").read_text()
    parsed = datetime.fromisoformat(raw)
    assert parsed.tzinfo is not None
    # Within a few seconds of "now" — sanity check that we're not writing a
    # frozen string.
    delta = abs((datetime.now(timezone.utc) - parsed).total_seconds())
    assert delta < 60


def test_missing_temp_humidity_with_no_weather_section_logs_and_continues(
    tmp_path, state_dir, display_recorder, monkeypatch, caplog
):
    """Branch: PurpleAir drops Temp/Humidity but conf has no [weather] section.
    We log and render N/A — we do NOT pull stale temp/humidity from cache."""
    conf_path = tmp_path / "airquality.conf"
    conf_path.write_text("[purpleair]\napi_key = real-key\nsensor_id = 12345\n")
    monkeypatch.setattr(airQuality, "CONF_PATH", str(conf_path))
    monkeypatch.setattr(
        airQuality, "fetch_purpleair_data",
        lambda *a, **kw: _purple_payload(temp="N/A", humidity="N/A"),
    )

    with caplog.at_level("INFO"):
        rc = airQuality.main()

    assert rc == 0
    assert display_recorder[0]["data"]["Temp"] == "N/A"
    assert display_recorder[0]["data"]["Humidity"] == "N/A"
    assert any("no [weather] coords configured" in m for m in caplog.messages)


def test_live_path_with_unparseable_cached_pm25_treats_trend_as_first_run(
    state_dir, conf, display_recorder, monkeypatch
):
    """Branch: cache exists but PM2.5 is junk. last_pm25 falls through to None
    and the trend marker behaves like a fresh start ('-', no banner)."""
    cache_dir = state_dir / "airquality"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_reading.json").write_text(
        json.dumps({"PM2.5": "junk", "PM10": 0, "Temp": 0, "Humidity": 0, "Time": "x"})
    )

    monkeypatch.setattr(
        airQuality, "fetch_purpleair_data", lambda *a, **kw: _purple_payload(pm25=20.0),
    )

    rc = airQuality.main()

    assert rc == 0
    assert display_recorder[0]["trend_symbol"] == "-"
    assert display_recorder[0]["alert"] is False


def test_cache_fallback_with_unparseable_pm25_returns_one_without_drawing(
    state_dir, conf, display_recorder, monkeypatch
):
    """Branch: live fetch fails; cache is present but PM2.5 isn't a number.
    We can't render a useful [CACHED] panel, so exit 1 and don't draw garbage."""
    cache_dir = state_dir / "airquality"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_reading.json").write_text(
        json.dumps({"PM2.5": "junk", "PM10": 0, "Temp": 0, "Humidity": 0, "Time": "x"})
    )

    def _boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(airQuality, "fetch_purpleair_data", _boom)

    rc = airQuality.main()

    assert rc == 1
    assert display_recorder == []
    assert not (state_dir / "airquality" / "heartbeat").exists()


def test_cache_fallback_swallows_display_exception(
    state_dir, conf, display_recorder, monkeypatch, caplog
):
    """Branch: cached data is valid but the panel itself errors during the
    [CACHED] render. We log the exception, don't crash the process, and still
    return 1 (the live fetch failed — that's the signal monitoring cares about)."""
    cache_dir = state_dir / "airquality"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_reading.json").write_text(json.dumps(_purple_payload(pm25=15.0)))

    def _fetch_boom(*a, **kw):
        raise RuntimeError("network down")

    def _display_boom(*a, **kw):
        raise RuntimeError("panel exploded")

    monkeypatch.setattr(airQuality, "fetch_purpleair_data", _fetch_boom)
    monkeypatch.setattr(airQuality, "display_air_quality", _display_boom)

    with caplog.at_level("ERROR"):
        rc = airQuality.main()

    assert rc == 1
    assert any("Failed to display cached data" in m for m in caplog.messages)

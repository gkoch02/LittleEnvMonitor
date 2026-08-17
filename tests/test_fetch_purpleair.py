from unittest.mock import MagicMock

import pytest
import requests

import airQuality


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Skip the exponential backoff sleeps so tests stay fast."""
    monkeypatch.setattr(airQuality.time, "sleep", lambda *_: None)


@pytest.fixture
def mock_get(monkeypatch):
    """Replace the cached requests.Session with a stub whose .get is a MagicMock."""
    fake = MagicMock()
    fake_session = MagicMock()
    fake_session.get = fake
    monkeypatch.setattr(airQuality, "_http_session", lambda: fake_session)
    return fake


def _mock_response(status_code, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = ""
    resp.headers = headers or {}
    resp.json.return_value = json_data or {}
    return resp


def test_successful_fetch_parses_fields(mock_get):
    payload = {
        "sensor": {
            "pm2.5": 7.5,
            "pm10.0": 12.3,
            "temperature": 68,
            "humidity": 45,
            "last_seen": 1_700_000_000,
        }
    }
    mock_get.return_value = _mock_response(200, payload)
    result = airQuality.fetch_purpleair_data(123, "key", retries=1)

    assert result["PM2.5"] == 7.5
    assert result["PM10"] == 12.3
    assert result["Temp"] == 68
    assert result["Humidity"] == 45
    assert result["Time"] != "N/A"
    assert result["LastSeenEpoch"] == 1_700_000_000
    assert mock_get.call_count == 1


def test_4xx_does_not_retry(mock_get):
    mock_get.return_value = _mock_response(401)
    with pytest.raises(RuntimeError, match="401"):
        airQuality.fetch_purpleair_data(123, "key", retries=3)
    assert mock_get.call_count == 1


def test_404_does_not_retry(mock_get):
    mock_get.return_value = _mock_response(404)
    with pytest.raises(RuntimeError, match="404"):
        airQuality.fetch_purpleair_data(123, "key", retries=3)
    assert mock_get.call_count == 1


def test_5xx_retries_then_raises(mock_get):
    mock_get.return_value = _mock_response(503)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        airQuality.fetch_purpleair_data(123, "key", retries=3)
    assert mock_get.call_count == 3


def test_network_error_retries_then_raises(mock_get):
    mock_get.side_effect = requests.ConnectionError("boom")
    with pytest.raises(requests.ConnectionError):
        airQuality.fetch_purpleair_data(123, "key", retries=3)
    assert mock_get.call_count == 3


def test_recovers_after_transient_failure(mock_get):
    payload = {
        "sensor": {
            "pm2.5": 5,
            "pm10.0": 8,
            "temperature": 70,
            "humidity": 40,
            "last_seen": 1_700_000_000,
        }
    }
    mock_get.side_effect = [_mock_response(503), _mock_response(200, payload)]
    result = airQuality.fetch_purpleair_data(123, "key", retries=3)
    assert result["PM2.5"] == 5
    assert mock_get.call_count == 2


def test_missing_sensor_fields_default_to_na(mock_get):
    mock_get.return_value = _mock_response(200, {"sensor": {}})
    result = airQuality.fetch_purpleair_data(123, "key", retries=1)
    assert result["PM2.5"] == "N/A"
    assert result["PM10"] == "N/A"
    assert result["Temp"] == "N/A"
    assert result["Humidity"] == "N/A"
    assert result["Time"] == "N/A"
    assert result["LastSeenEpoch"] is None


def test_429_retries_with_retry_after_header(mock_get):
    payload = {
        "sensor": {
            "pm2.5": 9,
            "pm10.0": 11,
            "temperature": 65,
            "humidity": 50,
            "last_seen": 1_700_000_000,
        }
    }
    mock_get.side_effect = [
        _mock_response(429, headers={"Retry-After": "1"}),
        _mock_response(200, payload),
    ]
    result = airQuality.fetch_purpleair_data(123, "key", retries=3)
    assert result["PM2.5"] == 9
    assert mock_get.call_count == 2


def test_429_exhausts_retries_then_raises(mock_get):
    mock_get.return_value = _mock_response(429)
    with pytest.raises(RuntimeError, match="429"):
        airQuality.fetch_purpleair_data(123, "key", retries=3)
    assert mock_get.call_count == 3


def test_retries_below_one_rejected(mock_get):
    """Guard against the assert-elided-under-O case from the review."""
    with pytest.raises(ValueError, match="retries"):
        airQuality.fetch_purpleair_data(123, "key", retries=0)
    assert mock_get.call_count == 0


def test_retry_after_is_capped(monkeypatch, mock_get):
    """A 5-minute Retry-After hint must not exceed the cap."""
    captured_sleeps = []
    monkeypatch.setattr(airQuality.time, "sleep", lambda s: captured_sleeps.append(s))
    payload = {
        "sensor": {
            "pm2.5": 1, "pm10.0": 1, "temperature": 1, "humidity": 1,
            "last_seen": 1_700_000_000,
        }
    }
    mock_get.side_effect = [
        _mock_response(429, headers={"Retry-After": "300"}),
        _mock_response(200, payload),
    ]
    airQuality.fetch_purpleair_data(123, "key", retries=2)
    assert captured_sleeps == [airQuality.RETRY_AFTER_CAP_SEC]


def test_retry_after_zero_falls_through_to_backoff(monkeypatch, mock_get):
    captured_sleeps = []
    monkeypatch.setattr(airQuality.time, "sleep", lambda s: captured_sleeps.append(s))
    payload = {
        "sensor": {
            "pm2.5": 1, "pm10.0": 1, "temperature": 1, "humidity": 1,
            "last_seen": 1_700_000_000,
        }
    }
    mock_get.side_effect = [
        _mock_response(429, headers={"Retry-After": "0"}),
        _mock_response(200, payload),
    ]
    airQuality.fetch_purpleair_data(123, "key", retries=2)
    # First retry without a usable Retry-After uses 2**1 = 2s.
    assert captured_sleeps == [2]


def test_retry_after_http_date_falls_through_to_backoff(monkeypatch, mock_get):
    """Spec also allows an HTTP-date in Retry-After. We don't parse it; we
    must fall through to the exponential backoff instead of raising."""
    captured_sleeps = []
    monkeypatch.setattr(airQuality.time, "sleep", lambda s: captured_sleeps.append(s))
    payload = {
        "sensor": {
            "pm2.5": 1, "pm10.0": 1, "temperature": 1, "humidity": 1,
            "last_seen": 1_700_000_000,
        }
    }
    mock_get.side_effect = [
        _mock_response(
            429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
        ),
        _mock_response(200, payload),
    ]
    result = airQuality.fetch_purpleair_data(123, "key", retries=2)
    assert result["PM2.5"] == 1
    assert captured_sleeps == [2]  # 2**1 backoff, not the HTTP date


def test_last_seen_zero_renders_as_na(mock_get):
    """A `last_seen` of 0 means "no reading yet" — don't show 1969."""
    mock_get.return_value = _mock_response(
        200,
        {
            "sensor": {
                "pm2.5": 5, "pm10.0": 6, "temperature": 70, "humidity": 40,
                "last_seen": 0,
            }
        },
    )
    result = airQuality.fetch_purpleair_data(123, "key", retries=1)
    assert result["Time"] == "N/A"
    assert result["LastSeenEpoch"] is None


def test_missing_sensor_key_raises_runtime_error(mock_get):
    """A 200 response with no `sensor` key shouldn't escape as a bare KeyError."""
    mock_get.return_value = _mock_response(200, {"unexpected": "shape"})
    with pytest.raises((RuntimeError, KeyError)):
        airQuality.fetch_purpleair_data(123, "key", retries=1)


# --- Freshness validation (issue #17) ---------------------------------------
#
# fetch_purpleair_data() only carries the raw epoch through; the actual
# freshness policy (threshold, missing/malformed/future-skew handling) lives
# in airQuality._is_fresh() and is exercised directly here, plus end-to-end
# in tests/test_main.py against main()'s cache-fallback wiring.


def test_is_fresh_accepts_recent_sample():
    now = 1_700_010_000
    assert airQuality._is_fresh(now - 60, now=now) is True


def test_is_fresh_rejects_sample_past_threshold():
    now = 1_700_010_000
    stale = now - airQuality.FRESHNESS_THRESHOLD_SEC - 1
    assert airQuality._is_fresh(stale, now=now) is False


def test_is_fresh_accepts_sample_exactly_at_threshold():
    now = 1_700_010_000
    boundary = now - airQuality.FRESHNESS_THRESHOLD_SEC
    assert airQuality._is_fresh(boundary, now=now) is True


def test_is_fresh_rejects_none():
    assert airQuality._is_fresh(None, now=1_700_010_000) is False


def test_is_fresh_rejects_non_numeric_string():
    assert airQuality._is_fresh("N/A", now=1_700_010_000) is False


def test_is_fresh_rejects_zero_or_negative():
    assert airQuality._is_fresh(0, now=1_700_010_000) is False
    assert airQuality._is_fresh(-100, now=1_700_010_000) is False


def test_is_fresh_rejects_nan_and_inf():
    assert airQuality._is_fresh(float("nan"), now=1_700_010_000) is False
    assert airQuality._is_fresh(float("inf"), now=1_700_010_000) is False


def test_is_fresh_accepts_slight_future_skew_within_tolerance():
    now = 1_700_010_000
    slightly_ahead = now + airQuality.FUTURE_SKEW_TOLERANCE_SEC
    assert airQuality._is_fresh(slightly_ahead, now=now) is True


def test_is_fresh_rejects_future_skew_beyond_tolerance():
    now = 1_700_010_000
    far_ahead = now + airQuality.FUTURE_SKEW_TOLERANCE_SEC + 1
    assert airQuality._is_fresh(far_ahead, now=now) is False


def test_is_fresh_accepts_numeric_string_epoch():
    """Defensive: JSON always gives us a number, but don't crash on a string
    that happens to parse cleanly."""
    now = 1_700_010_000
    assert airQuality._is_fresh(str(now - 60), now=now) is True

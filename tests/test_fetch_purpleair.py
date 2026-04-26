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

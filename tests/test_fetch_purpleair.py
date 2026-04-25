from unittest.mock import MagicMock, patch

import pytest
import requests

import airQuality


def _mock_response(status_code, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = ""
    resp.json.return_value = json_data or {}
    return resp


def test_successful_fetch_parses_fields():
    payload = {
        "sensor": {
            "pm2.5": 7.5,
            "pm10.0": 12.3,
            "temperature": 68,
            "humidity": 45,
            "last_seen": 1_700_000_000,
        }
    }
    with patch(
        "airQuality.requests.get",
        return_value=_mock_response(200, payload),
    ) as mock_get:
        result = airQuality.fetch_purpleair_data(123, "key", retries=1, delay=0)

    assert result["PM2.5"] == 7.5
    assert result["PM10"] == 12.3
    assert result["Temp"] == 68
    assert result["Humidity"] == 45
    assert result["Time"] != "N/A"
    assert mock_get.call_count == 1


def test_4xx_does_not_retry():
    with patch(
        "airQuality.requests.get",
        return_value=_mock_response(401),
    ) as mock_get:
        with pytest.raises(RuntimeError, match="401"):
            airQuality.fetch_purpleair_data(123, "key", retries=3, delay=0)
    assert mock_get.call_count == 1


def test_404_does_not_retry():
    with patch(
        "airQuality.requests.get",
        return_value=_mock_response(404),
    ) as mock_get:
        with pytest.raises(RuntimeError, match="404"):
            airQuality.fetch_purpleair_data(123, "key", retries=3, delay=0)
    assert mock_get.call_count == 1


def test_5xx_retries_then_raises():
    with patch(
        "airQuality.requests.get",
        return_value=_mock_response(503),
    ) as mock_get:
        with pytest.raises(RuntimeError, match="HTTP 503"):
            airQuality.fetch_purpleair_data(123, "key", retries=3, delay=0)
    assert mock_get.call_count == 3


def test_network_error_retries_then_raises():
    with patch(
        "airQuality.requests.get",
        side_effect=requests.ConnectionError("boom"),
    ) as mock_get:
        with pytest.raises(requests.ConnectionError):
            airQuality.fetch_purpleair_data(123, "key", retries=3, delay=0)
    assert mock_get.call_count == 3


def test_recovers_after_transient_failure():
    payload = {
        "sensor": {
            "pm2.5": 5,
            "pm10.0": 8,
            "temperature": 70,
            "humidity": 40,
            "last_seen": 1_700_000_000,
        }
    }
    responses = [_mock_response(503), _mock_response(200, payload)]
    with patch(
        "airQuality.requests.get",
        side_effect=responses,
    ) as mock_get:
        result = airQuality.fetch_purpleair_data(123, "key", retries=3, delay=0)
    assert result["PM2.5"] == 5
    assert mock_get.call_count == 2


def test_missing_sensor_fields_default_to_na():
    payload = {"sensor": {}}
    with patch(
        "airQuality.requests.get",
        return_value=_mock_response(200, payload),
    ):
        result = airQuality.fetch_purpleair_data(123, "key", retries=1, delay=0)
    assert result["PM2.5"] == "N/A"
    assert result["PM10"] == "N/A"
    assert result["Temp"] == "N/A"
    assert result["Humidity"] == "N/A"
    assert result["Time"] == "N/A"

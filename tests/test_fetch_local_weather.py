from unittest.mock import MagicMock

import pytest
import requests

import airQuality


@pytest.fixture
def mock_get(monkeypatch):
    """Replace the cached requests.Session with a stub whose .get is a MagicMock."""
    fake = MagicMock()
    fake_session = MagicMock()
    fake_session.get = fake
    monkeypatch.setattr(airQuality, "_http_session", lambda: fake_session)
    return fake


def _mock_response(status_code, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_parses_current_block(mock_get):
    payload = {"current": {"temperature_2m": 72.4, "relative_humidity_2m": 55}}
    mock_get.return_value = _mock_response(200, payload)
    result = airQuality.fetch_local_weather(37.0, -121.0)
    assert result == {"Temp": 72, "Humidity": 55}


def test_missing_fields_default_to_na(mock_get):
    mock_get.return_value = _mock_response(200, {"current": {}})
    result = airQuality.fetch_local_weather(37.0, -121.0)
    assert result == {"Temp": "N/A", "Humidity": "N/A"}


def test_missing_current_block_defaults_to_na(mock_get):
    mock_get.return_value = _mock_response(200, {})
    result = airQuality.fetch_local_weather(37.0, -121.0)
    assert result == {"Temp": "N/A", "Humidity": "N/A"}


def test_http_error_propagates(mock_get):
    mock_get.return_value = _mock_response(500)
    with pytest.raises(requests.HTTPError):
        airQuality.fetch_local_weather(37.0, -121.0)


def test_non_numeric_temperature_returns_na(mock_get):
    """Guard: temperature_2m is a string — isinstance check must reject it and return 'N/A'."""
    payload = {"current": {"temperature_2m": "72", "relative_humidity_2m": 55}}
    mock_get.return_value = _mock_response(200, payload)
    result = airQuality.fetch_local_weather(37.0, -121.0)
    assert result["Temp"] == "N/A"
    assert result["Humidity"] == 55


def test_non_numeric_humidity_returns_na(mock_get):
    """Guard: relative_humidity_2m is a string — isinstance rejects it and returns 'N/A'."""
    payload = {"current": {"temperature_2m": 72.4, "relative_humidity_2m": "55"}}
    mock_get.return_value = _mock_response(200, payload)
    result = airQuality.fetch_local_weather(37.0, -121.0)
    assert result["Temp"] == 72
    assert result["Humidity"] == "N/A"


def test_request_url_includes_coords_and_units(mock_get):
    payload = {"current": {"temperature_2m": 70, "relative_humidity_2m": 50}}
    mock_get.return_value = _mock_response(200, payload)
    airQuality.fetch_local_weather(37.5, -121.9)
    url = mock_get.call_args[0][0]
    assert "latitude=37.5" in url
    assert "longitude=-121.9" in url
    assert "temperature_unit=fahrenheit" in url
    assert "relative_humidity_2m" in url

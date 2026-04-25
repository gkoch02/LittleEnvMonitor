from unittest.mock import MagicMock, patch

import pytest
import requests

import airQuality


def _mock_response(status_code, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_parses_current_block():
    payload = {"current": {"temperature_2m": 72.4, "relative_humidity_2m": 55}}
    with patch("airQuality.requests.get", return_value=_mock_response(200, payload)):
        result = airQuality.fetch_local_weather(37.0, -121.0)
    assert result == {"Temp": 72, "Humidity": 55}


def test_missing_fields_default_to_na():
    with patch(
        "airQuality.requests.get",
        return_value=_mock_response(200, {"current": {}}),
    ):
        result = airQuality.fetch_local_weather(37.0, -121.0)
    assert result == {"Temp": "N/A", "Humidity": "N/A"}


def test_missing_current_block_defaults_to_na():
    with patch(
        "airQuality.requests.get",
        return_value=_mock_response(200, {}),
    ):
        result = airQuality.fetch_local_weather(37.0, -121.0)
    assert result == {"Temp": "N/A", "Humidity": "N/A"}


def test_http_error_propagates():
    with patch("airQuality.requests.get", return_value=_mock_response(500)):
        with pytest.raises(requests.HTTPError):
            airQuality.fetch_local_weather(37.0, -121.0)


def test_request_url_includes_coords_and_units():
    payload = {"current": {"temperature_2m": 70, "relative_humidity_2m": 50}}
    with patch(
        "airQuality.requests.get",
        return_value=_mock_response(200, payload),
    ) as mock_get:
        airQuality.fetch_local_weather(37.5, -121.9)
    url = mock_get.call_args[0][0]
    assert "latitude=37.5" in url
    assert "longitude=-121.9" in url
    assert "temperature_unit=fahrenheit" in url
    assert "relative_humidity_2m" in url

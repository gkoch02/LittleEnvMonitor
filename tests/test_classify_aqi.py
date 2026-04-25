import pytest

from airQuality import classify_aqi


@pytest.mark.parametrize(
    "pm25,expected",
    [
        (0, ("Good", "black")),
        (12, ("Good", "black")),
        (12.01, ("Moderate", "black")),
        (35.4, ("Moderate", "black")),
        (35.41, ("Unhealthy for Sensitive Groups", "red")),
        (55.4, ("Unhealthy for Sensitive Groups", "red")),
        (55.41, ("Unhealthy", "red")),
        (150.4, ("Unhealthy", "red")),
        (150.41, ("Very Unhealthy", "red")),
        (250.4, ("Very Unhealthy", "red")),
        (250.41, ("Hazardous", "red")),
        (500, ("Hazardous", "red")),
    ],
)
def test_classify_aqi_band_boundaries(pm25, expected):
    assert classify_aqi(pm25) == expected

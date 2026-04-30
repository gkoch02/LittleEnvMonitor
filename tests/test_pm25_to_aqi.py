"""Tests for the EPA PM2.5 → AQI piecewise-linear conversion.

The breakpoints come from 40 CFR Part 58 App. G (2012) and must agree with
`classify_aqi`'s bands — a PM2.5 value that lands in "Moderate" must produce
an AQI in [51, 100], etc.
"""
import pytest

from airQuality import classify_aqi, pm25_to_aqi


@pytest.mark.parametrize(
    "pm25,expected",
    [
        (0.0, 0),
        (12.0, 50),
        (12.1, 51),
        (35.4, 100),
        (35.5, 101),
        (55.4, 150),
        (55.5, 151),
        (150.4, 200),
        (150.5, 201),
        (250.4, 300),
        (250.5, 301),
        (500.4, 500),
    ],
)
def test_breakpoint_endpoints_map_exactly(pm25, expected):
    assert pm25_to_aqi(pm25) == expected


def test_above_top_breakpoint_clamps_to_500():
    assert pm25_to_aqi(750.0) == 500


@pytest.mark.parametrize("bad", [-0.1, -1, "N/A", None, "junk"])
def test_invalid_input_returns_none(bad):
    assert pm25_to_aqi(bad) is None


def test_string_numeric_input_is_accepted():
    # PurpleAir occasionally returns numbers as strings; round-trip via float.
    assert pm25_to_aqi("12.0") == 50


@pytest.mark.parametrize("pm25", [0.0, 6.0, 12.0, 20.0, 35.4, 45.0, 60.0, 200.0, 400.0])
def test_aqi_band_matches_classify_aqi_category(pm25):
    """The numeric AQI must always agree with the category label."""
    aqi = pm25_to_aqi(pm25)
    category, _ = classify_aqi(pm25)
    bands = {
        "Good": (0, 50),
        "Moderate": (51, 100),
        "Unhealthy for Sensitive Groups": (101, 150),
        "Unhealthy": (151, 200),
        "Very Unhealthy": (201, 300),
        "Hazardous": (301, 500),
    }
    lo, hi = bands[category]
    assert lo <= aqi <= hi

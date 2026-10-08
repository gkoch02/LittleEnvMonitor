"""Tests for the EPA PM2.5 → AQI piecewise-linear conversion.

The breakpoints come from 40 CFR Part 58 App. G (2012). `classify_aqi` reads
the same table, so the number and the category label can't disagree.
"""
import pytest

from airQuality import pm25_to_aqi


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


@pytest.mark.parametrize(
    "bad",
    [
        -0.1,
        -1,
        "N/A",
        None,
        "junk",
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_invalid_input_returns_none(bad):
    assert pm25_to_aqi(bad) is None


def test_truncates_per_epa_spec_not_rounds():
    """EPA App. G says truncate, not round. 12.05 must map to 12.0 → AQI 50,
    not 12.1 → AQI 51 (which is what `round(12.05, 1)` would give)."""
    assert pm25_to_aqi(12.05) == 50
    assert pm25_to_aqi(35.45) == 100


def test_string_numeric_input_is_accepted():
    # PurpleAir occasionally returns numbers as strings; round-trip via float.
    assert pm25_to_aqi("12.0") == 50

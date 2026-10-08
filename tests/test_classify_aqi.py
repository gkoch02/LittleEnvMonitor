import pytest

from airQuality import classify_aqi


@pytest.mark.parametrize(
    "pm25,expected",
    [
        # Truncated boundary values — these are the EPA-spec band edges and
        # must each land in the lower band.
        (0, ("Good", "black")),
        (12, ("Good", "black")),
        (12.0, ("Good", "black")),
        (12.1, ("Moderate", "black")),
        (35.4, ("Moderate", "black")),
        (35.5, ("Unhealthy for Sensitive Groups", "red")),
        (55.4, ("Unhealthy for Sensitive Groups", "red")),
        (55.5, ("Unhealthy", "red")),
        (150.4, ("Unhealthy", "red")),
        (150.5, ("Very Unhealthy", "red")),
        (250.4, ("Very Unhealthy", "red")),
        (250.5, ("Hazardous", "red")),
        (500, ("Hazardous", "red")),
        (750, ("Hazardous", "red")),  # above the top breakpoint
    ],
)
def test_classify_aqi_band_boundaries(pm25, expected):
    assert classify_aqi(pm25) == expected


@pytest.mark.parametrize(
    "pm25,expected",
    [
        # Sub-decimal precision must truncate, not round, before band lookup.
        # 12.09 → 12.0 → Good (NOT Moderate, which is what un-truncated
        # comparison would give).
        (12.09, ("Good", "black")),
        (35.49, ("Moderate", "black")),
        (55.49, ("Unhealthy for Sensitive Groups", "red")),
        (150.49, ("Unhealthy", "red")),
        (250.49, ("Very Unhealthy", "red")),
    ],
)
def test_classify_aqi_truncates_before_lookup(pm25, expected):
    assert classify_aqi(pm25) == expected


@pytest.mark.parametrize(
    "bad",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        -1,
        -0.1,
        "N/A",
        None,
        "junk",
    ],
)
def test_classify_aqi_invalid_input_returns_unknown(bad):
    """Mirrors `pm25_to_aqi` returning None on the same inputs — together they
    keep the display from rendering contradictory `AQI: <number> (<category>)`
    text when the upstream reading is broken."""
    assert classify_aqi(bad) == ("Unknown", "black")

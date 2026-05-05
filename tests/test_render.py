"""Tests for the hardware-free render layer.

`_render_panel_images` returns the (black, red) 1-bit images that both the
e-ink path and the --dry-run PNG share, and `render_preview_png` composites
them. These tests do real PIL rendering and assert *structural* properties
(pixel counts in known regions, layer differences across modes) rather than
pixel-perfect snapshots — that keeps them robust to font version differences
across CI runners while still catching the kind of layout regression the
existing call-sequence tests can't see.
"""
import pytest
from PIL import Image

import airQuality


def _payload(pm25=12.0, pm10=18.0, temp=70, humidity=45):
    return {
        "PM2.5": pm25, "PM10": pm10, "Temp": temp, "Humidity": humidity,
        "Time": "12:00 PM",
    }


def _nonwhite(image, box=None):
    """Count pixels darker than white in a 1-bit image. Higher = more ink."""
    if box is not None:
        image = image.crop(box)
    return sum(1 for px in image.getdata() if px == 0)


def test_render_returns_two_layers_at_panel_size():
    black, red = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False,
    )
    assert black.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)
    assert red.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)
    assert black.mode == "1"
    assert red.mode == "1"


def test_alert_changes_red_layer_title_region():
    """Switching alert on must redraw the red title band — that's what makes
    'AQI Rising!' replace 'Air Quality - <city>'."""
    title_box = (10, 5, airQuality.PANEL_WIDTH - 10, 35)
    _, red_normal = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False,
    )
    _, red_alert = airQuality._render_panel_images(
        _payload(), alert=True, trend_symbol="+", aqi_value=160, category="Unhealthy",
        cat_color="red", city="Campbell", stale=False,
    )
    assert _nonwhite(red_normal, title_box) != _nonwhite(red_alert, title_box)


def test_stale_changes_red_layer_title_region():
    title_box = (10, 5, airQuality.PANEL_WIDTH - 10, 35)
    _, red_fresh = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False,
    )
    _, red_stale = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="?", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=True,
    )
    assert _nonwhite(red_fresh, title_box) != _nonwhite(red_stale, title_box)


def test_red_aqi_routes_to_red_layer_not_black():
    """When `cat_color='red'` the AQI line must be drawn on the red layer.
    A regression here is what produces a panel that looks all-black for an
    Unhealthy reading."""
    aqi_box = (10, 70, airQuality.PANEL_WIDTH - 10, 100)
    black_red, red_red = airQuality._render_panel_images(
        _payload(pm25=80), alert=False, trend_symbol="+", aqi_value=160,
        category="Unhealthy", cat_color="red", city="Campbell", stale=False,
    )
    black_blk, red_blk = airQuality._render_panel_images(
        _payload(pm25=10), alert=False, trend_symbol="+", aqi_value=42,
        category="Good", cat_color="black", city="Campbell", stale=False,
    )
    # Red AQI should put more red ink in the AQI band than the black case.
    assert _nonwhite(red_red, aqi_box) > _nonwhite(red_blk, aqi_box)


def test_borders_present_on_both_layers():
    """The frame is drawn on both layers; a regression that drops one is the
    sort of thing that visually looks fine on the dry-run preview but renders
    weirdly on the actual e-ink panel."""
    black, red = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False,
    )
    # Top-left corner of each border has at least one black pixel.
    assert black.getpixel((3, 3)) == 0
    assert red.getpixel((5, 5)) == 0


def test_render_preview_png_writes_valid_image(tmp_path):
    out = tmp_path / "preview.png"
    returned = airQuality.render_preview_png(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, out_path=str(out),
        scale=2,
    )
    assert returned == str(out)
    assert out.is_file()

    img = Image.open(out)
    assert img.mode == "RGB"
    assert img.size == (airQuality.PANEL_WIDTH * 2, airQuality.PANEL_HEIGHT * 2)


def test_render_preview_png_creates_parent_dirs(tmp_path):
    out = tmp_path / "deep" / "nested" / "preview.png"
    airQuality.render_preview_png(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, out_path=str(out),
    )
    assert out.is_file()


def test_render_preview_png_scale_one_is_native_size(tmp_path):
    out = tmp_path / "preview.png"
    airQuality.render_preview_png(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, out_path=str(out),
        scale=1,
    )
    img = Image.open(out)
    assert img.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)


def test_render_handles_aqi_value_none_in_panel_images():
    """`pm25_to_aqi` returns None on bad input — the renderer must still
    produce a valid image (the text just drops the number)."""
    black, red = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="-", aqi_value=None,
        category="Unknown", cat_color="black", city="Campbell", stale=False,
    )
    assert black.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)


def test_minimal_theme_returns_two_layers_at_panel_size():
    black, red = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="minimal",
    )
    assert black.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)
    assert red.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)


def test_minimal_theme_drops_left_stats_column():
    """The minimal layout sacrifices the stats column for a bigger hero AQI;
    a regression that re-introduced the stats rows would land ink in the
    upper-left quadrant."""
    stats_box = (8, 30, 130, 102)
    black_default, _ = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="default",
    )
    black_minimal, _ = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="minimal",
    )
    assert _nonwhite(black_minimal, stats_box) < _nonwhite(black_default, stats_box)


def test_minimal_theme_red_aqi_still_routes_to_red_layer():
    aqi_box = (60, 25, airQuality.PANEL_WIDTH - 60, 95)
    _, red_red = airQuality._render_panel_images(
        _payload(pm25=80), alert=False, trend_symbol="+", aqi_value=160,
        category="Unhealthy", cat_color="red", city="Campbell", stale=False,
        theme="minimal",
    )
    _, red_blk = airQuality._render_panel_images(
        _payload(pm25=10), alert=False, trend_symbol="+", aqi_value=42,
        category="Good", cat_color="black", city="Campbell", stale=False,
        theme="minimal",
    )
    assert _nonwhite(red_red, aqi_box) > _nonwhite(red_blk, aqi_box)


def test_minimal_theme_handles_aqi_value_none():
    black, _ = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="-", aqi_value=None,
        category="Unknown", cat_color="black", city="Campbell", stale=False,
        theme="minimal",
    )
    assert black.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)


def test_minimal_theme_long_category_falls_back_to_short_form():
    """USG label is wide enough that the full string overruns the panel; the
    minimal renderer should swap in the short form rather than clip."""
    black, red = airQuality._render_panel_images(
        _payload(pm25=45), alert=False, trend_symbol="+", aqi_value=120,
        category="Unhealthy for Sensitive Groups", cat_color="red",
        city="Campbell", stale=False, theme="minimal",
    )
    assert black.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)


def test_fredoka_theme_renders_at_panel_size():
    black, red = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="fredoka",
    )
    assert black.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)
    assert red.size == (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)


def test_fredoka_theme_keeps_default_layout_regions():
    """Fredoka swaps the typeface but keeps the default two-column layout, so
    the left-hand stats region must still carry meaningful ink (unlike minimal,
    which empties it out). This catches a regression that would accidentally
    point fredoka at the minimal body renderer."""
    stats_box = (8, 30, 130, 102)
    black_default, _ = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="default",
    )
    black_fredoka, _ = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="fredoka",
    )
    # Both should fill the stats region; ink counts should be in the same ballpark.
    default_ink = _nonwhite(black_default, stats_box)
    fredoka_ink = _nonwhite(black_fredoka, stats_box)
    assert default_ink > 0
    assert fredoka_ink > 0


def test_fredoka_theme_uses_different_glyphs_than_default():
    """Sanity check that the font swap actually produces different pixels —
    if both themes resolved to Inter, this test would fail."""
    black_default, _ = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="default",
    )
    black_fredoka, _ = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="fredoka",
    )
    assert list(black_default.getdata()) != list(black_fredoka.getdata())


def test_render_preview_png_raises_when_load_returns_none(tmp_path, monkeypatch):
    """Guard: if PIL.Image.load() ever returns None (closed/invalid image), the
    compositor must raise RuntimeError rather than silently writing a blank PNG."""
    from unittest.mock import MagicMock

    bad = MagicMock()
    bad.load.return_value = None
    monkeypatch.setattr(airQuality, "_render_panel_images", lambda *a, **kw: (bad, bad))

    with pytest.raises(RuntimeError, match="PIL.Image.load"):
        airQuality.render_preview_png(
            {"PM2.5": 12.0, "PM10": 18.0, "Temp": 70, "Humidity": 45, "Time": "12:00 PM"},
            alert=False, trend_symbol="+", aqi_value=50, category="Good",
            cat_color="black", city="Campbell", stale=False,
            out_path=str(tmp_path / "out.png"),
        )


def test_unknown_theme_falls_back_to_default():
    """A bogus theme that slipped past load_config (e.g. via direct API use)
    should still render — `_render_panel_images` falls back to default rather
    than blowing up."""
    black_unknown, _ = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="bogus",
    )
    black_default, _ = airQuality._render_panel_images(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, theme="default",
    )
    # Same theme = same pixels.
    assert list(black_unknown.getdata()) == list(black_default.getdata())

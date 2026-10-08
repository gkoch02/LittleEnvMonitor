"""Tests for the hardware-free render layer.

`_render_panel_images` returns the (black, red) 1-bit images that both the
e-ink path and the --dry-run PNG share, and `render_preview_png` composites
them. These tests do real PIL rendering and assert *structural* properties
(pixel counts in known regions, layer differences across modes) rather than
pixel-perfect snapshots, which keeps them robust to font rendering differences
across CI runners.
"""
import pytest
from PIL import Image

import airQuality

PANEL_SIZE = (airQuality.PANEL_WIDTH, airQuality.PANEL_HEIGHT)
TITLE_BOX = (10, 5, airQuality.PANEL_WIDTH - 10, 35)
# Left edge of the body: the default layout's stat rows live here, and the
# minimal layout's centered hero number never reaches it.
STATS_BOX = (8, 30, 80, 102)
TIMESTAMP_BOX = (150, 98, airQuality.PANEL_WIDTH - 6, 117)


def _payload(pm25=12.0, pm10=18.0, temp=70, humidity=45, time="12:00 PM"):
    return {"PM2.5": pm25, "PM10": pm10, "Temp": temp, "Humidity": humidity, "Time": time}


def _render(**overrides):
    kwargs = dict(
        data=_payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False,
    )
    kwargs.update(overrides)
    return airQuality._render_panel_images(**kwargs)


def _red_reading():
    return dict(data=_payload(pm25=80), aqi_value=160, category="Unhealthy", cat_color="red")


def _nonwhite(image, box=None):
    """Count inked (0) pixels in a 1-bit image, optionally within `box`."""
    if box is not None:
        image = image.crop(box)
    return sum(1 for px in image.getdata() if px == 0)


@pytest.mark.parametrize("theme", airQuality.SUPPORTED_THEMES)
@pytest.mark.parametrize("aqi_value,category", [(50, "Good"), (None, "Unknown")])
def test_every_theme_renders_two_1bit_layers(theme, aqi_value, category):
    """Smoke test: each theme renders, including the `--` placeholder used
    when `pm25_to_aqi` returns None."""
    black, red = _render(theme=theme, aqi_value=aqi_value, category=category)
    assert black.size == red.size == PANEL_SIZE
    assert black.mode == red.mode == "1"


def test_alert_changes_red_layer_title_region():
    """'AQI Rising!' replaces 'Air Quality - <city>' in the red title band."""
    _, red_normal = _render()
    _, red_alert = _render(alert=True, **_red_reading())
    assert _nonwhite(red_normal, TITLE_BOX) != _nonwhite(red_alert, TITLE_BOX)


def test_stale_changes_red_layer_title_region():
    _, red_fresh = _render()
    _, red_stale = _render(trend_symbol="?", stale=True)
    assert _nonwhite(red_fresh, TITLE_BOX) != _nonwhite(red_stale, TITLE_BOX)


def test_stale_render_shows_cached_reading_time():
    """A [CACHED] panel shows when the reading was taken, not the current
    time — so two stale renders differ only if their cached `Time` differs."""
    _, red_early = _render(stale=True, data=_payload(time="1:00 AM"))
    _, red_late = _render(stale=True, data=_payload(time="11:58 PM"))
    assert _nonwhite(red_early, TIMESTAMP_BOX) != _nonwhite(red_late, TIMESTAMP_BOX)


def test_stale_render_without_cached_time_still_renders():
    """Caches written before `Time` was rendered may lack it (or hold "N/A")."""
    for data in ({"PM2.5": 12.0, "PM10": 1, "Temp": 1, "Humidity": 1}, _payload(time="N/A")):
        black, _ = _render(stale=True, data=data)
        assert black.size == PANEL_SIZE


def test_stale_gauge_has_no_red_fill():
    gauge_box = (10, 104, 150, 114)
    _, red_fresh = _render(**_red_reading())
    _, red_stale = _render(stale=True, **_red_reading())
    assert _nonwhite(red_fresh, gauge_box) > 0
    assert _nonwhite(red_stale, gauge_box) == 0


def test_red_aqi_routes_to_red_layer_not_black():
    """When `cat_color='red'` the hero AQI must be drawn on the red layer.
    A regression here is what produces a panel that looks all-black for an
    Unhealthy reading."""
    aqi_box = (10, 70, airQuality.PANEL_WIDTH - 10, 100)
    _, red_red = _render(**_red_reading())
    _, red_blk = _render(data=_payload(pm25=10), aqi_value=42)
    assert _nonwhite(red_red, aqi_box) > _nonwhite(red_blk, aqi_box)


def test_borders_present_on_both_layers():
    """The frame is drawn on both layers; dropping one looks fine in the
    dry-run preview but renders oddly on the real panel."""
    black, red = _render()
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

    img = Image.open(out)
    assert img.mode == "RGB"
    assert img.size == (airQuality.PANEL_WIDTH * 2, airQuality.PANEL_HEIGHT * 2)


def test_render_preview_png_composites_black_over_red(tmp_path, monkeypatch):
    """Black ink wins where both layers are inked; red shows only where black
    is unset — mirroring how the panel renders the two buffers."""
    black = Image.new("1", PANEL_SIZE, 255)
    red = Image.new("1", PANEL_SIZE, 255)
    black.putpixel((0, 0), 0)
    red.putpixel((0, 0), 0)
    red.putpixel((1, 0), 0)
    monkeypatch.setattr(airQuality, "_render_panel_images", lambda *a, **kw: (black, red))
    out = tmp_path / "preview.png"

    airQuality.render_preview_png(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", out_path=str(out), scale=1,
    )

    img = Image.open(out)
    assert img.size == PANEL_SIZE
    assert img.getpixel((0, 0)) == (20, 20, 20)
    assert img.getpixel((1, 0)) == (200, 30, 30)
    assert img.getpixel((2, 0)) == (250, 250, 250)


def test_render_preview_png_creates_parent_dirs(tmp_path):
    out = tmp_path / "deep" / "nested" / "preview.png"
    airQuality.render_preview_png(
        _payload(), alert=False, trend_symbol="+", aqi_value=50, category="Good",
        cat_color="black", city="Campbell", stale=False, out_path=str(out),
    )
    assert out.is_file()


def test_minimal_theme_drops_left_stats_column():
    black_default, _ = _render(theme="default")
    black_minimal, _ = _render(theme="minimal")
    assert _nonwhite(black_default, STATS_BOX) > 0
    assert _nonwhite(black_minimal, STATS_BOX) == 0


def test_minimal_theme_red_aqi_still_routes_to_red_layer():
    aqi_box = (60, 25, airQuality.PANEL_WIDTH - 60, 95)
    _, red_red = _render(theme="minimal", **_red_reading())
    _, red_blk = _render(theme="minimal", data=_payload(pm25=10), aqi_value=42)
    assert _nonwhite(red_red, aqi_box) > _nonwhite(red_blk, aqi_box)


def test_fredoka_theme_keeps_default_layout():
    """Fredoka swaps the typeface but keeps the two-column layout, so the
    stats column must carry ink (the minimal layout leaves it empty)."""
    black_fredoka, _ = _render(theme="fredoka")
    assert _nonwhite(black_fredoka, STATS_BOX) > 0


def test_fredoka_theme_uses_different_glyphs_than_default():
    """If both themes resolved to Inter, the pixels would be identical."""
    black_default, _ = _render(theme="default")
    black_fredoka, _ = _render(theme="fredoka")
    assert list(black_default.getdata()) != list(black_fredoka.getdata())


def test_unknown_theme_falls_back_to_default():
    """A bogus theme that slipped past load_config (e.g. direct API use)
    renders the default layout rather than blowing up."""
    black_unknown, _ = _render(theme="bogus")
    black_default, _ = _render(theme="default")
    assert list(black_unknown.getdata()) == list(black_default.getdata())

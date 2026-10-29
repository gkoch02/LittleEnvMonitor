"""Render the README banner at docs/banner.png.

Drawn in the panel's own three inks (paper, black, red) with the panel's own
face, and the device on the right is `_render_panel_images()` on the same
dummy reading the previews use, scaled up pixel-for-pixel, so the banner
tracks the live layout. Deterministic: no clock reads, no network.

Usage:
    python docs/make_banner.py
"""

import os
import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import airQuality  # noqa: E402
from airQuality import _render_panel_images  # noqa: E402
from docs.generate_preview import DUMMY_DATA  # noqa: E402


class FrozenDatetime(datetime):
    """A live render stamps the panel with the wall clock; pin it to the dummy reading's time."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 6, 29, 14, 30, tzinfo=tz)


airQuality.datetime = FrozenDatetime

OUT_PATH = os.path.join(REPO_ROOT, "docs", "banner.png")
FONT_PATH = os.path.join(REPO_ROOT, "fonts", "Inter-Bold.ttf")

WIDTH, HEIGHT = 1600, 400
PAPER = (255, 255, 255)
INK = (0, 0, 0)
RED = (200, 24, 24)
SCALE = 3


def font(size):
    return ImageFont.truetype(FONT_PATH, size)


def panel_rgb():
    """The two 1-bit planes composited as the panel shows them: red ink wins over black."""
    black, red = _render_panel_images(
        DUMMY_DATA, alert=False, trend_symbol="-", aqi_value=35, category="Good",
        cat_color="black", city="Greenwich", stale=False,
    )
    out = Image.new("RGB", black.size, PAPER)
    out.paste(INK, mask=black.point(lambda v: 255 if v == 0 else 0))
    out.paste(RED, mask=red.point(lambda v: 255 if v == 0 else 0))
    return out


def main():
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)

    panel = panel_rgb()
    panel = panel.resize((panel.width * SCALE, panel.height * SCALE), Image.Resampling.NEAREST)
    px = WIDTH - panel.width - 60
    py = (HEIGHT - panel.height) // 2
    bezel = 10
    draw.rounded_rectangle(
        (px - bezel, py - bezel, px + panel.width + bezel, py + panel.height + bezel),
        radius=12, fill=INK,
    )
    image.paste(panel, (px, py))

    x = 70
    draw.text((x, 78), "Little Env Monitor", font=font(70), fill=INK)
    draw.text((x + 2, 180), "the air outside, on the wall, every half hour",
              font=font(32), fill=INK)
    draw.text((x + 2, 234), "PurpleAir  ·  Pi Zero  ·  2.13-inch black/red e-ink",
              font=font(24), fill=INK)

    # The panel's AQI gauge, as a motif: an outlined bar part-filled in red.
    gx, gy, gw, gh = x + 2, 300, 460, 22
    draw.rectangle((gx, gy, gx + gw, gy + gh), outline=INK, width=3)
    draw.rectangle((gx + 3, gy + 3, gx + int(gw * 35 / 300), gy + gh - 3), fill=RED)
    draw.text((gx + gw + 18, gy - 4), "AQI 35 · Good", font=font(24), fill=INK)

    palette = Image.new("P", (1, 1))
    palette.putpalette(list(PAPER) + list(INK) + list(RED) + [0, 0, 0] * 253)
    image = image.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
    image.save(OUT_PATH, optimize=True)
    print(f"wrote {os.path.relpath(OUT_PATH, REPO_ROOT)} ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    main()

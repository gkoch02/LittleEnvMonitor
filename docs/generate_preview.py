"""Render a PNG preview of what the e-ink panel shows, using dummy data.

This mirrors the drawing in airQuality.py:display_air_quality() but writes a
PNG instead of pushing buffers to the Waveshare panel, so it can run on any
machine without the Pi hardware libraries. Re-run after changing the layout
to refresh docs/preview.png.

Usage:
    python docs/generate_preview.py
"""

from PIL import Image, ImageDraw, ImageFont

# Match epd2in13b_V4: panel is 122x250, drawn landscape as 250x122.
WIDTH, HEIGHT = 250, 122
SCALE = 3  # upscale so the PNG is legible in the README

FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
OUT_PATH = "docs/preview.png"

DUMMY_DATA = {
    "PM2.5": 8.4,
    "PM10": 14.2,
    "Temp": 68,
    "Humidity": 52,
    "Time": "2:30 PM",
}
DUMMY_HEADER = "Air Quality - Campbell"
DUMMY_TREND = "-"
DUMMY_CATEGORY = "Good"
DUMMY_CAT_COLOR = "black"
DUMMY_TIMESTAMP = "2:30pm"


def render():
    font_large = ImageFont.truetype(FONT_PATH_BOLD, 18)
    font_small = ImageFont.truetype(FONT_PATH_BOLD, 16)
    font_xsmall = ImageFont.truetype(FONT_PATH_BOLD, 12)

    image_black = Image.new("1", (WIDTH, HEIGHT), 255)
    image_red = Image.new("1", (WIDTH, HEIGHT), 255)
    draw_black = ImageDraw.Draw(image_black)
    draw_red = ImageDraw.Draw(image_red)

    draw_red.rectangle((5, 5, WIDTH - 5, HEIGHT - 5), outline=0, width=3)
    draw_black.rectangle((3, 3, WIDTH - 3, HEIGHT - 3), outline=0, width=3)

    draw_red.text((10, 10), DUMMY_HEADER, font=font_large, fill=0)

    y_offset = 40
    spacing = 18
    draw_black.line(
        [(10, y_offset - 4), (WIDTH - 10, y_offset - 4)], fill=0, width=1
    )
    draw_black.text(
        (10, y_offset),
        f"PM2.5: {DUMMY_DATA['PM2.5']} µg/m³  {DUMMY_TREND}",
        font=font_small,
        fill=0,
    )
    draw_black.text(
        (10, y_offset + spacing),
        f"PM10:  {DUMMY_DATA['PM10']} µg/m³",
        font=font_small,
        fill=0,
    )
    draw_black.text(
        (10, y_offset + 3 * spacing),
        f"T/H:   {DUMMY_DATA['Temp']} °F / {DUMMY_DATA['Humidity']}%",
        font=font_small,
        fill=0,
    )

    aqi_y = y_offset + 2 * spacing
    aqi_text = f"AQI: {DUMMY_CATEGORY}"
    if DUMMY_CAT_COLOR == "red":
        draw_red.text((10, aqi_y), aqi_text, font=font_small, fill=0)
    else:
        draw_black.text((10, aqi_y), aqi_text, font=font_small, fill=0)

    bbox = font_xsmall.getbbox(DUMMY_TIMESTAMP)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = WIDTH - text_width - 10
    y = HEIGHT - text_height - 12
    draw_red.text((x, y), DUMMY_TIMESTAMP, font=font_xsmall, fill=0)

    # Composite into an RGB preview: white background, red where the red layer
    # is set, black where the black layer is set (black wins overlaps, like
    # the panel itself).
    preview = Image.new("RGB", (WIDTH, HEIGHT), (250, 250, 250))
    px = preview.load()
    rb = image_red.load()
    bb = image_black.load()
    for j in range(HEIGHT):
        for i in range(WIDTH):
            if bb[i, j] == 0:
                px[i, j] = (20, 20, 20)
            elif rb[i, j] == 0:
                px[i, j] = (200, 30, 30)

    preview = preview.resize(
        (WIDTH * SCALE, HEIGHT * SCALE), Image.NEAREST
    )
    preview.save(OUT_PATH)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    render()

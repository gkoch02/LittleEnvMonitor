"""Render a PNG preview of what the e-ink panel shows, using dummy data.

This delegates to `airQuality.render_preview_png()` so the layout stays in
sync with the live e-ink path automatically — no parallel copy of the draw
code to keep aligned. Re-run after changing the layout to refresh
`docs/preview.png`.

Usage:
    python docs/generate_preview.py
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from airQuality import render_preview_png  # noqa: E402

DUMMY_DATA = {
    "PM2.5": 8.4,
    "PM10": 14.2,
    "Temp": 68,
    "Humidity": 52,
    "Time": "2:30 PM",
}
OUT_PATH = os.path.join(REPO_ROOT, "docs", "preview.png")


def render():
    render_preview_png(
        data=DUMMY_DATA,
        alert=False,
        trend_symbol="-",
        aqi_value=35,
        category="Good",
        cat_color="black",
        city="Campbell",
        stale=False,
        out_path=OUT_PATH,
        scale=3,
    )
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    render()

"""Render PNG previews of what the e-ink panel shows, using dummy data.

This delegates to `airQuality.render_preview_png()` so the layout stays in
sync with the live e-ink path automatically — no parallel copy of the draw
code to keep aligned. One PNG is written per supported theme; re-run after
changing a layout to refresh the README screenshots.

Usage:
    python docs/generate_preview.py
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from airQuality import SUPPORTED_THEMES, render_preview_png  # noqa: E402

DUMMY_DATA = {
    "PM2.5": 8.4,
    "PM10": 14.2,
    "Temp": 68,
    "Humidity": 52,
    "Time": "2:30 PM",
}
DOCS_DIR = os.path.join(REPO_ROOT, "docs")
# `default` keeps the historical filename so existing README links / external
# references stay live; alternative themes get a `preview-<theme>.png` suffix.
DEFAULT_OUT = os.path.join(DOCS_DIR, "preview.png")


def _out_path(theme):
    return DEFAULT_OUT if theme == "default" else os.path.join(
        DOCS_DIR, f"preview-{theme}.png",
    )


def render():
    for theme in SUPPORTED_THEMES:
        out = _out_path(theme)
        render_preview_png(
            data=DUMMY_DATA,
            alert=False,
            trend_symbol="-",
            aqi_value=35,
            category="Good",
            cat_color="black",
            city="Campbell",
            stale=False,
            out_path=out,
            scale=3,
            theme=theme,
        )
        print(f"wrote {out}")


if __name__ == "__main__":
    render()

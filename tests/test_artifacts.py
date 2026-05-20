"""Smoke tests for shipped artifacts that aren't otherwise exercised.

`airquality.conf.example` and `docs/generate_preview.py` both ship to users
but had no test coverage — silent drift here means a maintainer edit can
break the README screenshots or the documented config schema without CI
catching it.
"""
import os
import subprocess
import sys

import airQuality

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_conf_example_loads_via_load_config(tmp_path, monkeypatch):
    """The shipped example must parse under load_config(). The sensor_id is a
    placeholder that won't parse as int, so we substitute a real id before
    loading — that's a documented user step, not a config-schema issue. The
    api_key placeholder is handled the documented way (env var override)."""
    src = os.path.join(REPO_ROOT, "airquality.conf.example")
    text = open(src).read().replace("YOUR_SENSOR_ID", "12345")
    dst = tmp_path / "airquality.conf"
    dst.write_text(text)

    monkeypatch.setenv("PURPLEAIR_API_KEY", "real-key-from-env")
    api_key, sensor_id, weather_coords, city, theme = airQuality.load_config(str(dst))

    assert api_key == "real-key-from-env"
    assert sensor_id == 12345
    assert weather_coords is not None  # [weather] section is present in the example
    lat, lon = weather_coords
    assert -90 <= lat <= 90
    assert -180 <= lon <= 180
    assert city == "Campbell"
    assert theme in airQuality.SUPPORTED_THEMES


def test_generate_preview_writes_one_png_per_theme(tmp_path, monkeypatch):
    """`docs/generate_preview.py` is the documented way to refresh README
    screenshots after layout changes. Run it as a subprocess so we exercise
    the same entry point a maintainer would, and redirect the docs dir to a
    tmp_path so we don't clobber the checked-in PNGs."""
    docs_target = tmp_path / "docs"
    docs_target.mkdir()

    # The script writes to `<repo>/docs/preview*.png` — symlink the tmp dir
    # into a fake repo layout and point the script at it via PYTHONPATH so
    # `from airQuality import ...` still resolves.
    script = os.path.join(REPO_ROOT, "docs", "generate_preview.py")

    # Run the script with a wrapper that swaps DOCS_DIR before render() runs.
    runner = tmp_path / "run.py"
    runner.write_text(
        "import sys, os\n"
        f"sys.path.insert(0, {REPO_ROOT!r})\n"
        f"sys.path.insert(0, {os.path.dirname(script)!r})\n"
        "import generate_preview\n"
        f"generate_preview.DOCS_DIR = {str(docs_target)!r}\n"
        "generate_preview.DEFAULT_OUT = os.path.join(generate_preview.DOCS_DIR, 'preview.png')\n"
        "generate_preview.render()\n"
    )

    result = subprocess.run(
        [sys.executable, str(runner)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    # One PNG per supported theme, with `default` keeping the historical filename.
    expected = {
        "default": docs_target / "preview.png",
        "minimal": docs_target / "preview-minimal.png",
        "fredoka": docs_target / "preview-fredoka.png",
    }
    assert set(airQuality.SUPPORTED_THEMES) == set(expected), (
        "generate_preview.py output filenames are out of sync with SUPPORTED_THEMES"
    )
    for theme, path in expected.items():
        assert path.is_file(), f"missing preview for theme {theme!r}: {path}"
        assert path.stat().st_size > 0, f"empty preview for theme {theme!r}: {path}"

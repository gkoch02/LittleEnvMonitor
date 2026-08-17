"""Tests for the --dry-run CLI mode.

Dry-run is the on-laptop smoke test path: it uses the same fetch + render
pipeline but writes a PNG instead of touching e-ink hardware, and skips cache
and heartbeat writes (the operator asked for a one-off preview, not a state
update).
"""
import json
import time

import pytest

import airQuality


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(airQuality, "CACHE_PATH", str(state / "airquality" / "last_reading.json"))
    monkeypatch.setattr(airQuality, "HEARTBEAT_PATH", str(state / "airquality" / "heartbeat"))
    return state


@pytest.fixture
def conf(tmp_path, monkeypatch):
    path = tmp_path / "airquality.conf"
    path.write_text(
        "[purpleair]\napi_key = real-key\nsensor_id = 12345\n"
    )
    monkeypatch.setattr(airQuality, "CONF_PATH", str(path))
    return path


def _payload(pm25=20.0):
    return {
        "PM2.5": pm25, "PM10": 22.0, "Temp": 70, "Humidity": 40, "Time": "12:00 PM",
        "LastSeenEpoch": time.time(),
    }


def test_dry_run_writes_png_and_skips_state(tmp_path, state_dir, conf, monkeypatch):
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", lambda *a, **kw: _payload())
    out = tmp_path / "preview.png"

    rc = airQuality.main(["--dry-run", str(out)])

    assert rc == 0
    assert out.is_file()
    # No state side effects.
    assert not (state_dir / "airquality" / "last_reading.json").exists()
    assert not (state_dir / "airquality" / "heartbeat").exists()


def test_dry_run_does_not_fall_back_to_cache_on_fetch_failure(
    tmp_path, state_dir, conf, monkeypatch,
):
    """A real run would render [CACHED] here; dry-run should fail loudly."""
    cache_dir = state_dir / "airquality"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last_reading.json").write_text(json.dumps(_payload(pm25=15.0)))

    def _boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(airQuality, "fetch_purpleair_data", _boom)
    out = tmp_path / "preview.png"

    rc = airQuality.main(["--dry-run", str(out)])

    assert rc == 1
    assert not out.exists()


def test_dry_run_png_write_failure_returns_one(tmp_path, state_dir, conf, monkeypatch):
    """If render_preview_png raises (e.g. disk full), dry-run must return 1
    and must NOT fall through to the [CACHED] render path."""
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", lambda *a, **kw: _payload())

    def _boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(airQuality, "render_preview_png", _boom)
    out = tmp_path / "preview.png"

    rc = airQuality.main(["--dry-run", str(out)])

    assert rc == 1
    assert not out.exists()
    # No cache or heartbeat side-effects on the failure path either.
    assert not (state_dir / "airquality" / "last_reading.json").exists()
    assert not (state_dir / "airquality" / "heartbeat").exists()


def test_dry_run_default_path(tmp_path, state_dir, conf, monkeypatch):
    """`--dry-run` with no argument uses ./airquality-preview.png."""
    monkeypatch.setattr(airQuality, "fetch_purpleair_data", lambda *a, **kw: _payload())
    monkeypatch.chdir(tmp_path)

    rc = airQuality.main(["--dry-run"])

    assert rc == 0
    assert (tmp_path / "airquality-preview.png").is_file()

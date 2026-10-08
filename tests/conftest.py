"""Shared test setup.

`display_air_quality()` lazily imports `waveshare_epd.epd2in13b_V4`, and the
real `waveshare_epd.epdconfig` runs Raspberry Pi / Jetson hardware detection
at import time — which raises on a non-Pi host. We stub the package out in
`sys.modules` so that lazy import picks up `FakeEPD` instead.
"""
import json
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import airQuality  # noqa: E402


class FakeEPD:
    """Minimal stand-in for the Waveshare EPD class.

    Records every method call so tests can assert on the sequence. Defaults to
    a successful run (`init` returns 0, all methods are no-ops). Override
    per-method behavior with `monkeypatch.setattr(FakeEPD, "init", ...)`.
    Each constructed instance is appended to `FakeEPD.instances`.
    """

    instances: list = []

    def __init__(self):
        self.calls = []
        FakeEPD.instances.append(self)

    def init(self):
        self.calls.append(("init",))
        return 0

    def Clear(self):
        self.calls.append(("Clear",))

    def getbuffer(self, image):
        # Return a tagged sentinel so `display`'s recorder can assert the
        # positional order (black buffer first, red buffer second).
        self.calls.append(("getbuffer", image))
        return ("buffer-for", id(image))

    def display(self, *args, **kwargs):
        self.calls.append(("display", args, kwargs))

    def sleep(self):
        self.calls.append(("sleep",))


fake_epd_module = types.ModuleType("waveshare_epd.epd2in13b_V4")
fake_epd_module.EPD = FakeEPD  # type: ignore[attr-defined]

# Build a real package module for `waveshare_epd` so submodule attribute
# resolution returns our fake (a MagicMock here would intercept attribute
# lookups and shadow the sys.modules entry for the submodule).
waveshare_pkg = types.ModuleType("waveshare_epd")
waveshare_pkg.__path__ = []  # type: ignore[attr-defined]  # mark as a package
waveshare_pkg.epd2in13b_V4 = fake_epd_module  # type: ignore[attr-defined]

sys.modules["waveshare_epd"] = waveshare_pkg
sys.modules["waveshare_epd.epd2in13b_V4"] = fake_epd_module


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Point the cache and heartbeat at a per-test state dir."""
    state = tmp_path / "state"
    monkeypatch.setattr(airQuality, "CACHE_PATH", str(state / "airquality" / "last_reading.json"))
    monkeypatch.setattr(airQuality, "HEARTBEAT_PATH", str(state / "airquality" / "heartbeat"))
    return state


@pytest.fixture
def seed_cache(state_dir):
    """Write a reading to the cache file; returns the cache path."""
    def _seed(reading):
        path = state_dir / "airquality" / "last_reading.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(reading))
        return path
    return _seed


@pytest.fixture
def mock_get(monkeypatch):
    """Replace the cached requests.Session with a stub whose .get is a MagicMock."""
    fake_session = MagicMock()
    monkeypatch.setattr(airQuality, "_http_session", lambda: fake_session)
    return fake_session.get


def network_down(*args, **kwargs):
    """Drop-in for `fetch_purpleair_data` that simulates an outage."""
    raise RuntimeError("network down")

"""Shared test setup.

`airQuality.py` imports `waveshare_epd.epd2in13b_V4` at module load, and the
underlying `waveshare_epd.epdconfig` runs Raspberry Pi / Jetson hardware
detection at *its* import time — which raises on a non-Pi host. The tests
exercise only the platform-independent code paths, so we stub the package out
in `sys.modules` before any test imports `airQuality`.

The stub for `epd2in13b_V4` exposes a tiny `EPD` class with the same surface
the script actually calls (`init`, `Clear`, `display`, `getbuffer`, `sleep`,
plus `width`/`height` attributes). Tests that need to inspect or fail-inject
display calls can monkeypatch attributes on the class.
"""
import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


class FakeEPD:
    """Minimal stand-in for the Waveshare EPD class.

    Records every method call so tests can assert on the sequence. Defaults to
    a successful run (`init` returns 0, all methods are no-ops). Override
    per-method behavior with `monkeypatch.setattr(FakeEPD, "init", ...)`.

    Each constructed instance is appended to `FakeEPD.instances`; tests that
    need to inspect what `display_air_quality` did should clear this list at
    setup (the auto-clear fixture in `tests/test_display.py` does so).
    """

    width = 122
    height = 250
    instances: list = []  # populated in __init__

    def __init__(self):
        self.calls = []
        FakeEPD.instances.append(self)

    def init(self):
        self.calls.append(("init",))
        return 0

    def Clear(self):
        self.calls.append(("Clear",))

    def getbuffer(self, image):
        self.calls.append(("getbuffer",))
        return b""

    def display(self, *args, **kwargs):
        self.calls.append(("display",))

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

"""Shared test setup.

`airQuality.py` imports `waveshare_epd.epd2in13b_V4` at module load, and the
underlying `waveshare_epd.epdconfig` runs Raspberry Pi / Jetson hardware
detection at *its* import time — which raises on a non-Pi host. The tests
exercise only the platform-independent code paths, so we stub the package out
in `sys.modules` before any test imports `airQuality`.
"""
import os
import sys
from unittest.mock import MagicMock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

sys.modules["waveshare_epd"] = MagicMock()
sys.modules["waveshare_epd.epd2in13b_V4"] = MagicMock()

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-script Raspberry Pi air quality monitor. `airQuality.py` runs once per systemd timer tick, fetches a PurpleAir sensor via the PurpleAir API, renders the reading to a Waveshare 2.13" black/red e-ink display (`epd2in13b_V4`), and caches the full reading so the next tick can fall back if the fetch fails.

There is no build step and no package — `airQuality.py` is the entry point and everything else is supporting infrastructure. A pytest suite under `tests/` covers the platform-independent code paths (AQI classification, config parsing, the PurpleAir HTTP client, Open-Meteo fallback, the JSON cache, and the orchestration in `main()`); GitHub Actions runs `ruff`, `mypy`, and `pytest` on every push and pull request across Python 3.10/3.11/3.12.

## Commands

Deploy / reinstall (creates `.venv/`, installs deps, validates config, renders and installs the systemd unit, enables the timer):
```bash
bash deploy.sh
# bash deploy.sh --check-api   # also smoke-test the PurpleAir key/sensor
```

Manual run via systemd (uses the installed unit + venv):
```bash
sudo systemctl start airquality.service
journalctl -u airquality.service -f
```

Manual run from a dev checkout (no systemd, uses the venv directly):
```bash
.venv/bin/python airQuality.py
```

Dry-run on any machine (no e-ink hardware needed — fetches real data, writes a PNG preview, skips cache/heartbeat):
```bash
.venv/bin/python airQuality.py --dry-run                  # writes ./airquality-preview.png
.venv/bin/python airQuality.py --dry-run /tmp/preview.png # custom path
```

Timer status / upcoming runs:
```bash
systemctl status airquality.timer
systemctl list-timers airquality.timer
```

Override the cache location for local testing without touching `/var/lib/airquality/`:
```bash
AIRQUALITY_STATE_DIR=/tmp/aq .venv/bin/python airQuality.py
```

Run the full check suite (works on any machine — does not require Pi hardware libs):
```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m mypy airQuality.py
python -m pytest        # enforces --cov-fail-under=75 from pyproject.toml
```

Regenerate the README preview images after changing the e-ink layout (one PNG per theme):
```bash
python docs/generate_preview.py
```

## Architecture notes worth knowing up front

**Config is loaded inside `main()`, not at import.** Historically it loaded at module scope, which meant a missing/invalid `airquality.conf` crashed before the cached-fallback path could run. If you refactor, keep `load_config()` inside `main()` and keep it raising `SystemExit` with a human-readable message.

**`PURPLEAIR_API_KEY` env var wins over the config file.** This exists so the systemd unit can ship the secret via `EnvironmentFile=` (mode 0600) instead of leaving it in the repo dir. `load_config()` strips whitespace from the env var first, so a blank/whitespace-only env var falls back to the file rather than clobbering it. `deploy.sh`'s preflight validation mirrors this: a placeholder key in the file is OK as long as the env var is set.

**The e-ink panel must always be put to sleep.** `display_air_quality()` wraps the draw in `try/finally` so `epd.sleep()` runs even if drawing raises. Leaving the panel powered shortens its life. Any new display-side code must preserve this invariant.

**Drawing is split from hardware.** `_render_panel_images()` builds the (black, red) 1-bit images from the data and returns them; `display_air_quality()` rotates and pushes them to the EPD; `render_preview_png()` composites them into an upscaled RGB PNG. Both consumers go through the same draw helper so the live e-ink path and the `--dry-run`/`docs/generate_preview.py` previews can never drift. If you tweak the layout, edit `_render_panel_images()` and re-run `python docs/generate_preview.py` to refresh `docs/preview.png`.

**The Waveshare hardware import is lazy.** `from waveshare_epd import epd2in13b_V4` lives *inside* `display_air_quality()`, not at module scope. This lets a dev box without `RPi.GPIO`/`spidev` (and without the test-time stub) still `import airQuality` for the `--dry-run` path. When invoked as a script, Python adds the script's directory to `sys.path[0]` automatically, so the lazy import resolves the vendored package without help — there is no longer a module-level `sys.path.insert`. Don't reintroduce one; if you need to import `airQuality` from a different cwd, add the path on the caller side (the tests' `conftest.py` already does).

**Two SIGALRM fences guard the e-ink path.** The vendored Waveshare busy-wait has no timeout of its own, so `_alarm(DISPLAY_TIMEOUT_SEC=60)` wraps the draw and a separate `_alarm(SLEEP_TIMEOUT_SEC=10)` wraps `epd.sleep()` in the `finally` (SIGALRM is one-shot, so the sleep needs a fresh alarm). These exist because the systemd unit has `TimeoutStartSec=120` — without them a stuck SPI/GPIO call would eat the whole budget and starve the cache-fallback render. POSIX-only by design (the unit is Linux-only).

**HTTP retry logic distinguishes 4xx from 5xx/network errors.** `fetch_purpleair_data()` only retries on timeouts, connection errors, and 5xx. A 401 (bad key) or 404 (bad sensor id) fails fast with a `RuntimeError` — don't widen this to retry all errors, it just delays the real failure by 30+ seconds. The one 4xx exception is **429 rate-limit**, which is retried with `Retry-After` honored but capped at `RETRY_AFTER_CAP_SEC=30` so a 5-minute hint can't blow past `TimeoutStartSec`. Default backoff between attempts is `min(2**attempt, 8)` seconds (2/4/8s).

**Module-level caches: `_http_session()` and `_load_font()`.** Both are `functools.lru_cache`-wrapped. The `requests.Session` saves a TLS handshake per call (meaningful on a Pi Zero) and is shared between PurpleAir + Open-Meteo. Fonts are cached because they're identical every render. Both are lazy so `import airQuality` stays cheap and tests that patch `requests.get` keep working unchanged.

**Temp/humidity fall back to Open-Meteo, not the cache.** When the PurpleAir reading comes back missing `Temp` or `Humidity` (the sensor sometimes drops them) `main()` calls `fetch_local_weather()` against Open-Meteo (free, no API key) using the optional `[weather] latitude/longitude` from `airquality.conf`. The fallback only fills the missing field — PM2.5/PM10 still come from PurpleAir. If the `[weather]` section is absent we just log and continue with `N/A`; we don't pull temp/humidity from the JSON cache, since stale weather is worse than no weather.

**Title bar city comes from `[display] city` in `airquality.conf`.** The e-ink header reads `Air Quality - <city>`, defaulting to `Campbell` when the section/key is absent or blank. Don't reintroduce a hardcoded city string — `display_air_quality()` takes `city` as a parameter and `main()` threads it through from `load_config()`.

**Numeric AQI and category label are kept in lock-step.** `pm25_to_aqi()` does the EPA piecewise-linear PM2.5 → AQI conversion (40 CFR Part 58 App. G, 2012 breakpoints) and `classify_aqi()` returns the matching category band; the bands in both functions are deliberately identical, and `tests/test_pm25_to_aqi.py::test_aqi_band_matches_classify_aqi_category` asserts they agree. If you ever update one (e.g. to the 2024 EPA revision) update the other in the same change. The display renders the AQI as a hero number in the right column with the category label beneath (e.g. `35` over `Good`); if `pm25_to_aqi()` returns `None` (negative/non-numeric) the renderer shows `--` in place of the number and just the category below, so any cache entry without a usable PM2.5 still renders cleanly. Long category names that don't fit the hero column are abbreviated via `_CATEGORY_SHORT` (e.g. `Unhealthy for Sensitive Groups` → `USG`); add new entries there if you ever introduce another long band.

**Layout split: title bar + theme body + bottom strip.** `_render_panel_images()` lays the panel out as: a red title bar (`Air Quality - <city>` / `AQI Rising!` / `Air Quality [CACHED]`), a hairline divider, a theme-specific body region, and a bottom strip that shares an AQI gauge bar with the timestamp. The title bar, frame, and bottom strip are shared across all themes so the alert/stale/cache invariants behave identically regardless of theme. The body region is dispatched via theme: `default` and `fredoka` call `_draw_default_body()` (two-column: stat rows left, hero AQI right); `minimal` calls `_draw_minimal_body()` (giant centered AQI, no stats column). The gauge is an outlined rect with a red fill proportional to `min(AQI, 300) / 300` — saturated = "at least very unhealthy." On `stale=True` the gauge intentionally renders outline-only (no red fill) so a `[CACHED]` panel reads as obviously not-fresh at a glance. The borders on both layers shrank from width=3 to width=1 in this redesign; `tests/test_render.py::test_borders_present_on_both_layers` still asserts an inked pixel at `(3,3)` on black and `(5,5)` on red, so keep at least a 1-pixel rect at those coords if you rework the frame again.

**Themes are selected via `[display] theme` in `airquality.conf`.** `SUPPORTED_THEMES = ("default", "minimal", "fredoka")` and `DEFAULT_THEME = "default"` are the canonical list; `load_config()` validates against it and raises `SystemExit` for unknown values. `_THEME_FONT_PATHS` maps each theme to a font file — `default` and `minimal` use `fonts/Inter-Bold.ttf`; `fredoka` uses `fonts/Fredoka-VariableFont_wdth,wght.ttf`. `_load_font()` detects variable fonts via `get_variation_names()` and selects the "Bold" named instance after loading (Fredoka ships as a single variable font file). Add a row to `_THEME_FONT_PATHS` to introduce a new font-only theme; a new body layout needs a new `_draw_<name>_body()` function and a dispatch branch in `_render_panel_images()`.

**`--dry-run` is the on-laptop smoke test.** `main()` accepts an optional `--dry-run [PATH]` that fetches real PurpleAir data, runs the same trend/AQI/category logic, and writes a PNG via `render_preview_png()` instead of pushing to the e-ink panel. It deliberately differs from a normal run on two points: it skips `write_cache()`/`write_heartbeat()` (no state side-effects), and on fetch failure it returns 1 instead of falling back to a `[CACHED]` render — the operator asked for a fresh preview, not a stale one. Default output is `./airquality-preview.png`; pass a path to override. Coverage lives in `tests/test_dry_run.py`.

**One JSON cache, used for both fallback rendering and trend detection.** The live run writes the full reading to `$AIRQUALITY_STATE_DIR/airquality/last_reading.json` (defaulting via `XDG_STATE_HOME`). On the next tick that same file is read for two purposes: computing the PM2.5 delta that drives the trend marker and the "AQI Rising!" banner, and — if the live fetch fails — feeding a `stale=True` render that shows "Air Quality [CACHED]". Writes go through a `.tmp` + `os.replace` to stay atomic. An older PM2.5-only text cache (`.last_pm25`) used to live in the repo root; don't reintroduce it, the cached display path needs the full PM10/Temp/Humidity payload.

**Trend marker vs. "AQI Rising!" banner use different rules.** The `+/-` next to PM2.5 shows `+` only when the current PM2.5 is strictly higher than the cached value, and `-` otherwise (including when the value held steady, fell, or no cached reading exists). The red "AQI Rising!" banner is stricter: it fires only when PM2.5 has climbed by at least `TREND_THRESHOLD` (5 µg/m³) since the cached reading. Tune `TREND_THRESHOLD` at the top of `airQuality.py` if the banner is too noisy or too quiet.

**Heartbeat file marks fully-successful runs.** On the live render path `main()` writes the current UTC ISO-8601 timestamp to `$AIRQUALITY_STATE_DIR/airquality/heartbeat` (atomic via `.tmp` + `os.replace`). It is **not** updated on the cache-fallback path, so an external monitor can alert when the file goes stale and catch a unit that's silently stuck rendering [CACHED]. The timer doesn't fire overnight (08:00–21:30 only), so any staleness alert needs to be scoped to the run window — see README for the recommended threshold.

**Cache-fallback runs still exit 1.** The systemd unit is `Type=oneshot` with **no `Restart=`** (the timer is the retry mechanism). A successful live render exits 0, anything that ends in `_render_cached_fallback` exits 1 — that's intentional so journalctl/monitoring can spot the outage. Don't add `Restart=on-failure`; it would relaunch every 30s on top of the 30-min timer tick.

**Post-render persistence errors are logged, not fatal.** Once `display_air_quality()` returns successfully, `main()` calls `write_cache()` and `write_heartbeat()` inside a `try/except OSError` — a disk-full or permissions error there must NOT downgrade the run to a cache-fallback render, because the user is already looking at fresh data. Keep this split (separate `_render_cached_fallback` helper) intact.

**`systemd/airquality.service.in` is a template, not an installable unit.** `deploy.sh` substitutes `@USER@`, `@GROUP@`, `@REPO_DIR@`, `@PYTHON@`, `@STATE_DIR@` and installs the rendered file to `/etc/systemd/system/airquality.service`. If you edit the unit, edit the `.in` template and re-run `deploy.sh` (or `sed` + `systemctl daemon-reload` manually). Don't hardcode `pi`/`/home/pi` — deploys run as any user. The unit is sandboxed (`ProtectSystem=strict`, `MemoryMax=128M`, `RestrictAddressFamilies=...`); `AF_NETLINK` is kept because sysfs-backed SPI/GPIO needs it.

**`deploy.sh` ends with a post-check, not just `enable --now`.** After enabling the timer it runs `systemctl start airquality.service` once (Type=oneshot blocks until exit), reads `systemctl show -p Result -p ExecMainStatus` to classify the run, and tails 20 lines of `journalctl -u airquality.service`. A non-zero exit doesn't fail the deploy — a freshly enabled SPI bus or a transient PurpleAir blip is normal, and the timer will retry — but the operator gets immediate feedback instead of having to remember to check journalctl after walking away.

**`waveshare_epd/` is vendored, read-only.** The files are copied from [waveshare/e-Paper](https://github.com/waveshare/e-Paper). Don't patch them locally — update by recopying from upstream and bumping the version table in `waveshare_epd/UPSTREAM.md`. Ruff and mypy are configured to skip this directory.

**`tests/conftest.py` stubs `waveshare_epd` in `sys.modules` before tests import `airQuality`.** The real `epdconfig` runs Pi/Jetson hardware detection at *its* import time and raises on a non-Pi host. With the EPD import now lazy (inside `display_air_quality()`), this stub is consulted at *call* time rather than import time, but the mechanism is the same — the entries in `sys.modules` are picked up by the lazy `from waveshare_epd import epd2in13b_V4`. The `FakeEPD` class records every method call so display-path tests can assert on the sequence and inject failures via `monkeypatch.setattr(FakeEPD, ...)`. If you add a new EPD method to `display_air_quality()`, add it to `FakeEPD` too.

## Files you'll touch most

- `airQuality.py` — the whole program
- `tests/` — pytest suite; `conftest.py` owns the waveshare stub, the rest mirror module names (`test_load_config.py`, `test_fetch_purpleair.py`, etc.)
- `systemd/airquality.service.in` — unit template (edit here, not the installed copy)
- `systemd/airquality.timer` — schedule (every 30 min, 08:00–21:30)
- `deploy.sh` — bootstrap on a fresh Pi
- `airquality.conf` — local, gitignored, holds the PurpleAir API key, sensor id, optional `[weather]` coords, optional `[display] city`, and optional `[display] theme`
- `pyproject.toml` — ruff/mypy/pytest config (line length 100, target py310, coverage floor 75%)
- `fonts/` — vendored TrueType fonts: `Inter-Bold.ttf` (default/minimal themes) and `Fredoka-VariableFont_wdth,wght.ttf` (fredoka theme). OFL license files sit alongside them.
- `docs/generate_preview.py` — regenerates the preview PNGs after layout changes; writes one per theme (`docs/preview.png`, `docs/preview-minimal.png`, `docs/preview-fredoka.png`) via `airQuality.render_preview_png()` so there's no parallel copy of the draw code to keep aligned

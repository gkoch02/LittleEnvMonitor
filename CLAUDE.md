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

Regenerate the README preview image after changing the e-ink layout:
```bash
python docs/generate_preview.py
```

## Architecture notes worth knowing up front

**Config is loaded inside `main()`, not at import.** Historically it loaded at module scope, which meant a missing/invalid `airquality.conf` crashed before the cached-fallback path could run. If you refactor, keep `load_config()` inside `main()` and keep it raising `SystemExit` with a human-readable message.

**`PURPLEAIR_API_KEY` env var wins over the config file.** This exists so the systemd unit can ship the secret via `EnvironmentFile=` (mode 0600) instead of leaving it in the repo dir. `load_config()` strips whitespace from the env var first, so a blank/whitespace-only env var falls back to the file rather than clobbering it. `deploy.sh`'s preflight validation mirrors this: a placeholder key in the file is OK as long as the env var is set.

**The e-ink panel must always be put to sleep.** `display_air_quality()` wraps the draw in `try/finally` so `epd.sleep()` runs even if drawing raises. Leaving the panel powered shortens its life. Any new display-side code must preserve this invariant.

**Two SIGALRM fences guard the e-ink path.** The vendored Waveshare busy-wait has no timeout of its own, so `_alarm(DISPLAY_TIMEOUT_SEC=60)` wraps the draw and a separate `_alarm(SLEEP_TIMEOUT_SEC=10)` wraps `epd.sleep()` in the `finally` (SIGALRM is one-shot, so the sleep needs a fresh alarm). These exist because the systemd unit has `TimeoutStartSec=120` — without them a stuck SPI/GPIO call would eat the whole budget and starve the cache-fallback render. POSIX-only by design (the unit is Linux-only).

**HTTP retry logic distinguishes 4xx from 5xx/network errors.** `fetch_purpleair_data()` only retries on timeouts, connection errors, and 5xx. A 401 (bad key) or 404 (bad sensor id) fails fast with a `RuntimeError` — don't widen this to retry all errors, it just delays the real failure by 30+ seconds. The one 4xx exception is **429 rate-limit**, which is retried with `Retry-After` honored but capped at `RETRY_AFTER_CAP_SEC=30` so a 5-minute hint can't blow past `TimeoutStartSec`. Default backoff between attempts is `min(2**attempt, 8)` seconds (2/4/8s).

**Module-level caches: `_http_session()` and `_load_font()`.** Both are `functools.lru_cache`-wrapped. The `requests.Session` saves a TLS handshake per call (meaningful on a Pi Zero) and is shared between PurpleAir + Open-Meteo. Fonts are cached because they're identical every render. Both are lazy so `import airQuality` stays cheap and tests that patch `requests.get` keep working unchanged.

**Temp/humidity fall back to Open-Meteo, not the cache.** When the PurpleAir reading comes back missing `Temp` or `Humidity` (the sensor sometimes drops them) `main()` calls `fetch_local_weather()` against Open-Meteo (free, no API key) using the optional `[weather] latitude/longitude` from `airquality.conf`. The fallback only fills the missing field — PM2.5/PM10 still come from PurpleAir. If the `[weather]` section is absent we just log and continue with `N/A`; we don't pull temp/humidity from the JSON cache, since stale weather is worse than no weather.

**Title bar city comes from `[display] city` in `airquality.conf`.** The e-ink header reads `Air Quality - <city>`, defaulting to `Campbell` when the section/key is absent or blank. Don't reintroduce a hardcoded city string — `display_air_quality()` takes `city` as a parameter and `main()` threads it through from `load_config()`.

**One JSON cache, used for both fallback rendering and trend detection.** The live run writes the full reading to `$AIRQUALITY_STATE_DIR/airquality/last_reading.json` (defaulting via `XDG_STATE_HOME`). On the next tick that same file is read for two purposes: computing the PM2.5 delta that drives the trend marker and the "AQI Rising!" banner, and — if the live fetch fails — feeding a `stale=True` render that shows "Air Quality [CACHED]". Writes go through a `.tmp` + `os.replace` to stay atomic. An older PM2.5-only text cache (`.last_pm25`) used to live in the repo root; don't reintroduce it, the cached display path needs the full PM10/Temp/Humidity payload.

**Trend marker vs. "AQI Rising!" banner use different rules.** The `+/-` next to PM2.5 shows `+` only when the current PM2.5 is strictly higher than the cached value, and `-` otherwise (including when the value held steady, fell, or no cached reading exists). The red "AQI Rising!" banner is stricter: it fires only when PM2.5 has climbed by at least `TREND_THRESHOLD` (5 µg/m³) since the cached reading. Tune `TREND_THRESHOLD` at the top of `airQuality.py` if the banner is too noisy or too quiet.

**Heartbeat file marks fully-successful runs.** On the live render path `main()` writes the current UTC ISO-8601 timestamp to `$AIRQUALITY_STATE_DIR/airquality/heartbeat` (atomic via `.tmp` + `os.replace`). It is **not** updated on the cache-fallback path, so an external monitor can alert when the file goes stale and catch a unit that's silently stuck rendering [CACHED]. The timer doesn't fire overnight (08:00–21:30 only), so any staleness alert needs to be scoped to the run window — see README for the recommended threshold.

**Cache-fallback runs still exit 1.** The systemd unit is `Type=oneshot` with **no `Restart=`** (the timer is the retry mechanism). A successful live render exits 0, anything that ends in `_render_cached_fallback` exits 1 — that's intentional so journalctl/monitoring can spot the outage. Don't add `Restart=on-failure`; it would relaunch every 30s on top of the 30-min timer tick.

**Post-render persistence errors are logged, not fatal.** Once `display_air_quality()` returns successfully, `main()` calls `write_cache()` and `write_heartbeat()` inside a `try/except OSError` — a disk-full or permissions error there must NOT downgrade the run to a cache-fallback render, because the user is already looking at fresh data. Keep this split (separate `_render_cached_fallback` helper) intact.

**`systemd/airquality.service.in` is a template, not an installable unit.** `deploy.sh` substitutes `@USER@`, `@GROUP@`, `@REPO_DIR@`, `@PYTHON@`, `@STATE_DIR@` and installs the rendered file to `/etc/systemd/system/airquality.service`. If you edit the unit, edit the `.in` template and re-run `deploy.sh` (or `sed` + `systemctl daemon-reload` manually). Don't hardcode `pi`/`/home/pi` — deploys run as any user. The unit is sandboxed (`ProtectSystem=strict`, `MemoryMax=128M`, `RestrictAddressFamilies=...`); `AF_NETLINK` is kept because sysfs-backed SPI/GPIO needs it.

**`waveshare_epd/` is vendored, read-only.** The files are copied from [waveshare/e-Paper](https://github.com/waveshare/e-Paper). Don't patch them locally — update by recopying from upstream and bumping the version table in `waveshare_epd/UPSTREAM.md`. Ruff and mypy are configured to skip this directory.

**`sys.path.insert(0, ...)` at the top of `airQuality.py` is load-bearing** — systemd runs the script from `WorkingDirectory` but with no package context, so the vendored `waveshare_epd` import needs the explicit path prepend. Don't remove it when tidying imports.

**`tests/conftest.py` stubs `waveshare_epd` in `sys.modules` before tests import `airQuality`.** The real `epdconfig` runs Pi/Jetson hardware detection at *its* import time and raises on a non-Pi host. The `FakeEPD` class records every method call so display-path tests can assert on the sequence and inject failures via `monkeypatch.setattr(FakeEPD, ...)`. If you add a new EPD method to `display_air_quality()`, add it to `FakeEPD` too.

## Files you'll touch most

- `airQuality.py` — the whole program
- `tests/` — pytest suite; `conftest.py` owns the waveshare stub, the rest mirror module names (`test_load_config.py`, `test_fetch_purpleair.py`, etc.)
- `systemd/airquality.service.in` — unit template (edit here, not the installed copy)
- `systemd/airquality.timer` — schedule (every 30 min, 08:00–21:30)
- `deploy.sh` — bootstrap on a fresh Pi
- `airquality.conf` — local, gitignored, holds the PurpleAir API key, sensor id, optional `[weather]` coords, and optional `[display] city`
- `pyproject.toml` — ruff/mypy/pytest config (line length 100, target py310, coverage floor 75%)
- `docs/generate_preview.py` — regenerates `docs/preview.png` after layout changes

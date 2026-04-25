# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-script Raspberry Pi air quality monitor. `airQuality.py` runs once per systemd timer tick, fetches a PurpleAir sensor via the PurpleAir API, renders the reading to a Waveshare 2.13" black/red e-ink display (`epd2in13b_V4`), and caches the full reading so the next tick can fall back if the fetch fails.

There is no build step and no package — `airQuality.py` is the entry point and everything else is supporting infrastructure. A small pytest suite under `tests/` covers the platform-independent code paths (AQI classification, config parsing, the PurpleAir HTTP client, and the JSON cache); GitHub Actions runs it on every push and pull request.

## Commands

Deploy / reinstall (creates `.venv/`, installs deps, validates config, renders and installs the systemd unit, enables the timer):
```bash
bash deploy.sh
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

Run the test suite (works on any machine — does not require Pi hardware libs):
```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Architecture notes worth knowing up front

**Config is loaded inside `main()`, not at import.** Historically it loaded at module scope, which meant a missing/invalid `airquality.conf` crashed before the cached-fallback path could run. If you refactor, keep `load_config()` inside `main()` and keep it raising `SystemExit` with a human-readable message.

**The e-ink panel must always be put to sleep.** `display_air_quality()` wraps the draw in `try/finally` so `epd.sleep()` runs even if drawing raises. Leaving the panel powered shortens its life. Any new display-side code must preserve this invariant.

**HTTP retry logic distinguishes 4xx from 5xx/network errors.** `fetch_purpleair_data()` only retries on timeouts, connection errors, and 5xx. A 401 (bad key) or 404 (bad sensor id) fails fast with a `RuntimeError` — don't widen this to retry all errors, it just delays the real failure by 30+ seconds.

**Temp/humidity fall back to Open-Meteo, not the cache.** When the PurpleAir reading comes back missing `Temp` or `Humidity` (the sensor sometimes drops them) `main()` calls `fetch_local_weather()` against Open-Meteo (free, no API key). Coords come from the optional `[weather] latitude/longitude` in `airquality.conf`, defaulting to Campbell, CA 95008 (`DEFAULT_LATITUDE`/`DEFAULT_LONGITUDE` at the top of `airQuality.py`) when the section is absent. The fallback only fills the missing field — PM2.5/PM10 still come from PurpleAir. We don't pull temp/humidity from the JSON cache: stale weather is worse than no weather.

**One JSON cache, used for both fallback rendering and trend detection.** The live run writes the full reading to `$AIRQUALITY_STATE_DIR/airquality/last_reading.json` (defaulting via `XDG_STATE_HOME`). On the next tick that same file is read for two purposes: computing the PM2.5 delta that drives the trend marker and the "AQI Rising!" banner, and — if the live fetch fails — feeding a `stale=True` render that shows "Air Quality [CACHED]". An older PM2.5-only text cache (`.last_pm25`) used to live in the repo root; don't reintroduce it, the cached display path needs the full PM10/Temp/Humidity payload.

**Trend marker vs. "AQI Rising!" banner use different rules.** The `+/-` next to PM2.5 shows `+` only when the current PM2.5 is strictly higher than the cached value, and `-` otherwise (including when the value held steady, fell, or no cached reading exists). The red "AQI Rising!" banner is stricter: it fires only when PM2.5 has climbed by at least `TREND_THRESHOLD` (5 µg/m³) since the cached reading. Tune `TREND_THRESHOLD` at the top of `airQuality.py` if the banner is too noisy or too quiet.

**`systemd/airquality.service.in` is a template, not an installable unit.** `deploy.sh` substitutes `@USER@`, `@GROUP@`, `@REPO_DIR@`, `@PYTHON@`, `@STATE_DIR@` and installs the rendered file to `/etc/systemd/system/airquality.service`. If you edit the unit, edit the `.in` template and re-run `deploy.sh` (or `sed` + `systemctl daemon-reload` manually). Don't hardcode `pi`/`/home/pi` — deploys run as any user.

**`waveshare_epd/` is vendored, read-only.** The files are copied from [waveshare/e-Paper](https://github.com/waveshare/e-Paper). Don't patch them locally — update by recopying from upstream and bumping the version table in `waveshare_epd/UPSTREAM.md`.

**`sys.path.insert(0, ...)` at the top of `airQuality.py` is load-bearing** — systemd runs the script from `WorkingDirectory` but with no package context, so the vendored `waveshare_epd` import needs the explicit path prepend. Don't remove it when tidying imports.

## Files you'll touch most

- `airQuality.py` — the whole program
- `systemd/airquality.service.in` — unit template (edit here, not the installed copy)
- `systemd/airquality.timer` — schedule (every 30 min, 08:00–21:30)
- `deploy.sh` — bootstrap on a fresh Pi
- `airquality.conf` — local, gitignored, holds the PurpleAir API key and sensor id

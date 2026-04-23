# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-script Raspberry Pi air quality monitor. `airQuality.py` runs once per systemd timer tick, fetches a PurpleAir sensor via the PurpleAir API, renders the reading to a Waveshare 2.13" black/red e-ink display (`epd2in13b_V4`), and caches the full reading so the next tick can fall back if the fetch fails.

There is no build step, no test suite, and no package — `airQuality.py` is the entry point and everything else is supporting infrastructure.

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

## Architecture notes worth knowing up front

**Config is loaded inside `main()`, not at import.** Historically it loaded at module scope, which meant a missing/invalid `airquality.conf` crashed before the cached-fallback path could run. If you refactor, keep `load_config()` inside `main()` and keep it raising `SystemExit` with a human-readable message.

**The e-ink panel must always be put to sleep.** `display_air_quality()` wraps the draw in `try/finally` so `epd.sleep()` runs even if drawing raises. Leaving the panel powered shortens its life. Any new display-side code must preserve this invariant.

**HTTP retry logic distinguishes 4xx from 5xx/network errors.** `fetch_purpleair_data()` only retries on timeouts, connection errors, and 5xx. A 401 (bad key) or 404 (bad sensor id) fails fast with a `RuntimeError` — don't widen this to retry all errors, it just delays the real failure by 30+ seconds.

**Two separate caches in the code, intentionally.** The live run writes the full reading JSON to `$AIRQUALITY_STATE_DIR/airquality/last_reading.json` (defaults via `XDG_STATE_HOME`). The fallback path reads the same file and displays it with `stale=True` so the header shows "Air Quality [CACHED]". Don't go back to the old PM2.5-only text cache — the cached display needs PM10/Temp/Humidity too.

**Trend arrow vs. "AQI Rising!" banner use different thresholds.** The `+/-` arrow flips on any change; the red "AQI Rising!" banner only fires when PM2.5 has climbed by at least `TREND_THRESHOLD` (5 µg/m³) since the cached reading. Tune `TREND_THRESHOLD` at the top of `airQuality.py` if the banner is too noisy/quiet.

**`systemd/airquality.service.in` is a template, not an installable unit.** `deploy.sh` substitutes `@USER@`, `@GROUP@`, `@REPO_DIR@`, `@PYTHON@`, `@STATE_DIR@` and installs the rendered file to `/etc/systemd/system/airquality.service`. If you edit the unit, edit the `.in` template and re-run `deploy.sh` (or `sed` + `systemctl daemon-reload` manually). Don't hardcode `pi`/`/home/pi` — deploys run as any user.

**`waveshare_epd/` is vendored, read-only.** The files are copied from [waveshare/e-Paper](https://github.com/waveshare/e-Paper). Don't patch them locally — update by recopying from upstream and bumping the version table in `waveshare_epd/UPSTREAM.md`.

**`sys.path.insert(0, ...)` at the top of `airQuality.py` is load-bearing** — systemd runs the script from `WorkingDirectory` but with no package context, so the vendored `waveshare_epd` import needs the explicit path prepend. Don't remove it when tidying imports.

## Files you'll touch most

- `airQuality.py` — the whole program
- `systemd/airquality.service.in` — unit template (edit here, not the installed copy)
- `systemd/airquality.timer` — schedule (every 30 min, 08:00–21:30)
- `deploy.sh` — bootstrap on a fresh Pi
- `airquality.conf` — local, gitignored, holds the PurpleAir API key and sensor id

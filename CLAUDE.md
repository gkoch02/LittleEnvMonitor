# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

A single-script Raspberry Pi air quality monitor. `airQuality.py` runs once per systemd timer tick, fetches a PurpleAir sensor, renders the reading to a Waveshare 2.13" black/red e-ink panel (`epd2in13b_V4`), and caches the reading so the next tick can fall back to it if the fetch fails. No build step, no package. The README covers features, config, and deployment; this file covers the rules for changing the code.

## Commands

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m mypy airQuality.py
python -m pytest                 # coverage floor is set in pyproject.toml

.venv/bin/python airQuality.py --dry-run [PATH]   # real fetch → PNG, no hardware, no state writes
AIRQUALITY_STATE_DIR=/tmp/aq .venv/bin/python airQuality.py
python docs/generate_preview.py  # refresh README previews after a layout change
bash deploy.sh [--check-api]     # on the Pi
```

## Rules

Each rule's reasoning lives in a comment next to the code it protects; read that before changing it.

**Startup and config**
- Call `load_config()` inside `main()`, not at import, and have it raise `SystemExit` with a readable message. That keeps a bad config from crashing before the cache-fallback path.
- A non-blank `PURPLEAIR_API_KEY` env var wins over the file. `deploy.sh` validates by calling `load_config()` itself, so don't reimplement config rules in shell.
- Don't hardcode the city (`[display] city`, default `Campbell`) or add themes outside `SUPPORTED_THEMES`.

**Display**
- Always put the panel to sleep (`try/finally` in `display_air_quality()`), and keep both SIGALRM fences (draw and sleep).
- Keep the Waveshare import lazy (inside `display_air_quality()`), and don't add a module-level `sys.path.insert`.
- Draw only in `_render_panel_images()`. The panel, `--dry-run`, and `docs/generate_preview.py` all go through it.
- A new font-only theme is a row in `_THEME_FONT_PATHS`. A new layout is a `_draw_<name>_body()` plus a dispatch branch.

**Data and failure handling**
- Retry only on network errors, 5xx, and 429 (`Retry-After` capped at `RETRY_AFTER_CAP_SEC`). Fail fast on other 4xx.
- AQI bands live in one table, `_PM25_AQI_BREAKPOINTS`. Change bands there, not in `classify_aqi()`.
- Treat a stale or untrustworthy PurpleAir `last_seen` exactly like a fetch failure.
- Temp/humidity fall back to Open-Meteo, never to the cache.
- Cache-fallback runs exit 1. Don't add `Restart=` to the unit; the timer is the retry mechanism.
- Post-render `write_cache()`/`write_heartbeat()` errors are logged, not fatal. Only fully successful live runs write the heartbeat.

**Repo layout**
- Edit `systemd/airquality.service.in` (a template rendered by `deploy.sh`), not an installed unit. Don't hardcode `pi` or `/home/pi`.
- `waveshare_epd/` is vendored and read-only. Update it by recopying from upstream and bumping `waveshare_epd/UPSTREAM.md`.
- `tests/conftest.py` stubs `waveshare_epd` with `FakeEPD`. If `display_air_quality()` starts calling a new EPD method, add it there too.

## Writing code, comments, and tests

- Explain a reason once, in a comment at the code it applies to. Don't repeat it in this file, test docstrings, or the README.
- Comments describe the code as it is now. Leave history, issue/PR numbers, and review references to git.
- A test must fail when the behavior its name or docstring describes breaks. Before adding one, check that no existing test already catches that regression.
- Put shared test setup in fixtures (`conftest.py` has `state_dir`, `seed_cache`, `mock_get`, `network_down`). Use `parametrize` for input permutations.
- Don't write tests just to raise coverage. If a branch can't be reached, delete it instead of testing it.

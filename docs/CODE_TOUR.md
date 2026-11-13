# A tour of the code

For anyone opening this repo for the first time. The README is the reference; this page is meant to be read once, top to bottom, and leaves you knowing how a PurpleAir reading gets onto the little red-and-black panel, and how to find your way around the one script that does it.

You don't need to know Python well to follow it. Where a piece of Python is quoted, the sentence around it says what it does.

## The big picture

Almost everything is in one file, `airQuality.py`. It isn't a program that stays running: a systemd timer (`systemd/airquality.timer`) starts it every half hour from 08:00 to 21:30, it fetches one reading, draws it, puts the panel to sleep and exits.

The rest of the repo supports it:

- `waveshare_epd/`: the panel maker's driver, copied in unchanged (`waveshare_epd/UPSTREAM.md` says from where). You never need to read it.
- `deploy.sh`: sets up a Pi in one go, including writing the systemd service from `systemd/airquality.service.in`.
- `fonts/`: the two typefaces the themes use.
- `docs/generate_preview.py`, `docs/make_banner.py`: make the README's pictures.
- `tests/`: the test suite.

## Words this code uses

| Word | Means |
|---|---|
| **PM2.5**, **PM10** | Fine and coarse particles in the air, in micrograms per cubic metre (µg/m³). PM2.5 is the one the AQI is worked out from |
| **AQI** | The US Air Quality Index, 0 to 500. Here it's calculated from PM2.5 by EPA's formula (`pm25_to_aqi`) |
| **breakpoints** | EPA's table of PM2.5 ranges and the AQI range each maps to, with its category. One table, `_PM25_AQI_BREAKPOINTS`, near the top of the script |
| **category** | The name for an AQI range: Good, Moderate, Unhealthy for Sensitive Groups (shown as **USG**), Unhealthy, Very Unhealthy, Hazardous |
| **PurpleAir** | The sensor and the web service the readings come from. It needs an API key and the sensor's number |
| **`last_seen`** | When the sensor last reported. A reading older than an hour (`FRESHNESS_THRESHOLD_SEC`) counts as a failure, not as fresh |
| **cache** | `last_reading.json`: the last good reading, saved after every successful run |
| **`[CACHED]`** | What the title bar says when the live fetch failed and the panel is showing the cached reading instead |
| **trend**, **rising** | Comparing this PM2.5 with the cached one: `+` or `-` beside it, and "AQI Rising!" in the title when it climbed by `TREND_THRESHOLD` (5 µg/m³) or more |
| **heartbeat** | A file holding the time of the last fully successful run, for an outside monitor to watch |
| **Open-Meteo** | A free weather service, used only to fill in temperature and humidity when the sensor stops reporting them |
| **EPD** | Electronic paper display: the panel. `epd2in13b_V4` is this model, 250×122 pixels |
| **black layer**, **red layer** | The panel draws two separate black-and-white pictures, one printed in black ink and one in red. Every drawing call goes to one or the other |
| **theme** | `default`, `minimal` or `fredoka`: the layout and typeface (`SUPPORTED_THEMES`) |
| **dry run** | `--dry-run`: fetch for real but save a PNG picture instead of touching the panel or the cache |

## Following one reading

Say the timer fires at 14:30. Here's the path, with the function at each step; all of them are in `airQuality.py`. To find one, search the file for `def` and the name, e.g. `def main(`.

**1. systemd starts the script.** `airquality.timer` starts `airquality.service`, which runs the script with the repo's `.venv` Python and tells it where to keep its files (`AIRQUALITY_STATE_DIR=/var/lib/airquality`).

**2. Read the settings.** `main()` calls `load_config()`, which reads `airquality.conf` next to the script: the PurpleAir key and sensor number, optional coordinates for the weather fallback, the city and the theme. Anything missing or wrong stops the run with a one-line message saying what.

**3. Fetch.** `fetch_purpleair_data()` asks PurpleAir for PM2.5, PM10, humidity, temperature and `last_seen`. A network error, a server error or "slow down" (429) is retried up to three times with a pause; a refused key or unknown sensor (any other 4xx) gives up at once, since retrying won't help.

**4. Is it fresh?** `_is_fresh()` checks `last_seen`. A sensor that has gone quiet still answers with its last value, so an old reading is treated exactly like a failed fetch.

**5. Fill gaps.** If temperature or humidity is missing and `[weather]` coordinates are set, `fetch_local_weather()` gets them from Open-Meteo. They're never taken from the cache: no number is better than an old one.

**6. Work it out.** Back in `main()`: read the cache for the previous PM2.5 to get the trend, then `pm25_to_aqi()` and `classify_aqi()` turn PM2.5 into the AQI and its category. `pm25_to_aqi` finds the breakpoint row the reading falls in and scales it into that row's AQI range:

```python
return round((aqi_hi - aqi_lo) / (pm_hi - pm_lo) * (c - pm_lo) + aqi_lo)
```

That is a straight line between the row's two ends: a PM2.5 halfway along its range gives an AQI halfway along its range.

**7. Draw.** `display_air_quality()` calls `_render_panel_images()`, which makes the black and red layers: the frame, the title bar (city, "AQI Rising!" or `[CACHED]`), the body for the theme (`_draw_default_body` or `_draw_minimal_body`), and the gauge and time along the bottom. All drawing is in that one function, so the panel, the dry run and the README pictures always match.

**8. Onto the panel.** Still in `display_air_quality()`: turn both layers upside down (the panel is mounted that way), then `epd.init()`, `epd.Clear()`, `epd.display(...)` through the Waveshare driver, and finally, whatever happened, `epd.sleep()`. Each step has a time limit (`_alarm`), so a stuck panel can't hang the Pi.

**9. Remember.** Only after the panel has been drawn: `write_cache()` saves the reading and `write_heartbeat()` the time. The log ends with a `summary path=live …` line and the script exits 0.

**If steps 3–8 fail**, `main()` catches the error, logs `Live fetch/display failed; trying cache` with the reason, and `_render_cached_fallback()` draws the cached reading marked `[CACHED]`, with the time it was taken and an empty gauge. That run exits 1 and leaves the heartbeat alone, so the log and any monitor can see the outage, while the panel still shows something useful.

## The files that matter

| File | One line |
|---|---|
| `airQuality.py` | Everything: settings, fetching, AQI, drawing, the panel, the cache |
| `airquality.conf.example` | Every setting, with comments; copied to `airquality.conf` on the Pi |
| `systemd/airquality.timer` | When it runs |
| `systemd/airquality.service.in` | How it runs (a template; `deploy.sh` fills in the user and paths) |
| `deploy.sh` | Setting up a Pi from scratch |

## What you can skip

- **`waveshare_epd/`**: the manufacturer's driver, copied in. It's never edited here.
- **`tests/`**: it exists to catch mistakes; ignore it until a test fails. `tests/conftest.py` stands in a fake panel, so the tests run on any computer.
- **The retry and time-limit details** (`_alarm`, the 429 handling): they make the script robust; they don't change what it shows.
- **`docs/*.py`**: picture-making for the README.

The code is more careful than a script this size usually is: time limits around every panel call, freshness checks, a test suite that must cover nearly every line. That's because it was written mostly by an AI, which rereads everything every time and benefits from tests that catch it drifting. A person can safely read around it.

## Finding things

From the repo folder:

```bash
grep -n "CACHED" airQuality.py             # where does this text appear?
grep -n "def classify_aqi" airQuality.py   # where is this function defined?
grep -rn "TREND_THRESHOLD" .               # every file that uses this name
```

`-n` shows line numbers, `-r` searches every file in a folder. In VS Code or another editor, Cmd-F finds within the file, "Find in Files" (Cmd-Shift-F) across the repo, and Cmd-clicking a function name jumps to where it's defined.

Every log line starts with the time and level, and the last line of each run is a `summary path=… pm25=… source=…` line: `live` (all good), `cache_fallback` (showing the old reading), `fail` (nothing to show at all) or `dry_run`.

## Reading a crash

When something goes wrong, Python prints a **traceback**: the chain of function calls that led to the error. On the Pi it's in `journalctl -u airquality.service`. This script catches nearly everything and falls back to the cache, so you'll usually see the traceback under a `Live fetch/display failed; trying cache` line. A made-up example, for a wrong API key:

```
ERROR Live fetch/display failed; trying cache
Traceback (most recent call last):
  File "/home/pi/LittleEnvMonitor/airQuality.py", line 725, in main
    data = fetch_purpleair_data(sensor_id, api_key)
  File "/home/pi/LittleEnvMonitor/airQuality.py", line 261, in fetch_purpleair_data
    raise RuntimeError(
RuntimeError: PurpleAir API returned 403: {"error": "ApiKeyInvalidError", ...}
```

Read it **from the bottom up**:

- The last line is the error, in words: PurpleAir refused the key (403).
- The line above it is the exact code that raised it, and the `File … line …` above that says where: `fetch_purpleair_data`.
- Everything higher up is how the program got there.

| Error | Usually means |
|---|---|
| `PurpleAir API returned 401/403` | The API key is wrong or was revoked |
| `PurpleAir API returned 404` | The sensor number is wrong |
| `StalePurpleAirDataError` | The sensor hasn't reported for over an hour: check its power and Wi-Fi |
| `ConnectionError`, `Timeout` | No network, or PurpleAir is down. It recovers by itself |
| `epd.init failed (SPI/GPIO unavailable)` | The panel can't be reached: SPI is off, the ribbon is loose, or another program has the GPIO pins (`GPIO busy`) |
| `TimeoutError` from `_alarm` | The panel stopped answering mid-draw |
| `Config file not found`, `Invalid config` | A settings problem; the message names the file and the field |
| `ModuleNotFoundError: No module named 'x'` | The Python environment is missing something; see `MAINTAINING.md` |

## Making a change

1. **Find the place** with the tables above, or `grep`.
2. **Change one thing.**
3. **Try it** without the panel. With the dev setup (`python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`), this draws a made-up reading of 42 µg/m³ to a picture, through the same drawing code the panel uses:

   ```bash
   .venv/bin/python -c 'import airQuality as a; a.render_preview_png({"PM2.5": 42.0, "PM10": 50, "Temp": 70, "Humidity": 40, "Time": "2:30 PM"}, False, "+", a.pm25_to_aqi(42.0), *a.classify_aqi(42.0), "Home", out_path="/tmp/aq.png", theme="default")'
   open /tmp/aq.png
   ```

   Change the numbers or `theme=` to see other cases. With a real `airquality.conf`, `.venv/bin/python airQuality.py --dry-run /tmp/aq.png` does the same with a live reading.
4. **Undo** if it's wrong: `git diff` shows what you changed, `git checkout -- <file>` puts the original back.

Then run the tests: `.venv/bin/python -m pytest` runs them all in a few seconds. For one file, add `--no-cov` (`.venv/bin/python -m pytest tests/test_render.py --no-cov`), since the coverage check only makes sense for the whole suite. There's a test file per area, named after it. If you changed the layout, `python docs/generate_preview.py` refreshes the README pictures.

`MAINTAINING.md` covers getting a change onto the Pi.

## Where to go next

| To understand | Read |
|---|---|
| What the panel shows and why, settings, the schedule, the heartbeat | `README.md` |
| The rules for changing the code | `CLAUDE.md` |
| Running it on a Pi | `MAINTAINING.md` |
| The vendored panel driver | `waveshare_epd/UPSTREAM.md` |

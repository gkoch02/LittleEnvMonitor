# Keeping Little Env Monitor running

A guide to running the air quality panel day to day, with nothing but a terminal and a text editor: checking it's healthy, changing its settings, updating, recovering when something breaks, and making small code changes safely.

`README.md` is the full reference. This page only tells you which of it you need, and when. The paths below are the ones `deploy.sh` sets up; `systemctl cat airquality.service` shows the ones on your Pi.

## What's where

The panel is a Raspberry Pi with a systemd **timer** that runs the script every half hour from 08:00 to 21:30. Each run fetches one reading, draws it, puts the panel to sleep and exits. Nothing runs overnight.

| Thing | Where on the Pi | Touch it? |
|---|---|---|
| The code (a copy of this GitHub repo) | where you cloned it, e.g. `~/LittleEnvMonitor` | Only through `git pull`, or small tweaks (see the last section) |
| Its Python environment | `.venv/` inside the code folder | Rebuild it if it breaks (see "Things that will break eventually") |
| **Your settings**, including the PurpleAir key | `airquality.conf` in the code folder | Yes, this is the file you edit |
| The last good reading | `/var/lib/airquality/airquality/last_reading.json` | No; it's rewritten every successful run |
| The time of the last successful run | `/var/lib/airquality/airquality/heartbeat` | Read only |
| The service and timer | `/etc/systemd/system/airquality.service`, `airquality.timer` | Rarely; `deploy.sh` writes them |

The panel HAT takes the Pi's display connector, so this needs a Pi of its own. Everything below starts with logging in to the Pi from your Mac (`ssh pi@<the Pi>`, or the shortcut in your `~/.ssh/config`) and `cd ~/LittleEnvMonitor`.

## Is it OK?

```bash
systemctl list-timers airquality.timer
journalctl -u airquality.service --since today --no-pager | grep summary
```

The first shows when it last ran and when it runs next. The second shows one line per run today; the word after `path=` says how it went:

| `path=` | Means |
|---|---|
| `live` | All good: a fresh reading is on the panel |
| `cache_fallback` | The fetch failed; the panel shows the last good reading marked `[CACHED]`. Fine once in a while; worrying if it's every run |
| `fail` | The fetch failed and there was no usable cached reading, so the panel wasn't redrawn |

`systemctl status airquality.service` says `inactive (dead)` between runs, which is expected for a job that runs and exits. After a `cache_fallback` run it says `failed`; that's the script reporting the outage on purpose, and the next run clears it.

To run it now and watch:

```bash
sudo systemctl start airquality.service
journalctl -u airquality.service -n 30 --no-pager
```

## Changing settings (no code)

All the choices live in one file. The recipe is always the same:

```bash
cp airquality.conf airquality.conf.bak-$(date +%Y%m%d)                                   # 1. back it up
nano airquality.conf                                                                     # 2. edit
.venv/bin/python -c 'import sys, airQuality; airQuality.load_config(sys.argv[1]); print("config OK")' airquality.conf   # 3. check it
sudo systemctl start airquality.service                                                  # 4. run it now
journalctl -u airquality.service -n 5 --no-pager                                         # 5. check it worked
```

Step 3 prints `config OK`, or a message naming the problem (`Invalid theme 'fancy' …`, `Set a real api_key …`). A file the reader can't parse at all, such as a section header missing its `]`, gives a short Python error instead; restore the backup if you can't see it. The check doesn't notice a misspelled setting *name* (`thme = minimal`): that line is just ignored and the default used, so if a change seems to have no effect, check the spelling against `airquality.conf.example`.

The settings, all in `airquality.conf.example` with comments:

| Section, setting | What it does |
|---|---|
| `[purpleair]` `api_key` | Your PurpleAir read key. Required. Keep this file private: `deploy.sh` sets it to be readable only by you |
| `[purpleair]` `sensor_id` | The sensor's number, from the PurpleAir map. Required |
| `[weather]` `latitude`, `longitude` | Where to get temperature and humidity when the sensor stops reporting them. Leave the section out to show `N/A` instead |
| `[display]` `city` | The name in the title bar. Leave it blank for just "Air Quality" |
| `[display]` `theme` | `default`, `minimal` or `fredoka`; the README shows each |

The schedule (every half hour, 08:00 to 21:30) isn't a setting: it's in `systemd/airquality.timer`. To change it, edit that file in the repo, then `sudo cp systemd/airquality.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart airquality.timer`.

**To undo**, copy your backup back: `cp airquality.conf.bak-YYYYMMDD airquality.conf`.

## Updating

```bash
cd ~/LittleEnvMonitor
git pull --ff-only origin main
.venv/bin/python -m pip install -r requirements.txt
sudo systemctl start airquality.service
journalctl -u airquality.service -n 5 --no-pager
```

The `pip install` step brings the libraries up to what the new code expects; it's quick when nothing changed. The timer picks up the new code by itself on its next run. If the update changed anything in `systemd/`, run `bash deploy.sh` again to reinstall the service; it keeps your settings.

**To go back to the version that worked**: this repo has no release tags, so use the commit list. `git log --oneline -10` shows the last ten changes, newest first; pick the one before the update, then `git checkout <its short code>` and run the service as above. `git checkout main` and the update steps put you back on the latest.

## When it stops working

| What you see | Try |
|---|---|
| Panel stuck on an old reading, no `[CACHED]` | The timer isn't running: `systemctl list-timers airquality.timer`. `sudo systemctl enable --now airquality.timer` starts it |
| `[CACHED]` on the panel every time | The fetch is failing. `journalctl -u airquality.service -n 40` shows why; `docs/CODE_TOUR.md`, "Reading a crash", lists the usual errors |
| `PurpleAir API returned 401` or `403` | The API key is wrong or was revoked: get a new read key from PurpleAir and put it in the settings |
| `StalePurpleAirDataError` | The sensor itself has stopped reporting: check its power and Wi-Fi |
| Temperature or humidity shows `N/A` | The sensor stopped sending them and `[weather]` isn't set (or Open-Meteo didn't answer) |
| `epd.init failed` or `GPIO busy` | The Pi can't reach the panel: SPI off (`sudo raspi-config nonint get_spi` prints `0` when it's on), the ribbon loose, or another program using the display pins. A reboot clears a stuck pin |
| Fails after a Pi system update | See "Things that will break eventually" |
| Times are an hour off | The Pi's time zone: `timedatectl` shows it, `sudo timedatectl set-timezone America/Los_Angeles` (your zone) fixes it |
| Can't log in to the Pi | Its network address changed; your router's device list shows the new one. Update `~/.ssh/config` on the Mac |
| Pi won't boot at all | Probably the SD card. See "Rebuilding from scratch" |

## Back up now, while it works

There's very little to keep: your settings file, which holds the API key. From a Mac terminal:

```bash
mkdir -p ~/Backups/LittleEnvMonitor
scp 'pi@<the Pi>:LittleEnvMonitor/airquality.conf' ~/Backups/LittleEnvMonitor/
```

The cached reading isn't worth keeping; the first run after a rebuild makes a new one. The backup holds your PurpleAir key, so keep it somewhere private.

## Rebuilding from scratch

For a dead SD card or a new Pi. Allow half an hour.

1. Flash Raspberry Pi OS Lite onto a card with Raspberry Pi Imager on the Mac. In its settings, set the username, your Wi-Fi, and turn on SSH.
2. Log in, then get the code:

   ```bash
   sudo apt update && sudo apt install -y git
   git clone https://github.com/gkoch02/LittleEnvMonitor.git ~/LittleEnvMonitor
   ```

3. Put your settings back before the first run, from the Mac:

   ```bash
   scp ~/Backups/LittleEnvMonitor/airquality.conf 'pi@<the Pi>:LittleEnvMonitor/'
   ```

4. Install, back on the Pi. With the settings already in place, `deploy.sh` checks them instead of asking you to fill them in:

   ```bash
   cd ~/LittleEnvMonitor
   bash deploy.sh --check-api
   ```

   `--check-api` also tries the key against PurpleAir once. The script ends with a test run and its log. If it says SPI was just enabled, `sudo reboot` and the next half-hour run will draw.

## Things that will break eventually

Left alone, the Pi will run for years. What breaks it is change:

- **A big Raspberry Pi OS upgrade** (a new Debian version) usually brings a new Python, which strands the Python environment. Symptom: every run fails with `No module named` or `python: not found`. Fix: rebuild it, which `deploy.sh` does when the environment is missing:

  ```bash
  cd ~/LittleEnvMonitor
  rm -rf .venv
  bash deploy.sh
  ```

  Routine `sudo apt update && sudo apt upgrade` is safe; it's the jump between major versions that does this. Simplest of all: don't do major upgrades on an appliance that works.

- **PurpleAir** changes its rules now and then: keys, plans, how many requests are free. The panel shows `[CACHED]` and the log names the error.

- **The GPIO libraries** (`RPi.GPIO`, `spidev`) occasionally lag behind a new Pi OS or Pi model. The panel driver in `waveshare_epd/` is a fixed copy, so it only changes when someone copies in a newer one.

- **The SD card** wears out. A spare card and the backup above make this a short job.

## Small code changes

Settings cover most wishes. When they don't, [`docs/CODE_TOUR.md`](docs/CODE_TOUR.md) explains how the script works, and small edits are within reach without knowing Python well, as long as you keep to one change at a time and keep git's safety net.

**The safety net.** On the Pi, in `~/LittleEnvMonitor`:

- `git status` lists files you've changed (your `airquality.conf` never shows; git is told to ignore it).
- `git diff` shows exactly what you changed.
- `git checkout -- <file>` throws your change to that file away and puts the original back.

**Trying a change without touching the panel.** On the Mac, in your copy of the repo, `docs/CODE_TOUR.md`, "Making a change", has a one-line command that draws a made-up reading to a picture with the same code the panel uses.

**Where common things live** (all in `airQuality.py`, near the top):

| To change | Look in |
|---|---|
| How much PM2.5 has to rise for "AQI Rising!" | `TREND_THRESHOLD` |
| How old a reading may be before it counts as stale | `FRESHNESS_THRESHOLD_SEC` |
| The AQI bands, category names and which ones are red | `_PM25_AQI_BREAKPOINTS` |
| The short category labels under the number | `_CATEGORY_SHORT` |
| A theme's typeface | `_THEME_FONT_PATHS` |

**Getting it onto the Pi.** The quick way is to make the same edit on the Pi itself (`nano ~/LittleEnvMonitor/airQuality.py`); the next run uses it. It stays until the next `git pull`, which will refuse to run while your edit is there: `git diff > ~/my-change.patch` saves it, `git checkout -- airQuality.py` clears it, and after the pull `git apply ~/my-change.patch` puts it back (if the file hasn't changed underneath it).

The lasting way is to commit it in the repo on GitHub (on a branch, then a pull request), and `git pull` on the Pi. The tests on GitHub will tell you if the change broke something.

**Leave alone:**

- `waveshare_epd/`: the panel maker's driver, copied in unchanged.
- `/etc/systemd/system/airquality.service`: it's generated from `systemd/airquality.service.in` by `deploy.sh`; edit the template and re-run the script instead.

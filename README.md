# Little Env Monitor

An air quality monitor for a Raspberry Pi Zero driving a [Waveshare 2.13" black/red e-ink display (V4)](https://www.waveshare.com/wiki/2.13inch_e-Paper_HAT_%28E%29_Manual).

Pulls PM2.5, PM10, temperature, and humidity from a [PurpleAir](https://www2.purpleair.com) sensor via the PurpleAir API, classifies the AQI, and renders it to the display every 30 minutes. If the live fetch fails, it falls back to the last cached reading.

## Hardware

- Raspberry Pi Zero (or any Pi with SPI)
- Waveshare 2.13" e-Paper HAT V4 — black **and red** ink (epd2in13b_V4)
- A PurpleAir outdoor sensor (any model with API access)

## Display layout

- **Header (red):** "Air Quality - Campbell", or "AQI Rising!" if PM2.5 increased since last reading
- **Body (black):** PM2.5 with trend arrow, PM10, AQI category, temperature/humidity
- **AQI category (red):** when Unhealthy or worse
- **Timestamp (red, bottom-right):** time of last update

## Rebuilding from scratch

```bash
cd /home/pi
git clone https://github.com/gkoch02/LittleEnvMonitor.git
cd LittleEnvMonitor
bash deploy.sh
```

The deploy script installs dependencies, enables SPI, prompts you to fill in `airquality.conf`, then installs and starts the systemd timer.

> **Note:** If SPI wasn't already enabled, you may need to reboot before the display responds.

## Configuration

Copy the example config and fill in your credentials:

```bash
cp airquality.conf.example airquality.conf
nano airquality.conf
```

```ini
[purpleair]
api_key = YOUR_PURPLEAIR_API_KEY
sensor_id = YOUR_SENSOR_ID
```

`airquality.conf` is gitignored — it will never be committed.

Your PurpleAir API key is available at [api.purpleair.com](https://api.purpleair.com). Your sensor ID appears in the PurpleAir map URL when you click your sensor.

## Schedule

Runs every 30 minutes between 8:00 AM and 9:30 PM via a systemd timer. To trigger a manual run:

```bash
sudo systemctl start airquality.service
journalctl -u airquality.service -f
```

## Files

| File | Purpose |
|------|---------|
| `airQuality.py` | Main script — fetches data, classifies AQI, drives display |
| `airquality.conf.example` | Config template (copy to `airquality.conf` and fill in) |
| `deploy.sh` | One-shot deploy script for fresh Pi setup |
| `requirements.txt` | Python dependencies |
| `systemd/airquality.service` | systemd oneshot service unit |
| `systemd/airquality.timer` | systemd timer (every 30 min, 8 AM–9:30 PM) |
| `waveshare_epd/` | Waveshare e-Paper Python library (MIT, from [Waveshare's e-Paper repo](https://github.com/waveshare/e-Paper)) |

## License

Project code: MIT. Waveshare library files in `waveshare_epd/` are copyright Waveshare, also MIT licensed.

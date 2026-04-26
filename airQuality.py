import configparser
import functools
import json
import logging
import os
import signal
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import requests
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from waveshare_epd import epd2in13b_V4

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("airquality")

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
CONF_PATH = os.path.join(REPO_DIR, "airquality.conf")
STATE_DIR = os.environ.get(
    "AIRQUALITY_STATE_DIR",
    os.environ.get("XDG_STATE_HOME", os.path.join(os.path.expanduser("~"), ".local", "state")),
)
CACHE_PATH = os.path.join(STATE_DIR, "airquality", "last_reading.json")
HEARTBEAT_PATH = os.path.join(STATE_DIR, "airquality", "heartbeat")

FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

USER_AGENT = "LittleEnvMonitor/1.0"

# PM2.5 µg/m³ change required before flagging "AQI Rising!"
TREND_THRESHOLD = 5.0

# Hard ceiling on the e-ink draw call — the vendored busy-wait has no timeout
# of its own, so we fence it here to stay inside systemd's TimeoutStartSec.
DISPLAY_TIMEOUT_SEC = 60
# Separate budget for epd.sleep() so a stuck shutdown can't leak past the unit.
SLEEP_TIMEOUT_SEC = 10
# Cap any Retry-After the server hands us; a 5-minute hint would blow the
# 120s systemd TimeoutStartSec before we ever reached the cache fallback.
RETRY_AFTER_CAP_SEC = 30


def load_config(path):
    if not os.path.isfile(path):
        raise SystemExit(
            f"Config file not found: {path}\n"
            f"Copy airquality.conf.example to airquality.conf and fill in your credentials."
        )
    parser = configparser.ConfigParser()
    parser.read(path)
    try:
        # Env var wins over the config file so the systemd unit can ship the
        # secret via EnvironmentFile= (mode 0600) instead of the repo dir.
        # Strip the env var first so a whitespace-only value falls back to
        # the file rather than clobbering it.
        env_key = (os.environ.get("PURPLEAIR_API_KEY") or "").strip()
        api_key = env_key or parser["purpleair"]["api_key"].strip()
        sensor_id = int(parser["purpleair"]["sensor_id"])
    except (KeyError, ValueError) as e:
        raise SystemExit(f"Invalid config at {path}: {e}") from e
    if not api_key or api_key == "YOUR_PURPLEAIR_API_KEY":
        raise SystemExit(f"Set a real api_key in {path} or PURPLEAIR_API_KEY")
    if sensor_id <= 0:
        raise SystemExit(f"Invalid sensor_id in {path}: must be a positive integer")

    weather_coords = None
    if parser.has_section("weather"):
        try:
            lat = float(parser["weather"]["latitude"])
            lon = float(parser["weather"]["longitude"])
        except (KeyError, ValueError) as e:
            raise SystemExit(f"Invalid [weather] section in {path}: {e}") from e
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise SystemExit(
                f"Invalid [weather] coordinates in {path}: "
                f"latitude must be in [-90, 90] and longitude in [-180, 180]"
            )
        weather_coords = (lat, lon)

    city = parser.get("display", "city", fallback="Campbell").strip() or "Campbell"

    return api_key, sensor_id, weather_coords, city


@functools.lru_cache(maxsize=1)
def _http_session():
    """Module-level requests.Session, reused across PurpleAir + Open-Meteo.

    Saves a TLS handshake per call — meaningful on a Pi Zero. Lazily built so
    `import airQuality` stays cheap and so tests that patch `requests.get` keep
    working unchanged.
    """
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


@functools.lru_cache(maxsize=8)
def _load_font(size):
    """Cache TrueType fonts at module level — they're identical every render."""
    try:
        return ImageFont.truetype(FONT_PATH_BOLD, size)
    except OSError:
        log.warning("Font %s missing; falling back to PIL default", FONT_PATH_BOLD)
        return ImageFont.load_default()


def classify_aqi(pm25):
    if pm25 <= 12:
        return "Good", "black"
    if pm25 <= 35.4:
        return "Moderate", "black"
    if pm25 <= 55.4:
        return "Unhealthy for Sensitive Groups", "red"
    if pm25 <= 150.4:
        return "Unhealthy", "red"
    if pm25 <= 250.4:
        return "Very Unhealthy", "red"
    return "Hazardous", "red"


def fetch_purpleair_data(sensor_id, api_key, retries=3, timeout=15):
    if retries < 1:
        raise ValueError(f"retries must be >= 1, got {retries}")
    url = f"https://api.purpleair.com/v1/sensors/{sensor_id}"
    headers = {"X-API-Key": api_key}
    fields = ["pm2.5", "pm10.0", "humidity", "temperature", "last_seen"]
    full_url = f"{url}?fields={','.join(fields)}"

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        retry_after = None
        try:
            response = _http_session().get(full_url, headers=headers, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            log.warning("Attempt %d/%d network error: %s", attempt, retries, e)
        else:
            # Don't retry client errors (bad key, bad sensor id) — they won't fix themselves.
            # 429 is the one 4xx exception: it's a transient rate limit, so respect Retry-After.
            if response.status_code == 429:
                last_err = RuntimeError("HTTP 429 rate limited")
                try:
                    # Spec allows an HTTP-date here too; we only handle the
                    # integer-seconds form and fall through to backoff otherwise.
                    parsed = int(response.headers.get("Retry-After", "0"))
                    retry_after = min(parsed, RETRY_AFTER_CAP_SEC) or None
                except ValueError:
                    retry_after = None
                log.warning(
                    "Attempt %d/%d rate limited (Retry-After=%s)",
                    attempt, retries, retry_after,
                )
            elif 400 <= response.status_code < 500:
                raise RuntimeError(
                    f"PurpleAir API returned {response.status_code}: {response.text[:200]}"
                )
            elif response.status_code >= 500:
                last_err = RuntimeError(f"HTTP {response.status_code}")
                log.warning("Attempt %d/%d server error: %s", attempt, retries, last_err)
            else:
                sensor_data = response.json()["sensor"]
                last_seen = sensor_data.get("last_seen")
                return {
                    "PM2.5": sensor_data.get("pm2.5", "N/A"),
                    "PM10": sensor_data.get("pm10.0", "N/A"),
                    "Temp": sensor_data.get("temperature", "N/A"),
                    "Humidity": sensor_data.get("humidity", "N/A"),
                    "Time": (
                        datetime.fromtimestamp(last_seen).strftime("%-I:%M %p")
                        if last_seen
                        else "N/A"
                    ),
                }
        if attempt < retries:
            # Backoff between attempts: 2/4/8s (cap 8s). With retries=3 the
            # total wait is 2+4 = 6s; the 8s case only kicks in for retries>=4.
            # 429 honors Retry-After when present (capped above).
            sleep_for = retry_after if retry_after is not None else min(2 ** attempt, 8)
            time.sleep(sleep_for)
    # `retries >= 1` is enforced above, so the loop ran at least once and
    # last_err was set on every non-success branch.
    assert last_err is not None
    raise last_err


def fetch_local_weather(latitude, longitude, timeout=10):
    """Fetch current temp (°F) and humidity (%) from Open-Meteo as a PurpleAir fallback.

    Open-Meteo is free and requires no API key. Missing fields come back as "N/A"
    so the caller can keep the same shape as `fetch_purpleair_data`.
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&current=temperature_2m,relative_humidity_2m"
        "&temperature_unit=fahrenheit"
    )
    response = _http_session().get(url, timeout=timeout)
    response.raise_for_status()
    current = response.json().get("current") or {}
    temp = current.get("temperature_2m")
    humidity = current.get("relative_humidity_2m")
    return {
        "Temp": round(temp) if isinstance(temp, (int, float)) else "N/A",
        "Humidity": round(humidity) if isinstance(humidity, (int, float)) else "N/A",
    }


def _is_missing(value):
    return value is None or value == "N/A"


@contextmanager
def _alarm(seconds):
    """SIGALRM-based timeout fence around a blocking call.

    The vendored waveshare busy-wait has no timeout of its own, so this is the
    one knob that keeps a stuck panel from eating the whole 120s systemd budget.
    POSIX-only — fine for the systemd unit.
    """
    def _handler(signum, frame):
        raise TimeoutError(f"timed out after {seconds}s")

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def write_cache(data):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, CACHE_PATH)


def read_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_heartbeat():
    """Atomically write the current UTC time to the heartbeat file.

    Only called on the fully-successful path so external monitors can tell
    a healthy unit from one that is silently stuck in cache fallback.
    """
    os.makedirs(os.path.dirname(HEARTBEAT_PATH), exist_ok=True)
    tmp = HEARTBEAT_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())
    os.replace(tmp, HEARTBEAT_PATH)


def display_air_quality(data, alert, trend_symbol, category, cat_color, city, stale=False):
    # Two alarms because SIGALRM is one-shot: once it fires (or is cancelled by
    # the with-exit), epd.sleep() in the finally would no longer be fenced.
    # The second alarm keeps the panel-sleep invariant honest even when the
    # main draw timed out — every blocking SPI/busy-wait path stays bounded.
    epd = epd2in13b_V4.EPD()
    try:
        with _alarm(DISPLAY_TIMEOUT_SEC):
            # Vendored waveshare returns -1 from init() on SPI/GPIO failure
            # rather than raising — surface it explicitly so the cache-fallback
            # branch in main() can take over.
            if epd.init() == -1:
                raise RuntimeError("epd.init failed (SPI/GPIO unavailable)")
            epd.Clear()

            font_large = _load_font(18)
            font_small = _load_font(16)
            font_xsmall = _load_font(12)

            width, height = epd.height, epd.width
            image_black = Image.new("1", (width, height), 255)
            image_red = Image.new("1", (width, height), 255)
            draw_black = ImageDraw.Draw(image_black)
            draw_red = ImageDraw.Draw(image_red)

            draw_red.rectangle((5, 5, width - 5, height - 5), outline=0, width=3)
            draw_black.rectangle((3, 3, width - 3, height - 3), outline=0, width=3)

            if stale:
                draw_red.text((10, 10), "Air Quality [CACHED]", font=font_large, fill=0)
            elif alert:
                draw_red.text((10, 10), "AQI Rising!", font=font_large, fill=0)
            else:
                draw_red.text((10, 10), f"Air Quality - {city}", font=font_large, fill=0)

            y_offset = 40
            spacing = 18
            draw_black.line(
                [(10, y_offset - 4), (width - 10, y_offset - 4)], fill=0, width=1
            )
            draw_black.text(
                (10, y_offset),
                f"PM2.5: {data['PM2.5']} µg/m³  {trend_symbol}",
                font=font_small,
                fill=0,
            )
            draw_black.text(
                (10, y_offset + spacing),
                f"PM10:  {data['PM10']} µg/m³",
                font=font_small,
                fill=0,
            )
            draw_black.text(
                (10, y_offset + 3 * spacing),
                f"T/H:   {data['Temp']} °F / {data['Humidity']}%",
                font=font_small,
                fill=0,
            )

            aqi_y = y_offset + 2 * spacing
            aqi_text = f"AQI: {category}"
            if cat_color == "red":
                draw_red.text((10, aqi_y), aqi_text, font=font_small, fill=0)
            else:
                draw_black.text((10, aqi_y), aqi_text, font=font_small, fill=0)

            timestamp = datetime.now().strftime("%I:%M%p").lstrip("0").lower()
            bbox = font_xsmall.getbbox(timestamp)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = width - text_width - 10
            y = height - text_height - 12
            draw_red.text((x, y), timestamp, font=font_xsmall, fill=0)

            image_black = image_black.rotate(180)
            image_red = image_red.rotate(180)

            epd.display(epd.getbuffer(image_black), epd.getbuffer(image_red))
    finally:
        # Always sleep the panel; leaving it powered shortens its life.
        # Fresh alarm because the outer one may have already fired or expired.
        try:
            with _alarm(SLEEP_TIMEOUT_SEC):
                epd.sleep()
        except Exception:
            log.exception("Failed to put e-ink panel to sleep")


def _summary(branch, pm25=None, rising=None, source=None):
    log.info(
        "summary path=%s pm25=%s rising=%s source=%s",
        branch, pm25, rising, source,
    )


def _render_cached_fallback(city, source):
    """Render the previous reading marked [CACHED]. Always returns exit code 1.

    Split out so the live path's persistence errors (write_cache/write_heartbeat)
    don't accidentally trigger a stale render on top of a successful display.
    """
    cached = read_cache()
    if not cached:
        _summary("fail", source=source)
        return 1
    try:
        pm25 = float(cached["PM2.5"])
    except (KeyError, TypeError, ValueError):
        log.error("Cached reading is unusable")
        _summary("fail", source=source)
        return 1
    category, cat_color = classify_aqi(pm25)
    try:
        display_air_quality(cached, False, "?", category, cat_color, city, stale=True)
    except Exception:
        log.exception("Failed to display cached data")
    _summary("cache_fallback", pm25=pm25, source=source)
    return 1


def main():
    api_key, sensor_id, weather_coords, city = load_config(CONF_PATH)
    source = "purpleair"
    try:
        data = fetch_purpleair_data(sensor_id, api_key)
        if _is_missing(data["Temp"]) or _is_missing(data["Humidity"]):
            if weather_coords is not None:
                try:
                    weather = fetch_local_weather(*weather_coords)
                    if _is_missing(data["Temp"]):
                        data["Temp"] = weather["Temp"]
                    if _is_missing(data["Humidity"]):
                        data["Humidity"] = weather["Humidity"]
                    source = "purpleair+openmeteo"
                except Exception:
                    log.exception("Local weather fallback failed")
            else:
                log.info(
                    "PurpleAir missing temp/humidity but no [weather] coords configured"
                )
        current_pm25 = float(data["PM2.5"])
        cached = read_cache()
        last_pm25 = None
        if cached is not None:
            try:
                last_pm25 = float(cached.get("PM2.5"))
            except (TypeError, ValueError):
                last_pm25 = None
        rising = last_pm25 is not None and (current_pm25 - last_pm25) >= TREND_THRESHOLD
        trend_symbol = "+" if last_pm25 is not None and current_pm25 > last_pm25 else "-"
        category, cat_color = classify_aqi(current_pm25)
        display_air_quality(data, rising, trend_symbol, category, cat_color, city)
    except Exception:
        log.exception("Live fetch/display failed; trying cache")
        return _render_cached_fallback(city, source)

    # Display succeeded. Persistence failures here shouldn't downgrade the run
    # to a cache-fallback render — the user's already looking at fresh data.
    try:
        write_cache(data)
        write_heartbeat()
    except OSError:
        log.exception("Failed to persist cache/heartbeat after successful render")
    _summary("live", pm25=current_pm25, rising=rising, source=source)
    return 0


if __name__ == "__main__":
    sys.exit(main())

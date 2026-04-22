import requests
import configparser
import time
import json
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import logging
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from waveshare_epd import epd2in13b_V4

# Configure logging
logging.basicConfig(level=logging.INFO)

# Load config
_config = configparser.ConfigParser()
_config.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'airquality.conf'))
API_KEY = _config['purpleair']['api_key']
SENSOR_ID = int(_config['purpleair']['sensor_id'])
LAST_PM25_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_pm25")

# Fonts
FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
font_large = ImageFont.truetype(FONT_PATH_BOLD, 18)
font_small = ImageFont.truetype(FONT_PATH_BOLD, 16)
font_xsmall = ImageFont.truetype(FONT_PATH_BOLD, 12)

# AQI Category function with color indicator
def classify_aqi(pm25):
    if pm25 <= 12:
        return "Good", "black"
    elif pm25 <= 35.4:
        return "Moderate", "black"
    elif pm25 <= 55.4:
        return "Unhealthy for Sensitive Groups", "red"
    elif pm25 <= 150.4:
        return "Unhealthy", "red"
    elif pm25 <= 250.4:
        return "Very Unhealthy", "red"
    else:
        return "Hazardous", "red"

# Fetch with retry
def fetch_purpleair_data(sensor_id, api_key, retries=3, delay=10, timeout=15):
    url = f"https://api.purpleair.com/v1/sensors/{sensor_id}"
    headers = {"X-API-Key": api_key}
    fields = ["pm2.5", "pm10.0", "humidity", "temperature", "last_seen"]
    full_url = url + f"?fields={','.join(fields)}"
    last_err = None
    for attempt in range(retries):
        try:
            response = requests.get(full_url, headers=headers, timeout=timeout)
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")
            sensor_data = response.json()["sensor"]
            return {
                "PM2.5": sensor_data.get("pm2.5", "N/A"),
                "PM10": sensor_data.get("pm10.0", "N/A"),
                "Temp": sensor_data.get("temperature", "N/A"),
                "Humidity": sensor_data.get("humidity", "N/A"),
                "Time": datetime.fromtimestamp(sensor_data.get("last_seen")).strftime('%-I:%M %p')
            }
        except Exception as e:
            last_err = e
            print(f"{datetime.now()} - Attempt {attempt+1}/{retries} failed: {e}", flush=True)
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_err

# Read last PM2.5 value
def read_last_pm25():
    try:
        with open(LAST_PM25_FILE, "r") as f:
            return float(f.read().strip())
    except:
        return None

# Write current PM2.5 value
def write_last_pm25(value):
    with open(LAST_PM25_FILE, "w") as f:
        f.write(str(value))

# Load cached data for fallback display
def load_cache():
    try:
        with open(LAST_PM25_FILE, "r") as f:
            pm25 = float(f.read().strip())
        return {"PM2.5": pm25, "PM10": "N/A", "Temp": "N/A", "Humidity": "N/A", "Time": "cached"}
    except Exception:
        return None

# Draw to e-ink
def display_air_quality(data, alert, trend_symbol, category, cat_color, stale=False):
    epd = epd2in13b_V4.EPD()
    epd.init()
    epd.Clear()

    width, height = epd.height, epd.width
    image_black = Image.new('1', (width, height), 255)
    image_red = Image.new('1', (width, height), 255)
    draw_black = ImageDraw.Draw(image_black)
    draw_red = ImageDraw.Draw(image_red)

    draw_red.rectangle((5, 5, width - 5, height - 5), outline=0, width=3)
    draw_black.rectangle((3, 3, width - 3, height - 3), outline=0, width=3)

    if stale:
        draw_red.text((10, 10), "Air Quality [CACHED]", font=font_large, fill=0)
    elif alert:
        draw_red.text((10, 10), "AQI Rising!", font=font_large, fill=0)
    else:
        draw_red.text((10, 10), "Air Quality - Campbell", font=font_large, fill=0)

    y_offset = 40
    spacing = 18
    draw_black.line([(10, y_offset - 4), (width - 10, y_offset - 4)], fill=0, width=1)
    draw_black.text((10, y_offset), f"PM2.5: {data['PM2.5']} µg/m³  {trend_symbol}", font=font_small, fill=0)
    draw_black.text((10, y_offset + spacing), f"PM10:  {data['PM10']} µg/m³", font=font_small, fill=0)
    draw_black.text((10, y_offset + 3 * spacing), f"T/H:   {data['Temp']} °F / {data['Humidity']}%", font=font_small, fill=0)

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

    # Rotate both images 180 degrees
    image_black = image_black.rotate(180)
    image_red = image_red.rotate(180)

    epd.display(epd.getbuffer(image_black), epd.getbuffer(image_red))
    epd.sleep()

if __name__ == "__main__":
    try:
        data = fetch_purpleair_data(SENSOR_ID, API_KEY)
        current_pm25 = float(data["PM2.5"])
        last_pm25 = read_last_pm25()
        alert = last_pm25 is not None and current_pm25 > last_pm25
        trend_symbol = "+" if alert else "-"
        category, cat_color = classify_aqi(current_pm25)
        display_air_quality(data, alert, trend_symbol, category, cat_color)
        write_last_pm25(current_pm25)
    except Exception as e:
        print(f"{datetime.now()} - All retries failed: {e}", flush=True)
        logging.error("Failed to fetch live data, trying cache", exc_info=True)
        cached = load_cache()
        if cached:
            pm25 = float(cached["PM2.5"])
            category, cat_color = classify_aqi(pm25)
            try:
                display_air_quality(cached, False, "?", category, cat_color, stale=True)
            except Exception as disp_err:
                logging.error("Failed to display cached data", exc_info=True)
        sys.exit(1)

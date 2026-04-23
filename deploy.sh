#!/bin/bash
# Deploy LittleEnvMonitor on a fresh Raspberry Pi.
# Run from the repo root: bash deploy.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
RUN_GROUP="$(id -gn "$RUN_USER")"
STATE_DIR="/var/lib/airquality"
VENV_DIR="$REPO_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

echo "==> Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-venv python3-pip fonts-dejavu-core

echo "==> Creating Python virtualenv at $VENV_DIR..."
if [ ! -x "$VENV_PYTHON" ]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$REPO_DIR/requirements.txt"

echo "==> Enabling SPI (requires reboot if not already enabled)..."
if ! lsmod | grep -q spi_bcm2835; then
    if command -v raspi-config >/dev/null 2>&1; then
        sudo raspi-config nonint do_spi 0
        echo "    SPI enabled — you may need to reboot before the display works."
    else
        echo "    raspi-config not found; enable SPI manually if the display does not respond."
    fi
fi

echo "==> Checking config..."
if [ ! -f "$REPO_DIR/airquality.conf" ]; then
    cp "$REPO_DIR/airquality.conf.example" "$REPO_DIR/airquality.conf"
    echo ""
    echo "  !! Created airquality.conf from example."
    echo "  !! Edit it now and add your PurpleAir API key and sensor ID:"
    echo "  !!   nano $REPO_DIR/airquality.conf"
    echo ""
    read -r -p "Press Enter once you've saved the config to continue..."
fi

# Validate config has real values before installing the timer.
if ! "$VENV_PYTHON" - "$REPO_DIR/airquality.conf" <<'PY'
import configparser, sys
parser = configparser.ConfigParser()
parser.read(sys.argv[1])
try:
    api_key = parser["purpleair"]["api_key"].strip()
    sensor_id = parser["purpleair"]["sensor_id"].strip()
except KeyError as e:
    sys.exit(f"missing key: {e}")
if not api_key or api_key == "YOUR_PURPLEAIR_API_KEY":
    sys.exit("api_key is not set")
if not sensor_id or sensor_id == "YOUR_SENSOR_ID":
    sys.exit("sensor_id is not set")
try:
    int(sensor_id)
except ValueError:
    sys.exit("sensor_id must be an integer")
PY
then
    echo "    airquality.conf is invalid — fix it and re-run deploy.sh." >&2
    exit 1
fi

echo "==> Preparing state directory $STATE_DIR..."
sudo install -d -o "$RUN_USER" -g "$RUN_GROUP" -m 0755 "$STATE_DIR"

echo "==> Rendering and installing systemd units..."
RENDERED="$(mktemp)"
trap 'rm -f "$RENDERED"' EXIT
sed \
    -e "s|@USER@|$RUN_USER|g" \
    -e "s|@GROUP@|$RUN_GROUP|g" \
    -e "s|@REPO_DIR@|$REPO_DIR|g" \
    -e "s|@PYTHON@|$VENV_PYTHON|g" \
    -e "s|@STATE_DIR@|$STATE_DIR|g" \
    "$REPO_DIR/systemd/airquality.service.in" > "$RENDERED"
sudo install -m 0644 "$RENDERED" /etc/systemd/system/airquality.service
sudo install -m 0644 "$REPO_DIR/systemd/airquality.timer" /etc/systemd/system/airquality.timer
sudo systemctl daemon-reload
sudo systemctl enable --now airquality.timer

echo ""
echo "Done. Timer status:"
systemctl status airquality.timer --no-pager || true
echo ""
echo "To trigger a manual run: sudo systemctl start airquality.service"
echo "To watch logs:           journalctl -u airquality.service -f"

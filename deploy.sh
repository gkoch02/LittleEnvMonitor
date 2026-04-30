#!/bin/bash
# Deploy LittleEnvMonitor on a fresh Raspberry Pi.
# Run from the repo root: bash deploy.sh [--check-api]
#
#   --check-api   After validating the config, hit the PurpleAir API once to
#                 confirm the key and sensor_id actually work. Skipped by
#                 default so offline installs still succeed.
set -euo pipefail

CHECK_API=0
for arg in "$@"; do
    case "$arg" in
        --check-api) CHECK_API=1 ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
RUN_GROUP="$(id -gn "$RUN_USER")"
STATE_DIR="/var/lib/airquality"
VENV_DIR="$REPO_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
CONF_PATH="$REPO_DIR/airquality.conf"

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
if [ ! -f "$CONF_PATH" ]; then
    cp "$REPO_DIR/airquality.conf.example" "$CONF_PATH"
    echo ""
    echo "  !! Created airquality.conf from example."
    echo "  !! Edit it now and add your PurpleAir API key and sensor ID:"
    echo "  !!   nano $CONF_PATH"
    echo ""
    read -r -p "Press Enter once you've saved the config to continue..."
fi

# Tighten permissions before validation so we never leave a world-readable
# secret behind, even if validation fails.
chmod 600 "$CONF_PATH"

# Validate config has real values before installing the timer. Mirrors the
# runtime load_config() rules: PURPLEAIR_API_KEY env var wins over the file,
# and sensor_id must be a positive integer.
if ! "$VENV_PYTHON" - "$CONF_PATH" <<'PY'
import configparser, os, sys
parser = configparser.ConfigParser()
parser.read(sys.argv[1])
try:
    file_key = parser["purpleair"]["api_key"].strip()
    sensor_id = parser["purpleair"]["sensor_id"].strip()
except KeyError as e:
    sys.exit(f"missing key: {e}")
env_key = (os.environ.get("PURPLEAIR_API_KEY") or "").strip()
api_key = env_key or file_key
if not api_key or api_key == "YOUR_PURPLEAIR_API_KEY":
    sys.exit("api_key is not set (in airquality.conf or PURPLEAIR_API_KEY)")
if not sensor_id or sensor_id == "YOUR_SENSOR_ID":
    sys.exit("sensor_id is not set")
try:
    sid = int(sensor_id)
except ValueError:
    sys.exit("sensor_id must be an integer")
if sid <= 0:
    sys.exit("sensor_id must be a positive integer")
PY
then
    echo "    airquality.conf is invalid — fix it and re-run deploy.sh." >&2
    exit 1
fi

if [ "$CHECK_API" -eq 1 ]; then
    echo "==> Smoke-testing PurpleAir API..."
    # Prefer the env var so the placeholder-in-file + EnvironmentFile workflow
    # still gets a real connectivity check.
    API_KEY="${PURPLEAIR_API_KEY:-$(awk -F'= *' '/^api_key/ {print $2; exit}' "$CONF_PATH")}"
    SENSOR_ID="$(awk -F'= *' '/^sensor_id/ {print $2; exit}' "$CONF_PATH")"
    if ! curl -fsS \
            -H "X-API-Key: $API_KEY" \
            "https://api.purpleair.com/v1/sensors/$SENSOR_ID?fields=pm2.5" \
            -o /dev/null
    then
        echo "    PurpleAir API rejected the key/sensor pair — fix the config and retry." >&2
        exit 1
    fi
    echo "    OK"
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

echo "==> Triggering an initial run to verify the install..."
# Type=oneshot, so `systemctl start` blocks until the service exits. We don't
# bail on a non-zero exit here: a transient PurpleAir failure or a freshly
# enabled SPI bus that needs a reboot would surface as Result=exit-code, and
# the timer will retry on the next tick. Surface the outcome + recent journal
# lines so the operator can tell which case they're in.
sudo systemctl start airquality.service || true
RESULT="$(systemctl show airquality.service --property=Result --value 2>/dev/null || echo unknown)"
EXIT_CODE="$(systemctl show airquality.service --property=ExecMainStatus --value 2>/dev/null || echo '?')"
case "$RESULT" in
    success)
        echo "    Initial run OK (Result=success, ExecMainStatus=$EXIT_CODE)."
        ;;
    *)
        echo "    Initial run did not finish cleanly (Result=$RESULT, ExecMainStatus=$EXIT_CODE)."
        echo "    Common causes: SPI was just enabled and needs a reboot; PurpleAir is briefly unreachable;"
        echo "    the e-ink ribbon is loose. The timer will retry every 30 minutes."
        ;;
esac
echo ""
echo "Recent service log:"
journalctl -u airquality.service --no-pager -n 20 || true

echo ""
echo "Done. Timer status:"
systemctl status airquality.timer --no-pager || true
echo ""
echo "To trigger a manual run: sudo systemctl start airquality.service"
echo "To watch logs:           journalctl -u airquality.service -f"
echo "To preview without hardware: $VENV_PYTHON $REPO_DIR/airQuality.py --dry-run /tmp/preview.png"

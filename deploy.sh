#!/bin/bash
# Deploy LittleEnvMonitor on a fresh Raspberry Pi.
# Run from the repo root: bash deploy.sh
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3-pip fonts-dejavu-core

echo "==> Installing Python dependencies..."
pip3 install -r "$REPO_DIR/requirements.txt"

echo "==> Enabling SPI (requires reboot if not already enabled)..."
if ! lsmod | grep -q spi_bcm2835; then
    sudo raspi-config nonint do_spi 0
    echo "    SPI enabled — you may need to reboot before the display works."
fi

echo "==> Checking config..."
if [ ! -f "$REPO_DIR/airquality.conf" ]; then
    cp "$REPO_DIR/airquality.conf.example" "$REPO_DIR/airquality.conf"
    echo ""
    echo "  !! Created airquality.conf from example."
    echo "  !! Edit it now and add your PurpleAir API key and sensor ID:"
    echo "  !!   nano $REPO_DIR/airquality.conf"
    echo ""
    read -p "Press Enter once you've saved the config to continue..."
fi

echo "==> Installing systemd units..."
sudo cp "$REPO_DIR/systemd/airquality.service" /etc/systemd/system/
sudo cp "$REPO_DIR/systemd/airquality.timer"   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now airquality.timer

echo ""
echo "Done. Timer status:"
systemctl status airquality.timer --no-pager
echo ""
echo "To trigger a manual run: sudo systemctl start airquality.service"
echo "To watch logs:           journalctl -u airquality.service -f"

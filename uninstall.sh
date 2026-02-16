#!/bin/bash
# Uninstallation script for Video Converter Daemon

set -euo pipefail

echo "=== Video Converter Daemon Uninstallation ==="
echo ""

# Ensure running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root"
    echo "Usage: sudo ./uninstall.sh"
    exit 1
fi

# Confirm uninstallation
echo "WARNING: This will uninstall the Video Converter Daemon"
echo ""
read -p "Are you sure? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Cancelled"
    exit 0
fi

# Stop the service
echo ""
echo "Stopping service..."
if systemctl is-active --quiet video-converter 2>/dev/null; then
    systemctl stop video-converter
    echo "[OK] Service stopped"
fi

# Disable the service
echo "Disabling service..."
if systemctl is-enabled --quiet video-converter 2>/dev/null; then
    systemctl disable video-converter
    echo "[OK] Service disabled"
fi

# Remove systemd service file
echo "Removing systemd service file..."
if [ -f /etc/systemd/system/video-converter.service ]; then
    rm /etc/systemd/system/video-converter.service
    systemctl daemon-reload
    echo "[OK] Service file removed"
fi

# Remove daemon binary
echo "Removing daemon binary..."
if [ -f /usr/local/bin/video_converter_daemon.py ]; then
    rm /usr/local/bin/video_converter_daemon.py
    echo "[OK] Daemon binary removed"
fi

# Remove management script
echo "Removing management script..."
if [ -f /usr/local/bin/video-converter-manage ]; then
    rm /usr/local/bin/video-converter-manage
    echo "[OK] Management script removed"
fi

# Ask about keeping configuration and state
echo ""
read -p "Keep configuration and state files? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    # Remove config
    if [ -d /etc/video-converter ]; then
        echo "Removing configuration directory..."
        rm -rf /etc/video-converter
        echo "[OK] Configuration removed"
    fi

    # Remove state and work directories
    if [ -d /var/lib/video-converter ]; then
        echo "Removing state and work directories..."
        rm -rf /var/lib/video-converter
        echo "[OK] State and work directories removed"
    fi

    # Remove logs
    if [ -d /var/log/video-converter ]; then
        echo "Removing log directory..."
        rm -rf /var/log/video-converter
        echo "[OK] Log directory removed"
    fi
else
    echo ""
    echo "Configuration and state files preserved at:"
    echo "  Config: /etc/video-converter/"
    echo "  State: /var/lib/video-converter/"
    echo "  Logs: /var/log/video-converter/"
fi

echo ""
echo "=== Uninstallation Complete ==="
echo ""
echo "Video Converter Daemon has been uninstalled."
echo ""

if [ -d /etc/video-converter ] || [ -d /var/lib/video-converter ]; then
    echo "To completely remove remaining files later, run:"
    echo "  sudo rm -rf /etc/video-converter /var/lib/video-converter /var/log/video-converter"
fi

#!/bin/bash
# Video Converter Daemon Management Script

set -euo pipefail

SERVICE_NAME="video-converter"
CONFIG_FILE="/etc/video-converter/config.yaml"
SYSTEMCTL_CMD="sudo systemctl"
JOURNALCTL_CMD="sudo journalctl"

show_usage() {
    echo "Video Converter Daemon Manager"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  start       Start the daemon"
    echo "  stop        Stop the daemon"
    echo "  restart     Restart the daemon"
    echo "  status      Show daemon status"
    echo "  logs        Show recent logs (last 50 lines)"
    echo "  follow      Follow logs in real-time"
    echo "  enable      Enable daemon to start on boot"
    echo "  disable     Disable daemon auto-start"
    echo "  stats       Show conversion statistics"
    echo "  pending     Show pending files to convert by directory"
    echo "  reset       Reset processed files database"
    echo "  test        Test run (manual mode, FHS paths)"
    echo "  config      Edit configuration"
    echo ""
}

show_stats() {
    echo "=== Conversion Statistics ==="
    echo ""

    # Use system service paths
    STATE_DIR="/var/lib/video-converter"

    # Count processed files
    if [ -f "$STATE_DIR/processed.json" ]; then
        PROCESSED_COUNT=$(jq '. | length' "$STATE_DIR/processed.json" 2>/dev/null || echo "0")
        echo "Total files processed: $PROCESSED_COUNT"
        echo ""
        echo "Recent conversions:"
        $JOURNALCTL_CMD -u "$SERVICE_NAME" | grep "Successfully converted" | tail -5 || echo "(none yet)"
    else
        echo "No processed files database found at $STATE_DIR/processed.json"
    fi

    echo ""
    echo "=== Current Status ==="
    $SYSTEMCTL_CMD status "$SERVICE_NAME" --no-pager | grep -E "(Active:|Tasks:|Memory:|CPU:)" || echo "Service inactive or not available"
}

show_pending() {
    echo "=== Pending Files to Convert ==="
    echo ""

    # Get config file
    CONFIG_FILE="/etc/video-converter/config.yaml"
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "ERROR: Config file not found at $CONFIG_FILE"
        return 1
    fi

    # Load processed files
    STATE_DIR="/var/lib/video-converter"
    PROCESSED_FILE="$STATE_DIR/processed.json"

    # Get processed hashes
    if [ -f "$PROCESSED_FILE" ]; then
        PROCESSED_HASHES=$(jq -r '.[]' "$PROCESSED_FILE" 2>/dev/null || echo "")
    else
        PROCESSED_HASHES=""
    fi

    # Parse config and scan directories
    python3 << 'PYTHON_EOF'
import yaml
import json
import os
import hashlib
from pathlib import Path
from collections import defaultdict

config_file = "/etc/video-converter/config.yaml"
processed_file = "/var/lib/video-converter/processed.json"

try:
    with open(config_file) as f:
        config = yaml.safe_load(f)
except Exception as e:
    print(f"ERROR: Failed to load config: {e}")
    exit(1)

# Load processed hashes
processed = set()
if os.path.exists(processed_file):
    try:
        with open(processed_file) as f:
            processed = set(json.load(f))
    except:
        pass

# Scan directories
extensions = set(config['processing']['include_extensions'])
exclude_patterns = config['processing']['exclude_patterns']
directories = config['directories']

pending_by_dir = defaultdict(int)
total_pending = 0

for directory in directories:
    dir_path = Path(directory)
    if not dir_path.exists():
        print(f"[SKIP] {directory}: Directory not found")
        continue

    dir_pending = 0
    try:
        for ext in extensions:
            pattern = f"**/*.{ext}"
            for video_file in dir_path.glob(pattern):
                if not video_file.is_file():
                    continue

                # Check exclude patterns
                should_exclude = False
                for exclude_pattern in exclude_patterns:
                    if video_file.match(exclude_pattern):
                        should_exclude = True
                        break

                if should_exclude:
                    continue

                # Check if already processed
                file_hash = hashlib.sha256(str(video_file).encode()).hexdigest()
                if file_hash not in processed:
                    # Check if output exists
                    output_path = video_file.with_suffix('.m4v')
                    if not output_path.exists() or output_path == video_file:
                        dir_pending += 1
                        total_pending += 1

    except Exception as e:
        print(f"[ERROR] {directory}: {e}")

    if dir_pending > 0:
        pending_by_dir[directory] = dir_pending
    elif dir_path.exists():
        pending_by_dir[directory] = 0

# Display results
if pending_by_dir:
    for directory in sorted(pending_by_dir.keys()):
        count = pending_by_dir[directory]
        if count > 0:
            print(f"  {directory}: {count} file(s)")
        else:
            print(f"  {directory}: 0 files")

    print()
    print(f"Total pending: {total_pending} file(s)")
else:
    print("No directories configured")
PYTHON_EOF
}

case "${1:-}" in
    start)
        echo "Starting service..."
        $SYSTEMCTL_CMD start "$SERVICE_NAME"
        sleep 1
        $SYSTEMCTL_CMD status "$SERVICE_NAME" --no-pager
        ;;

    stop)
        echo "Stopping service..."
        $SYSTEMCTL_CMD stop "$SERVICE_NAME"
        ;;

    restart)
        echo "Restarting service..."
        $SYSTEMCTL_CMD restart "$SERVICE_NAME"
        sleep 1
        $SYSTEMCTL_CMD status "$SERVICE_NAME" --no-pager
        ;;

    status)
        $SYSTEMCTL_CMD status "$SERVICE_NAME" --no-pager
        ;;

    logs)
        $JOURNALCTL_CMD -u "$SERVICE_NAME" -n 50 --no-pager
        ;;

    follow)
        echo "Following logs (Ctrl+C to stop)..."
        $JOURNALCTL_CMD -u "$SERVICE_NAME" -f
        ;;

    enable)
        echo "Enabling service..."
        $SYSTEMCTL_CMD enable "$SERVICE_NAME"
        echo "Service will start automatically on boot"
        ;;

    disable)
        echo "Disabling service..."
        $SYSTEMCTL_CMD disable "$SERVICE_NAME"
        echo "Service will not start automatically on boot"
        ;;

    stats)
        show_stats
        ;;

    pending)
        show_pending
        ;;

    reset)
        echo "WARNING: This will reset the processed files database."
        echo "All files will be considered unprocessed and may be re-converted."
        read -p "Are you sure? (yes/no): " CONFIRM
        if [ "$CONFIRM" = "yes" ]; then
            STATE_DIR="/var/lib/video-converter"
            sudo rm -f "$STATE_DIR/processed.json"
            echo "Database reset complete"
            echo "Restarting service..."
            $SYSTEMCTL_CMD restart "$SERVICE_NAME"
        else
            echo "Cancelled"
        fi
        ;;

    test)
        echo "Running in test mode (Ctrl+C to stop)..."
        # Use FHS paths for test
        CONFIG_PATH="/etc/video-converter/config.yaml"
        if [ ! -f "$CONFIG_PATH" ]; then
            echo "ERROR: Config file not found at $CONFIG_PATH"
            echo "Install the daemon first with: sudo ./install.sh"
            exit 1
        fi
        sudo /usr/local/bin/video_converter_daemon.py --config "$CONFIG_PATH" --dry-run
        ;;

    config)
        EDITOR="${EDITOR:-nano}"
        echo "Opening configuration file..."
        sudo "$EDITOR" "$CONFIG_FILE"
        read -p "Restart service to apply changes? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            $SYSTEMCTL_CMD restart "$SERVICE_NAME"
            echo "Service restarted"
        fi
        ;;

    *)
        show_usage
        exit 1
        ;;
esac

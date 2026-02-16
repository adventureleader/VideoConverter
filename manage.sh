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

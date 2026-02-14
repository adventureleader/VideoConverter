#!/bin/bash
# Video Converter Daemon Management Script

SERVICE_NAME="video-converter"
CONFIG_FILE="config.yaml"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if using system or user service
if systemctl list-units --full --all | grep -q "^$SERVICE_NAME.service"; then
    SERVICE_TYPE="system"
    SYSTEMCTL_CMD="sudo systemctl"
    JOURNALCTL_CMD="sudo journalctl"
else
    SERVICE_TYPE="user"
    SYSTEMCTL_CMD="systemctl --user"
    JOURNALCTL_CMD="journalctl --user"
fi

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
    echo "  test        Test run (manual mode)"
    echo "  config      Edit configuration"
    echo ""
}

show_stats() {
    echo "=== Conversion Statistics ==="
    echo ""

    # Count processed files
    if [ -f /tmp/video_converter/processed.json ]; then
        PROCESSED_COUNT=$(jq '. | length' /tmp/video_converter/processed.json 2>/dev/null || echo "0")
        echo "Total files processed: $PROCESSED_COUNT"
        echo ""
        echo "Recent conversions:"
        $JOURNALCTL_CMD -u $SERVICE_NAME | grep "Successfully converted" | tail -5
    else
        echo "No processed files database found"
    fi

    echo ""
    echo "=== Current Status ==="
    $SYSTEMCTL_CMD status $SERVICE_NAME --no-pager | grep -E "(Active:|Tasks:|Memory:|CPU:)"
}

case "$1" in
    start)
        echo "Starting $SERVICE_TYPE service..."
        $SYSTEMCTL_CMD start $SERVICE_NAME
        sleep 1
        $SYSTEMCTL_CMD status $SERVICE_NAME --no-pager
        ;;

    stop)
        echo "Stopping $SERVICE_TYPE service..."
        $SYSTEMCTL_CMD stop $SERVICE_NAME
        ;;

    restart)
        echo "Restarting $SERVICE_TYPE service..."
        $SYSTEMCTL_CMD restart $SERVICE_NAME
        sleep 1
        $SYSTEMCTL_CMD status $SERVICE_NAME --no-pager
        ;;

    status)
        $SYSTEMCTL_CMD status $SERVICE_NAME --no-pager
        ;;

    logs)
        $JOURNALCTL_CMD -u $SERVICE_NAME -n 50 --no-pager
        ;;

    follow)
        echo "Following logs (Ctrl+C to stop)..."
        $JOURNALCTL_CMD -u $SERVICE_NAME -f
        ;;

    enable)
        echo "Enabling $SERVICE_TYPE service..."
        $SYSTEMCTL_CMD enable $SERVICE_NAME
        echo "Service will start automatically on boot"
        ;;

    disable)
        echo "Disabling $SERVICE_TYPE service..."
        $SYSTEMCTL_CMD disable $SERVICE_NAME
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
            rm -f /tmp/video_converter/processed.json
            echo "Database reset complete"
        else
            echo "Cancelled"
        fi
        ;;

    test)
        echo "Running in test mode (Ctrl+C to stop)..."
        cd "$SCRIPT_DIR"
        python3 video_converter_daemon.py config.yaml
        ;;

    config)
        ${EDITOR:-nano} "$SCRIPT_DIR/$CONFIG_FILE"
        read -p "Restart service to apply changes? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            $SYSTEMCTL_CMD restart $SERVICE_NAME
            echo "Service restarted"
        fi
        ;;

    *)
        show_usage
        exit 1
        ;;
esac

#!/bin/bash
# Installation script for Video Converter Daemon

# Security: Exit on error, undefined variables, and pipe failures
set -euo pipefail

# Security: Set a safe umask for all created files/directories
umask 0027

echo "=== Video Converter Daemon Installation ==="
echo ""

# Check if running as root for system installation
if [ "$EUID" -eq 0 ]; then
    SYSTEM_INSTALL=true
    echo "Running as root - will install as system service"
else
    SYSTEM_INSTALL=false
    echo "Running as user - will install as user service"
fi

# Get the script directory (safely)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Security: Verify expected files exist (prevent running from wrong directory)
if [ ! -f "$SCRIPT_DIR/video_converter_daemon.py" ] || [ ! -f "$SCRIPT_DIR/config.yaml" ]; then
    echo "ERROR: Required files not found in $SCRIPT_DIR"
    echo "       Ensure video_converter_daemon.py and config.yaml exist."
    exit 1
fi

# Check dependencies
echo ""
echo "Checking dependencies..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 is not installed"
    exit 1
fi
echo "[OK] Python 3 found: $(python3 --version)"

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "WARNING: ffmpeg is not installed"
    echo "Please install ffmpeg: sudo apt install ffmpeg"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "[OK] FFmpeg found: $(ffmpeg -version | head -n1)"
fi


# Install Python dependencies
echo ""
echo "Installing Python dependencies..."

# Try system package first (recommended for newer Ubuntu/Debian)
if ! python3 -c "import yaml" 2>/dev/null; then
    echo "PyYAML not found, attempting to install..."

    # Try system package first
    if command -v apt &> /dev/null; then
        echo "Installing via apt (recommended)..."
        sudo apt install -y python3-yaml
    else
        # Fallback to pip with --break-system-packages for externally-managed environments
        echo "Installing via pip..."
        pip3 install --user --break-system-packages PyYAML || pip3 install --user PyYAML
    fi
else
    echo "[OK] PyYAML already installed"
fi

# Determine the service user for system installs
if [ "$SYSTEM_INSTALL" = true ]; then
    # Security: Create a dedicated unprivileged system user instead of using
    # a hardcoded UID. Using a fixed UID like 125 is fragile and may collide
    # with existing users/services on different systems.
    SERVICE_USER="videoconverter"
    if ! id "$SERVICE_USER" &>/dev/null; then
        echo "Creating dedicated service user: $SERVICE_USER"
        # Check if group exists; if so, use it, otherwise create user+group
        if getent group "$SERVICE_USER" &>/dev/null; then
            useradd --system --no-create-home --shell /usr/sbin/nologin -g "$SERVICE_USER" "$SERVICE_USER"
        else
            useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
        fi
    else
        echo "[OK] Service user '$SERVICE_USER' already exists"
    fi
fi

# Create log directory
echo ""
echo "Creating log directory..."
if [ "$SYSTEM_INSTALL" = true ]; then
    mkdir -p /var/log/video-converter
    chown "$SERVICE_USER":"$SERVICE_USER" /var/log/video-converter
    # Security: Restrict log directory permissions (owner rwx, group rx, others none)
    chmod 750 /var/log/video-converter
    # Also create work directory for system service
    # Security: Use a directory under /var/lib instead of /tmp to avoid
    # /tmp-based symlink attacks and tmpwatch cleanup issues
    mkdir -p /var/lib/video-converter/work
    chown "$SERVICE_USER":"$SERVICE_USER" /var/lib/video-converter/work
    # Security: Restrict work directory permissions
    chmod 700 /var/lib/video-converter/work
else
    mkdir -p ~/.local/var/log/video-converter
    chmod 750 ~/.local/var/log/video-converter
    # Create user work directory outside of /tmp
    mkdir -p ~/.local/var/lib/video-converter/work
    chmod 700 ~/.local/var/lib/video-converter/work
    # Update config to use user directories
    sed -i "s|/var/log/video-converter|$HOME/.local/var/log/video-converter|g" config.yaml
    sed -i "s|/tmp/video_converter|$HOME/.local/var/lib/video-converter/work|g" config.yaml
fi

# Make daemon script executable (owner and group only)
chmod 750 video_converter_daemon.py

# Security: Restrict config file permissions (may contain sensitive paths)
chmod 640 config.yaml

# Configure the service
echo ""
echo "Configuring systemd service..."

# Security: Use mktemp for the temporary service file instead of a predictable path
TEMP_SERVICE_FILE="$(mktemp /tmp/video-converter.service.XXXXXX)"
# Security: Ensure temp file is cleaned up on exit
trap "rm -f '$TEMP_SERVICE_FILE'" EXIT

# Create service file with correct paths
if [ "$SYSTEM_INSTALL" = true ]; then
    # System service
    cat > "$TEMP_SERVICE_FILE" <<EOF
[Unit]
Description=Video Converter Daemon
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/video_converter_daemon.py $SCRIPT_DIR/config.yaml
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

# Environment
Environment="PATH=/usr/local/bin:/usr/bin:/bin"

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes

# Allow read-write to specific directories only
ReadWritePaths=/var/log/video-converter /var/lib/video-converter

# Resource limits to prevent runaway processes
LimitNOFILE=4096
MemoryMax=4G
CPUQuota=80%

[Install]
WantedBy=multi-user.target
EOF
    # Security: Set restrictive permissions on the service file
    chmod 644 "$TEMP_SERVICE_FILE"
    mv "$TEMP_SERVICE_FILE" /etc/systemd/system/video-converter.service
    systemctl daemon-reload
    echo "[OK] System service installed"
    echo ""
    echo "To enable and start the service:"
    echo "  sudo systemctl enable video-converter"
    echo "  sudo systemctl start video-converter"
    echo ""
    echo "To check status:"
    echo "  sudo systemctl status video-converter"
    echo "  sudo journalctl -u video-converter -f"
else
    # User service
    cat > "$TEMP_SERVICE_FILE" <<EOF
[Unit]
Description=Video Converter Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/video_converter_daemon.py $SCRIPT_DIR/config.yaml
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

# Environment
Environment="PATH=/usr/local/bin:/usr/bin:/bin"

# Security hardening (user service subset)
NoNewPrivileges=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes

[Install]
WantedBy=default.target
EOF
    mkdir -p ~/.config/systemd/user
    chmod 644 "$TEMP_SERVICE_FILE"
    mv "$TEMP_SERVICE_FILE" ~/.config/systemd/user/video-converter.service
    systemctl --user daemon-reload
    echo "[OK] User service installed"
    echo ""
    echo "To enable and start the service:"
    echo "  systemctl --user enable video-converter"
    echo "  systemctl --user start video-converter"
    echo ""
    echo "To check status:"
    echo "  systemctl --user status video-converter"
    echo "  journalctl --user -u video-converter -f"
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "IMPORTANT: Before starting the service, edit config.yaml to:"
echo "  1. Set the correct directories on nas01 to scan"
echo "  2. Adjust conversion quality settings if needed"
echo "  3. Configure other options as desired"
echo ""
echo "Configuration file: $SCRIPT_DIR/config.yaml"

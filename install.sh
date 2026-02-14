#!/bin/bash
# Installation script for Video Converter Daemon

# Security: Exit on error, undefined variables, and pipe failures
set -euo pipefail

# Security: Set a safe umask for all created files/directories
umask 0027

echo "=== Video Converter Daemon Installation ==="
echo ""

# Ensure running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root"
    echo "Usage: sudo ./install.sh"
    exit 1
fi

SYSTEM_INSTALL=true
echo "Running as root - installing system service"

# Get the script directory (safely)
SOURCE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SOURCE_DIR"

# Security: Verify expected files exist (prevent running from wrong directory)
if [ ! -f "$SOURCE_DIR/video_converter_daemon.py" ] || [ ! -f "$SOURCE_DIR/config.yaml" ]; then
    echo "ERROR: Required files not found in $SOURCE_DIR"
    echo "       Ensure video_converter_daemon.py and config.yaml exist."
    exit 1
fi

# For system installs, copy to /opt/video-converter and update SCRIPT_DIR
if [ "$EUID" -eq 0 ]; then
    INSTALL_DIR="/opt/video-converter"
    echo "Installing to: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cp -f "$SOURCE_DIR"/*.py "$INSTALL_DIR/"
    cp -f "$SOURCE_DIR"/*.yaml "$INSTALL_DIR/"
    cp -f "$SOURCE_DIR"/*.sh "$INSTALL_DIR/"
    cp -f "$SOURCE_DIR"/*.txt "$INSTALL_DIR/"
    SCRIPT_DIR="$INSTALL_DIR"
else
    SCRIPT_DIR="$SOURCE_DIR"
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
# Use existing docker user/group for system service
SERVICE_USER="docker"
SERVICE_GROUP="docker"

# Verify docker user exists
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "ERROR: User '$SERVICE_USER' does not exist"
    echo "Please install Docker or specify a different user"
    exit 1
fi

if ! getent group "$SERVICE_GROUP" &>/dev/null; then
    echo "ERROR: Group '$SERVICE_GROUP' does not exist"
    exit 1
fi

echo "[OK] Using service user: $SERVICE_USER (group: $SERVICE_GROUP)"

# Set up directories
echo ""
echo "Setting up directories..."
# Set ownership of install directory to docker
chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$INSTALL_DIR"
chmod -R 750 "$INSTALL_DIR"
chmod 640 "$INSTALL_DIR/config.yaml"

mkdir -p /var/log/video-converter
chown "$SERVICE_USER":"$SERVICE_GROUP" /var/log/video-converter
# Security: Restrict log directory permissions (owner rwx, group rx, others none)
chmod 750 /var/log/video-converter

# Create work directory
# Security: Use a directory under /var/lib instead of /tmp to avoid
# /tmp-based symlink attacks and tmpwatch cleanup issues
mkdir -p /var/lib/video-converter/work
chown -R "$SERVICE_USER":"$SERVICE_GROUP" /var/lib/video-converter
# Security: Parent directory allows owner to access subdirectories
chmod 750 /var/lib/video-converter
# Work directory is owner-only (contains videos during conversion)
chmod 700 /var/lib/video-converter/work

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

# Create system service file with correct paths
cat > "$TEMP_SERVICE_FILE" <<EOF
[Unit]
Description=Video Converter Daemon
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
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

echo ""
echo "=== Installation Complete ==="
echo ""
echo "IMPORTANT: Before starting the service, edit config.yaml to:"
echo "  1. Set the correct directories on nas01 to scan"
echo "  2. Adjust conversion quality settings if needed"
echo "  3. Configure other options as desired"
echo ""
echo "Configuration file: $SCRIPT_DIR/config.yaml"

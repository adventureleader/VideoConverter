#!/bin/bash
# Installation script for Video Converter Daemon

set -e

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

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check dependencies
echo ""
echo "Checking dependencies..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 is not installed"
    exit 1
fi
echo "✓ Python 3 found: $(python3 --version)"

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
    echo "✓ FFmpeg found: $(ffmpeg -version | head -n1)"
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
    echo "✓ PyYAML already installed"
fi

# Create log directory
echo ""
echo "Creating log directory..."
if [ "$SYSTEM_INSTALL" = true ]; then
    mkdir -p /var/log/video-converter
    chown $SUDO_USER:$SUDO_USER /var/log/video-converter
else
    mkdir -p ~/.local/var/log/video-converter
    # Update config to use user log directory
    sed -i "s|/var/log/video-converter|$HOME/.local/var/log/video-converter|g" config.yaml
fi

# Make daemon script executable
chmod +x video_converter_daemon.py

# Configure the service
echo ""
echo "Configuring systemd service..."

# Create service file with correct paths
cat > /tmp/video-converter.service <<EOF
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

[Install]
WantedBy=multi-user.target
EOF

if [ "$SYSTEM_INSTALL" = true ]; then
    # System service
    mv /tmp/video-converter.service /etc/systemd/system/
    systemctl daemon-reload
    echo "✓ System service installed"
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
    mkdir -p ~/.config/systemd/user
    mv /tmp/video-converter.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    echo "✓ User service installed"
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

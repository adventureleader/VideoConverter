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

# Check if daemon is running and stop it
echo ""
echo "Checking for running daemon..."
if systemctl is-active --quiet video-converter; then
    echo "[WARNING] video-converter service is running, stopping it..."
    systemctl stop video-converter
    echo "[OK] Service stopped"
else
    echo "[OK] Service not running"
fi

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

# Validate and optionally fix write permissions for all configured directories
echo ""
echo "Checking directory permissions..."

# Create a temporary Python script to parse config.yaml and check permissions
VALIDATE_SCRIPT="$(mktemp)"
trap "rm -f '$VALIDATE_SCRIPT'" EXIT

cat > "$VALIDATE_SCRIPT" <<'PYTHON_EOF'
import yaml
import os
import sys
from pathlib import Path

config_file = sys.argv[1]

try:
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
except Exception as e:
    print(f"ERROR: Failed to parse config.yaml: {e}")
    sys.exit(1)

# Collect all directories that need write access
dirs_to_check = []

# Add scan directories
if 'directories' in config and isinstance(config['directories'], list):
    dirs_to_check.extend(config['directories'])

# Add work directory
if 'processing' in config and 'work_dir' in config['processing']:
    dirs_to_check.append(config['processing']['work_dir'])

# Add log directory (parent of log file)
if 'daemon' in config and 'log_file' in config['daemon']:
    log_file = config['daemon']['log_file']
    dirs_to_check.append(os.path.dirname(log_file))

# Collect directories that need fixing
dirs_needing_fix = []

# Check each directory and its subdirectories
for dir_path in dirs_to_check:
    if not dir_path:
        continue

    path = Path(dir_path)

    # Check if directory exists
    if not path.exists():
        print(f"[SKIP] Directory does not exist: {dir_path}")
        continue

    if not path.is_dir():
        print(f"[ERROR] Not a directory: {dir_path}")
        sys.exit(1)

    # Check current directory
    try:
        # Try to create a test file
        test_file = path / ".write_test_$$"
        test_file.touch()
        test_file.unlink()
        print(f"[OK] Writable: {dir_path}")
    except PermissionError:
        print(f"[WARN] Not writable: {dir_path}")
        dirs_needing_fix.append(str(path))
    except Exception as e:
        print(f"[WARN] Could not test {dir_path}: {e}")

    # Check subdirectories
    try:
        for root, dirs, _ in os.walk(path):
            for d in dirs:
                subdir = Path(root) / d
                # Only check first few levels to avoid deep traversal
                depth = len(subdir.relative_to(path).parts)
                if depth > 3:
                    continue

                if not os.access(subdir, os.W_OK):
                    print(f"[WARN] Not writable: {subdir}")
                    dirs_needing_fix.append(str(subdir))
    except PermissionError:
        # Expected for some subdirectories we don't own
        pass

# If there are permission issues, show what needs to be fixed
if dirs_needing_fix:
    print("")
    print("=== Permission Issues Found ===")
    print("")
    print("The following directories need write permissions:")
    print("")
    for d in sorted(set(dirs_needing_fix)):
        print(f"  {d}")

    print("")
    print("Manual fix commands (if needed):")
    print("")
    for d in sorted(set(dirs_needing_fix)):
        print(f"  chmod u+w '{d}'")

    # Signal that fixes are needed (exit with code 2 to indicate fixes needed)
    sys.exit(2)
else:
    print("")
    print("[OK] All directories have correct permissions")
    sys.exit(0)
PYTHON_EOF

python3 "$VALIDATE_SCRIPT" "$SCRIPT_DIR/config.yaml"
PERM_STATUS=$?

if [ $PERM_STATUS -eq 2 ]; then
    # Permission issues found - ask user to fix them
    echo ""
    read -p "Would you like to automatically fix these permission issues? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "Fixing permissions..."

        # Create a Python script to apply the fixes
        FIX_SCRIPT="$(mktemp)"
        trap "rm -f '$FIX_SCRIPT'" EXIT

        cat > "$FIX_SCRIPT" <<'PYTHON_FIX_EOF'
import yaml
import os
import sys
import subprocess
from pathlib import Path

config_file = sys.argv[1]

try:
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
except Exception as e:
    print(f"ERROR: Failed to parse config.yaml: {e}")
    sys.exit(1)

# Collect all directories
dirs_to_fix = []

if 'directories' in config and isinstance(config['directories'], list):
    dirs_to_fix.extend(config['directories'])

if 'processing' in config and 'work_dir' in config['processing']:
    dirs_to_fix.append(config['processing']['work_dir'])

if 'daemon' in config and 'log_file' in config['daemon']:
    log_file = config['daemon']['log_file']
    dirs_to_fix.append(os.path.dirname(log_file))

fixed_dirs = set()

# Fix each directory and subdirectories
for dir_path in dirs_to_fix:
    if not dir_path or not Path(dir_path).exists():
        continue

    path = Path(dir_path)

    # Fix current directory
    if not os.access(path, os.W_OK):
        try:
            subprocess.run(['chmod', 'u+w', str(path)], check=True)
            subprocess.run(['chmod', 'g+w', str(path)], check=True)
            fixed_dirs.add(str(path))
            print(f"[FIXED] {path}")
        except Exception as e:
            print(f"[ERROR] Could not fix {path}: {e}")
            sys.exit(1)

    # Fix subdirectories
    try:
        for root, dirs, _ in os.walk(path):
            for d in dirs:
                subdir = Path(root) / d
                depth = len(subdir.relative_to(path).parts)
                if depth > 3:
                    continue

                if not os.access(subdir, os.W_OK):
                    try:
                        subprocess.run(['chmod', 'u+w', str(subdir)], check=True)
                        subprocess.run(['chmod', 'g+w', str(subdir)], check=True)
                        fixed_dirs.add(str(subdir))
                        print(f"[FIXED] {subdir}")
                    except Exception as e:
                        print(f"[ERROR] Could not fix {subdir}: {e}")
                        sys.exit(1)
    except PermissionError:
        pass

print("")
print(f"[OK] Fixed {len(fixed_dirs)} directories")
sys.exit(0)
PYTHON_FIX_EOF

        python3 "$FIX_SCRIPT" "$SCRIPT_DIR/config.yaml"
        if [ $? -ne 0 ]; then
            exit 1
        fi
    else
        echo ""
        echo "Skipping permission fixes. Please run the commands above manually and then re-run:"
        echo "  sudo ./install.sh"
        exit 1
    fi
elif [ $PERM_STATUS -ne 0 ]; then
    # Other error
    exit 1
fi

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

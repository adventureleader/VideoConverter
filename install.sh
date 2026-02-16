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

echo "Running as root - installing system service"

# Check if daemon is running and stop it
echo ""
echo "Checking for running daemon..."
if systemctl is-active --quiet video-converter 2>/dev/null || true; then
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
        apt install -y python3-yaml
    else
        # Fallback to pip with --break-system-packages for externally-managed environments
        echo "Installing via pip..."
        pip3 install --user --break-system-packages PyYAML || pip3 install --user PyYAML
    fi
else
    echo "[OK] PyYAML already installed"
fi

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

python3 "$VALIDATE_SCRIPT" "$SOURCE_DIR/config.yaml"
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

        python3 "$FIX_SCRIPT" "$SOURCE_DIR/config.yaml"
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

# Create FHS-compliant directories
echo ""
echo "Creating FHS-compliant directories..."

# /etc/video-converter - configuration
mkdir -p /etc/video-converter
chmod 755 /etc/video-converter

# /var/lib/video-converter - state and work
mkdir -p /var/lib/video-converter/work
chmod 755 /var/lib/video-converter
chmod 700 /var/lib/video-converter/work

# /var/log/video-converter - logs
mkdir -p /var/log/video-converter
chmod 755 /var/log/video-converter

echo "[OK] FHS directories created"

# Copy daemon script to /usr/local/bin
echo ""
echo "Installing daemon script..."
cp "$SOURCE_DIR/video_converter_daemon.py" /usr/local/bin/video_converter_daemon.py
chmod 755 /usr/local/bin/video_converter_daemon.py
echo "[OK] Daemon script installed to /usr/local/bin/video_converter_daemon.py"

# Copy config file (don't overwrite if it exists)
echo ""
echo "Installing configuration file..."
if [ -f /etc/video-converter/config.yaml ]; then
    echo "[SKIP] Config file already exists at /etc/video-converter/config.yaml"
    echo "       Keeping existing configuration"
else
    cp "$SOURCE_DIR/config.yaml" /etc/video-converter/config.yaml
    chmod 644 /etc/video-converter/config.yaml
    echo "[OK] Config file installed to /etc/video-converter/config.yaml"
fi

# Auto-migrate processed.json from old location if it exists
echo ""
echo "Checking for processed files database migration..."
OLD_DB="/opt/video-converter/work/processed.json"
NEW_DB="/var/lib/video-converter/processed.json"

if [ -f "$OLD_DB" ] && [ ! -f "$NEW_DB" ]; then
    echo "[MIGRATE] Found old database at $OLD_DB"
    cp "$OLD_DB" "$NEW_DB"
    chmod 600 "$NEW_DB"
    echo "[OK] Migrated to $NEW_DB"
elif [ -f "$NEW_DB" ]; then
    echo "[OK] Database already exists at $NEW_DB"
else
    echo "[OK] No existing database found"
fi

# Configure the service
echo ""
echo "Configuring systemd service..."

# Copy service file
cp "$SOURCE_DIR/video-converter.service" /etc/systemd/system/video-converter.service
chmod 644 /etc/systemd/system/video-converter.service
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
echo "IMPORTANT: Before starting the service, ensure config.yaml is correct:"
echo "  1. Edit /etc/video-converter/config.yaml"
echo "  2. Set the correct directories to scan"
echo "  3. Adjust conversion quality settings if needed"
echo "  4. Configure other options as desired"
echo ""
echo "Configuration file: /etc/video-converter/config.yaml"

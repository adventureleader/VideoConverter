# Video Converter Daemon

Automatically discovers and converts video files to .m4v format. Designed to run as a system service with root privileges for universal file access.

## Features

- **Automatic Discovery**: Scans specified directories for video files
- **Concurrent Processing**: Converts multiple videos simultaneously
- **Smart Tracking**: Remembers processed files to avoid re-processing
- **Configurable**: Flexible conversion settings (quality, codecs, etc.)
- **Daemon Service**: Runs continuously in the background as root
- **FHS Compliant**: Uses standard Linux filesystem hierarchy paths
- **Robust**: Handles errors gracefully and retries on failure
- **Remote Mode**: Convert files on a remote NAS/media host via SSH/SFTP
- **Security Hardened**: Input validation, path traversal prevention, systemd isolation

## Requirements

- Python 3.6+
- FFmpeg
- PyYAML
- systemd (for service management)
- Root privileges (for universal file access)
- paramiko (optional, only needed for remote mode)

## Installation

### Prerequisites

Before installation, ensure you have the required dependencies:

```bash
sudo apt update
sudo apt install ffmpeg python3-yaml
```

### System Service Installation

1. **Clone or download the Video Converter Daemon**:
   ```bash
   cd VideoConverter
   ```

2. **Edit the configuration file**:
   ```bash
   # Review config.yaml and set the directories to scan
   nano config.yaml
   ```

3. **Run the installation script as root**:
   ```bash
   sudo ./install.sh
   ```

The installation script will:
- Verify dependencies
- Create FHS-compliant directories
- Install the daemon to `/usr/local/bin/`
- Install config to `/etc/video-converter/`
- Setup systemd service
- Automatically migrate any old processed files database

4. **Configure the service**:
   ```bash
   sudo nano /etc/video-converter/config.yaml
   ```

5. **Enable and start the service**:
   ```bash
   sudo systemctl enable video-converter
   sudo systemctl start video-converter
   ```

## Configuration

Edit `/etc/video-converter/config.yaml` to customize the daemon behavior:

### Directories to Monitor

```yaml
directories:
  - "/path/to/videos1"
  - "/path/to/videos2"
```

### Conversion Quality

- **crf**: 18-28 (lower = better quality, larger file size)
  - 18-20: Very high quality
  - 21-23: High quality (recommended)
  - 24-26: Medium quality
  - 27+: Lower quality, smaller files

- **preset**: Encoding speed vs compression efficiency
  - `ultrafast` - Fastest, largest files
  - `medium` - Balanced (recommended)
  - `slow` - Better compression, slower
  - `veryslow` - Best compression, very slow

### Processing Options

- `keep_original`: Keep or delete source files after conversion
- `max_workers`: Number of concurrent conversions (1-8)
- `scan_interval`: How often to scan for new files (seconds, minimum 30)

### Remote Mode (SSH/SFTP)

Remote mode allows the daemon to run on a powerful conversion host while video files live on a separate media host (e.g., a NAS). The daemon discovers files on the remote host via SFTP, downloads them, converts locally with FFmpeg, and uploads the results back.

```yaml
remote:
  enabled: true
  host: "nas01"              # Remote hostname or IP
  port: 22                   # SSH port (1-65535, default 22)
  user: "root"               # SSH username
  key_file: "/root/.ssh/id_ed25519"  # Path to SSH private key (absolute)
  directories:               # Remote directories to scan
    - "/media"
    - "/mnt/smallmedia"
  connect_timeout: 30        # SSH connection timeout in seconds (default 30)
  transfer_timeout: 3600     # Per-file transfer timeout in seconds (default 3600)
```

**How it works:**
1. Discovers video files on the remote host via SFTP
2. Downloads each file to the local `work_dir`
3. Converts locally with FFmpeg
4. Uploads the `.m4v` result back to the remote host (atomic upload via temp file)
5. Preserves original file timestamps
6. Optionally deletes the original remote file (if `keep_original: false`)

**Requirements for remote mode:**
- `paramiko` Python package: `pip install paramiko>=3.0.0`
- SSH key-based authentication configured between the conversion host and the media host
- The install script will automatically install paramiko when remote mode is detected in the config

**Security:**
- SSH key authentication only (no passwords in config)
- Remote path validation prevents directory traversal attacks
- All operations are pure SFTP (no `ssh exec_command`)
- Uploads use atomic temp-then-rename to prevent partial files
- File size limits enforced before download

When remote mode is disabled or the `remote` section is absent, the daemon operates in local mode exactly as before.

### FHS Paths

The daemon uses the following standard Linux paths:

- **Configuration**: `/etc/video-converter/config.yaml`
- **State/Data**: `/var/lib/video-converter/` (processed.json)
- **Work Directory**: `/var/lib/video-converter/work/` (temporary files)
- **Logs**: `/var/log/video-converter/daemon.log`
- **Binary**: `/usr/local/bin/video_converter_daemon.py`

## Usage

### Check Status

```bash
sudo systemctl status video-converter
```

### View Logs

```bash
# View recent logs
sudo journalctl -u video-converter -n 50

# Follow logs in real-time
sudo journalctl -u video-converter -f

# Or view log file directly
sudo tail -f /var/log/video-converter/daemon.log
```

### Control Service

```bash
# Start
sudo systemctl start video-converter

# Stop
sudo systemctl stop video-converter

# Restart
sudo systemctl restart video-converter

# Disable auto-start
sudo systemctl disable video-converter
```

### CLI Flags

The daemon supports several command-line flags:

```bash
# Use custom config file
video_converter_daemon.py --config /path/to/config.yaml

# Test mode (log what would be done without converting)
video_converter_daemon.py --dry-run

# Validate configuration and exit
video_converter_daemon.py --validate-config

# Show version
video_converter_daemon.py --version

# Show help
video_converter_daemon.py --help
```

## Manual Testing

Test the converter without running as a systemd service:

```bash
# Run in foreground with default config
sudo /usr/local/bin/video_converter_daemon.py

# Run with custom config
sudo /usr/local/bin/video_converter_daemon.py --config /path/to/config.yaml

# Test mode (no conversion, just logging)
sudo /usr/local/bin/video_converter_daemon.py --dry-run

# Validate config
sudo /usr/local/bin/video_converter_daemon.py --validate-config
```

Press Ctrl+C to stop.

## Troubleshooting

### Check FFmpeg

```bash
ffmpeg -version
```

### View Errors

```bash
# Last 50 error log entries
sudo journalctl -u video-converter -p err -n 50

# Search for specific errors
sudo journalctl -u video-converter | grep ERROR
```

### Reset Processed Files

If you want to re-process files:

```bash
sudo rm /var/lib/video-converter/processed.json
sudo systemctl restart video-converter
```

### Test Single Conversion

```bash
ffmpeg -i input.mp4 -c:v libx264 -crf 23 -preset medium -c:a aac -b:a 128k output.m4v
```

### Check Permissions

If conversions fail due to permission issues:

```bash
# Ensure video directories are readable
ls -la /path/to/videos

# Verify work directory exists and is writable
ls -la /var/lib/video-converter/

# Check log directory
ls -la /var/log/video-converter/
```

## File Structure

```
VideoConverter/
├── config.yaml                    # Configuration file
├── video_converter_daemon.py      # Main daemon script
├── sftp_ops.py                    # SFTP operations module (remote mode)
├── video-converter.service        # Systemd service file
├── install.sh                     # Installation script
├── manage.sh                      # Management utility script
├── deploy.sh                      # Deployment script
├── requirements.txt               # Python dependencies
├── README.md                      # This file
├── CHANGELOG.md                   # Change history
├── QUICKSTART.md                  # Quick start guide
└── tests/                         # Test files
    ├── test_daemon.py            # Unit tests
    ├── test_integration.sh        # Integration tests
    └── conftest.py               # Pytest fixtures
```

## How It Works

### Local Mode (default)

1. **Discovery**: Periodically scans configured directories for video files
2. **Filtering**: Checks if files need processing (not already converted, not in progress)
3. **Convert**: Uses FFmpeg to convert to .m4v in a temporary directory
4. **Move**: Moves converted file to same directory as original
5. **Cleanup**: Removes temporary files, optionally deletes original
6. **Track**: Records processed files to avoid re-processing

### Remote Mode (SSH/SFTP)

1. **Discovery**: Lists video files on the remote host via SFTP
2. **Filtering**: Checks remote file size, whether output exists on remote, etc.
3. **Download**: Transfers the source file from remote to local `work_dir`
4. **Convert**: Uses FFmpeg to convert locally
5. **Upload**: Transfers the `.m4v` result back to the remote host (atomic)
6. **Cleanup**: Removes local temp files, optionally deletes remote original
7. **Track**: Records processed files locally to avoid re-processing

## Performance Tips

- **max_workers**: Increase for faster parallel processing (uses more CPU/RAM)
- **work_dir**: Use fast local storage (SSD) for temporary files
- **preset**: Use `fast` or `faster` for quicker conversions
- **crf**: Higher values (24-26) process faster and create smaller files

## Security Considerations

### Why Root?

The daemon runs as root to provide universal file access across the entire filesystem. This simplifies permission management for a daemon that needs to read/write files from various sources.

### Security Measures

The daemon includes extensive security hardening:

- **Input Validation**: All configuration values validated against allowlists at startup
- **Path Traversal Prevention**: Validates resolved paths to prevent symlink-based attacks
- **No Shell Injection**: Arguments passed as lists, never through shell execution
- **Restricted Features**: `extra_options` disabled to prevent ffmpeg flag injection
- **Atomic Operations**: File operations use temp files and atomic renames
- **Resource Limits**: File size limits, timeouts, and resource quotas
- **Systemd Isolation**: Process resource limits (memory, CPU, file descriptors)
- **Strict File Permissions**: Configuration files restricted to owner/group

### Systemd Security Hardening

The systemd service includes:

- `NoNewPrivileges=yes`: Prevents privilege escalation via executables
- `ProtectKernelTunables=yes`: Prevents modification of kernel parameters
- `ProtectKernelModules=yes`: Prevents kernel module loading
- `RestrictSUIDSGID=yes`: Prevents SUID/SGID execution
- `RestrictNamespaces=yes`: Prevents namespace creation
- Resource limits on memory, CPU, and file descriptors

## Migration from Older Versions

If you're upgrading from an older version that ran as a user service:

1. **Backup your current setup**:
   ```bash
   cp -r /opt/video-converter ~/video-converter-backup || true
   cp ~/.config/systemd/user/video-converter.service ~/video-converter-backup/ || true
   ```

2. **Stop the user service**:
   ```bash
   systemctl --user stop video-converter
   systemctl --user disable video-converter
   ```

3. **Run the new installer**:
   ```bash
   sudo ./install.sh
   ```

4. **Copy your config if needed**:
   ```bash
   # If you had custom settings
   sudo nano /etc/video-converter/config.yaml
   ```

5. **Start the new system service**:
   ```bash
   sudo systemctl enable video-converter
   sudo systemctl start video-converter
   ```

6. **Verify operation**:
   ```bash
   sudo systemctl status video-converter
   sudo journalctl -u video-converter -f
   ```

## Management Script

A management script is provided for common operations. After installation, it's available as `video-converter-manage`:

```bash
video-converter-manage start       # Start the daemon
video-converter-manage stop        # Stop the daemon
video-converter-manage restart     # Restart the daemon
video-converter-manage status      # Show daemon status
video-converter-manage logs        # Show recent logs
video-converter-manage follow      # Follow logs in real-time
video-converter-manage enable      # Enable auto-start
video-converter-manage disable     # Disable auto-start
video-converter-manage stats       # Show conversion statistics
video-converter-manage reset       # Reset processed files database
video-converter-manage test        # Run in test mode (dry-run)
video-converter-manage config      # Edit configuration
```

**Location:** `/usr/local/bin/video-converter-manage`

You can also run it from the source directory:
```bash
./manage.sh <command>
```

## Uninstallation

To uninstall the daemon:

```bash
sudo ./uninstall.sh
```

The uninstall script will:
- Stop and disable the systemd service
- Remove the daemon binary
- Remove the systemd service file
- Optionally remove configuration and state files (preserves by default for data safety)

You can later remove remaining files manually:

```bash
sudo rm -rf /etc/video-converter /var/lib/video-converter /var/log/video-converter
```

## License

Free to use and modify as needed.

## Support

For issues or questions:
- Check the logs: `sudo journalctl -u video-converter`
- Review the troubleshooting section above
- Check the QUICKSTART.md for quick reference
- Review the CHANGELOG.md for version history

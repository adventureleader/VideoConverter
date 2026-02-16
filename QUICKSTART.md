# Quick Start Guide

## Installation (on target server)

### 1. From Development Machine

Deploy to your server:

```bash
./deploy.sh nas01
```

Or manually:

```bash
scp -r . nas01:/tmp/video-converter
ssh nas01
cd /tmp/video-converter
```

### 2. Install Dependencies

```bash
sudo apt update
sudo apt install ffmpeg python3-yaml -y
```

### 3. Configure

Edit `config.yaml` and set your video directories:

```yaml
directories:
  - "/media/videos1"
  - "/mnt/videos2"
```

### 4. Test Run (Optional)

Run in test mode to verify everything works:

```bash
sudo python3 video_converter_daemon.py --config config.yaml --dry-run
```

Or with full paths:

```bash
sudo python3 video_converter_daemon.py --validate-config --config config.yaml
```

### 5. Install as System Service

```bash
sudo ./install.sh
```

The installer will:
- Create FHS directories (`/etc`, `/var/lib`, `/var/log`)
- Install the daemon to `/usr/local/bin/`
- Setup systemd service
- Migrate any old `processed.json` automatically

### 6. Start Service

```bash
# Enable auto-start on boot
sudo systemctl enable video-converter

# Start the service
sudo systemctl start video-converter

# Check status
sudo systemctl status video-converter

# Watch logs
sudo journalctl -u video-converter -f
```

## Done!

The daemon will now:
- Scan directories every 5 minutes for videos
- Convert up to 2 videos at a time
- Save .m4v files to the same directory as originals
- Keep original files (configurable)
- Track processed files to avoid duplicates

Everything happens locally on the server!

## Quick Commands

```bash
# Status
sudo systemctl status video-converter

# Stop
sudo systemctl stop video-converter

# Start
sudo systemctl start video-converter

# Restart (after config changes)
sudo systemctl restart video-converter

# View logs (live)
sudo journalctl -u video-converter -f

# View recent logs
sudo journalctl -u video-converter -n 50

# Reset processing database
sudo rm /var/lib/video-converter/processed.json
sudo systemctl restart video-converter
```

## Management Script

Use the included management script for convenience:

```bash
./manage.sh status     # Show status
./manage.sh logs       # Show recent logs
./manage.sh follow     # Follow logs live
./manage.sh stats      # Show conversion stats
./manage.sh config     # Edit configuration
./manage.sh restart    # Restart service
./manage.sh reset      # Reset processed files
```

## Important Paths

- **Configuration**: `/etc/video-converter/config.yaml`
- **Logs**: `/var/log/video-converter/daemon.log`
- **State/Database**: `/var/lib/video-converter/processed.json`
- **Work Directory**: `/var/lib/video-converter/work/` (temp files)
- **Binary**: `/usr/local/bin/video_converter_daemon.py`

## Troubleshooting

### Service won't start

Check logs:
```bash
sudo journalctl -u video-converter -n 100
```

Validate config:
```bash
sudo /usr/local/bin/video_converter_daemon.py --validate-config
```

### Permission denied errors

Ensure video directories are readable:
```bash
sudo ls -la /path/to/videos
```

The daemon runs as root so it should have access to all directories.

### No conversions happening

1. Check if service is running:
   ```bash
   sudo systemctl status video-converter
   ```

2. Check logs:
   ```bash
   sudo journalctl -u video-converter -f
   ```

3. Verify config is correct:
   ```bash
   sudo nano /etc/video-converter/config.yaml
   ```

4. Test with dry-run:
   ```bash
   sudo /usr/local/bin/video_converter_daemon.py --config /etc/video-converter/config.yaml --dry-run
   ```

## For More Information

- See **README.md** for comprehensive documentation
- See **CHANGELOG.md** for version history and upgrade info
- Check logs with `sudo journalctl -u video-converter -f`

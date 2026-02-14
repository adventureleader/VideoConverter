# Quick Start Guide

## Deploy to nas01

### 1. From Development Machine

```bash
./deploy.sh
```

This copies all files to `/opt/video-converter` on nas01.

### 2. SSH to nas01

```bash
ssh nas01
cd /opt/video-converter
```

### 3. Install Dependencies

```bash
sudo apt install ffmpeg python3-pip -y
pip3 install --user PyYAML
```

### 4. Configure

Edit `config.yaml` and set your video directories:

```yaml
directories:
  - "/your/video/directory1"
  - "/your/video/directory2"
```

### 5. Test Run (Optional)

Run manually to verify everything works:

```bash
python3 video_converter_daemon.py config.yaml
```

Press Ctrl+C after it finds some videos.

### 6. Install as Service

```bash
./install.sh
```

### 7. Start Service

```bash
# User service (recommended)
systemctl --user enable --now video-converter

# Check status
systemctl --user status video-converter

# Watch logs
journalctl --user -u video-converter -f
```

## Done!

The daemon will now:
- Scan directories every 5 minutes for videos
- Convert up to 2 videos at a time (locally on nas01)
- Save .m4v files to the same directory as originals
- Keep original files (configurable)
- Track processed files to avoid duplicates

No network transfers needed - everything happens locally on nas01!

## Quick Commands (on nas01)

```bash
# Status
systemctl --user status video-converter

# Stop
systemctl --user stop video-converter

# Start
systemctl --user start video-converter

# Restart (after config changes)
systemctl --user restart video-converter

# View logs
journalctl --user -u video-converter -f

# Or use the management script
./manage.sh status
./manage.sh follow
./manage.sh stats
```

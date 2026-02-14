# Quick Start Guide

## 1. Install Dependencies

```bash
sudo apt install ffmpeg rsync python3-pip -y
pip3 install --user PyYAML
```

## 2. Configure

Edit `config.yaml` and set your nas01 directories:

```yaml
remote:
  directories:
    - "/your/video/directory1"
    - "/your/video/directory2"
```

## 3. Test Connection

```bash
ssh nas01 "ls -la"
```

## 4. Test Run (Optional)

Run manually to verify everything works:

```bash
python3 video_converter_daemon.py config.yaml
```

Press Ctrl+C after it finds some videos.

## 5. Install as Service

```bash
./install.sh
```

## 6. Start Service

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
- Scan nas01 every 5 minutes for videos
- Convert up to 2 videos at a time
- Save .m4v files to the same directory as originals
- Keep original files (configurable)
- Track processed files to avoid duplicates

## Quick Commands

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

# Disable
systemctl --user disable video-converter
```

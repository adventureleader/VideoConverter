# Video Converter Daemon

Automatically discovers and converts video files from a remote server (nas01) to .m4v format.

## Features

- **Automatic Discovery**: Scans specified directories on nas01 for video files
- **Concurrent Processing**: Converts multiple videos simultaneously
- **Smart Tracking**: Remembers processed files to avoid re-processing
- **Configurable**: Flexible conversion settings (quality, codecs, etc.)
- **Daemon Service**: Runs continuously in the background
- **Robust**: Handles errors gracefully and retries on failure

## Requirements

- Python 3.6+
- FFmpeg
- rsync
- SSH access to nas01 (configured with key-based authentication)

## Installation

1. **Install system dependencies** (if not already installed):
   ```bash
   sudo apt install ffmpeg rsync python3-pip
   ```

2. **Run the installation script**:
   ```bash
   # For user service (recommended)
   ./install.sh

   # For system-wide service
   sudo ./install.sh
   ```

3. **Edit the configuration file** `config.yaml`:
   - Set the directories to scan on nas01
   - Adjust conversion quality settings
   - Configure other options as needed

4. **Start the daemon**:
   ```bash
   # User service
   systemctl --user enable video-converter
   systemctl --user start video-converter

   # System service
   sudo systemctl enable video-converter
   sudo systemctl start video-converter
   ```

## Configuration

Edit `config.yaml` to customize the daemon behavior:

### Remote Server Settings
```yaml
remote:
  host: "nas01"
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
- `max_workers`: Number of concurrent conversions
- `scan_interval`: How often to scan for new files (seconds)

## Usage

### Check Status
```bash
# User service
systemctl --user status video-converter

# System service
sudo systemctl status video-converter
```

### View Logs
```bash
# User service
journalctl --user -u video-converter -f

# System service
sudo journalctl -u video-converter -f

# Or view log file directly
tail -f /var/log/video-converter/daemon.log
```

### Stop/Start/Restart
```bash
# User service
systemctl --user stop video-converter
systemctl --user start video-converter
systemctl --user restart video-converter

# System service
sudo systemctl stop video-converter
sudo systemctl start video-converter
sudo systemctl restart video-converter
```

### Disable Auto-start
```bash
# User service
systemctl --user disable video-converter

# System service
sudo systemctl disable video-converter
```

## Manual Testing

Test the converter without running as a daemon:

```bash
# Edit config.yaml first, then:
python3 video_converter_daemon.py config.yaml
```

Press Ctrl+C to stop.

## Troubleshooting

### Check SSH Connection
```bash
ssh nas01 "echo 'Connection successful'"
```

### Check FFmpeg
```bash
ffmpeg -version
```

### Check for Errors
```bash
# View recent logs
journalctl --user -u video-converter -n 50

# Search for errors
journalctl --user -u video-converter | grep ERROR
```

### Reset Processed Files
If you want to re-process files:
```bash
rm /tmp/video_converter/processed.json
```

### Test Single Conversion
```bash
ffmpeg -i input.mp4 -c:v libx264 -crf 23 -preset medium -c:a aac -b:a 128k output.m4v
```

## File Structure

```
VideoConverter/
├── config.yaml                 # Configuration file
├── video_converter_daemon.py   # Main daemon script
├── video-converter.service     # Systemd service file
├── install.sh                  # Installation script
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

## How It Works

1. **Discovery**: Periodically scans configured directories on nas01 for video files
2. **Filtering**: Checks if files need processing (not already converted, not in progress)
3. **Download**: Downloads video file from nas01 to local work directory
4. **Convert**: Uses FFmpeg to convert to .m4v with configured settings
5. **Upload**: Uploads converted file back to nas01 (same directory as original)
6. **Cleanup**: Removes local temporary files, optionally deletes original
7. **Track**: Records processed files to avoid re-processing

## Performance Tips

- **max_workers**: Increase for faster processing (uses more CPU/RAM)
- **work_dir**: Use fast local storage (SSD) for temporary files
- **preset**: Use `fast` or `faster` for quicker conversions
- **crf**: Higher values (24-26) process faster and create smaller files

## Advanced Configuration

### Custom FFmpeg Options
Add extra FFmpeg parameters in `config.yaml`:
```yaml
conversion:
  extra_options:
    - "-movflags"
    - "+faststart"
    - "-pix_fmt"
    - "yuv420p"
```

### Exclude Patterns
Skip certain files or directories:
```yaml
processing:
  exclude_patterns:
    - "*/.backup/*"
    - "*/temp/*"
    - "*_converted_*"
```

## License

Free to use and modify as needed.

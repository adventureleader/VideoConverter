# Changelog

All notable changes to the Video Converter Daemon project will be documented in this file.

## [2.0.0] - 2024-02-16

### Major Changes: Root Privilege Refactor with FHS Compliance

This is a major release with breaking changes. The daemon now runs as root for universal file access and uses FHS-compliant paths.

### ⚠️ Breaking Changes

**Service Model**
- Daemon now runs as root (system service only)
- User service (`systemctl --user`) no longer supported
- Requires `sudo` for all commands

**File Locations**
- Configuration: `/etc/video-converter/config.yaml` (was `/opt/video-converter/config.yaml`)
- Binary: `/usr/local/bin/video_converter_daemon.py` (was `/opt/video-converter/video_converter_daemon.py`)
- State/processed.json: `/var/lib/video-converter/processed.json` (was `/opt/video-converter/work/processed.json`)
- Work directory: `/var/lib/video-converter/work/` (was `/opt/video-converter/work/`)
- Logs: `/var/log/video-converter/daemon.log` (was user-configurable, now standard)

**Installation**
- All user/group creation logic removed
- Docker user dependency removed
- FHS directories automatically created during installation
- Automatic migration of old `processed.json` to new location

### ✨ New Features

**CLI Flags**
- `--config` - Specify custom config file path
- `--dry-run` - Test mode (log what would be done without converting)
- `--validate-config` - Validate config and exit
- `--version` - Show version information
- `--help` - Show help message

**Configuration**
- New `state_dir` option in processing section (separates persistent state from temp files)
- Config template now uses FHS paths by default

**Testing Infrastructure**
- Unit tests with pytest (`tests/test_daemon.py`)
- Integration test shell script (`tests/test_integration.sh`)
- Pytest fixtures for testing (`tests/conftest.py`)
- CI/CD pipeline with GitHub Actions (`.github/workflows/ci.yml`)

**Documentation**
- Complete README rewrite with root privilege explanation
- New CHANGELOG.md (this file)
- Updated QUICKSTART.md for root commands
- Updated manage.sh for system service

### 🔧 Improvements

**Code Quality**
- Added comprehensive argument parsing with argparse
- Improved error messages and logging
- Better separation of concerns (state_dir vs work_dir)
- Enhanced docstrings

**Security**
- Root privilege allows universal file access without permission issues
- Maintained all existing security hardening (input validation, path traversal prevention, etc.)
- Updated systemd service to remove unnecessary restrictions for root service
- Still includes resource limits and kernel protection measures

**Installation**
- Complete rewrite of install.sh
- Removed conditional user service logic
- Automatic FHS directory creation
- Permission validation and auto-fix capabilities
- Automatic migration from old installations

### 📋 Configuration Changes

**config.yaml updates**

```yaml
# Old (v1.x)
processing:
  work_dir: "/var/lib/video-converter/work"

# New (v2.0)
processing:
  work_dir: "/var/lib/video-converter/work"
  state_dir: "/var/lib/video-converter"  # NEW: separate state directory
```

All paths in default config.yaml now use FHS locations.

### 🚀 Migration Guide

If upgrading from v1.x:

1. **Backup your existing installation**:
   ```bash
   cp -r /opt/video-converter ~/video-converter-backup
   cp ~/.config/systemd/user/video-converter.service ~/video-converter-backup/
   ```

2. **Stop the old user service**:
   ```bash
   systemctl --user stop video-converter
   systemctl --user disable video-converter
   ```

3. **Run the new installer**:
   ```bash
   cd VideoConverter
   sudo ./install.sh
   ```
   The installer will automatically:
   - Create FHS directories
   - Migrate your `processed.json`
   - Setup the new system service

4. **Update your configuration** (if you had custom settings):
   ```bash
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

### 🔄 Command Changes

**Old (v1.x)**
```bash
# User service
systemctl --user start video-converter
systemctl --user stop video-converter
journalctl --user -u video-converter -f
rm ~/.local/share/video-converter/processed.json
```

**New (v2.0)**
```bash
# System service
sudo systemctl start video-converter
sudo systemctl stop video-converter
sudo journalctl -u video-converter -f
sudo rm /var/lib/video-converter/processed.json
```

### 📊 Version Comparison

| Aspect | v1.x | v2.0 |
|--------|------|------|
| Service Type | User | System |
| Run As | `docker` user | `root` |
| Config Path | `/opt/video-converter/` | `/etc/video-converter/` |
| State Path | `/opt/video-converter/work/` | `/var/lib/video-converter/` |
| Log Path | Configurable | `/var/log/video-converter/` |
| Binary Path | `/opt/video-converter/` | `/usr/local/bin/` |
| CLI Flags | None | --config, --dry-run, --validate-config, --version |
| FHS Compliant | No | Yes |

## [1.0.0] - Previous Release

Earlier versions supported user-based service installation. For details on v1.x, refer to the v1 documentation.

---

## FAQ

### Why move to root?

Running as root simplifies permission management. The daemon needs to read/write files across the entire filesystem, and root access eliminates complex permission workarounds. The daemon maintains extensive security hardening to prevent abuse.

### Is it still secure?

Yes. The daemon includes:
- Input validation with allowlists
- Path traversal prevention
- No shell injection vectors
- Atomic file operations
- Resource limits via systemd
- Kernel protection features

### Can I stay on v1.x?

Yes, v1.x continues to work. However, v2.0 is recommended for better security and FHS compliance.

### How do I rollback if there are issues?

```bash
sudo systemctl stop video-converter
sudo systemctl disable video-converter
sudo rm /etc/systemd/system/video-converter.service

# Restore user service if backed up
systemctl --user enable video-converter
systemctl --user start video-converter
```

The old installation should still be in your backup or in `/opt/video-converter/`.

### What about my old processed.json?

The installer automatically migrates it from `/opt/video-converter/work/processed.json` to `/var/lib/video-converter/processed.json`.

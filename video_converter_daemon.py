#!/usr/bin/env python3
"""
Video Converter Daemon
Automatically discovers and converts video files to .m4v format
Supports local mode (default) and remote mode via SSH/SFTP
"""

import os
import sys
import time
import yaml
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import hashlib
import shutil
import re
import threading
import argparse
import posixpath
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Set, Optional, Union
import signal
import json

# --- Security: Allowed values for config validation ---
ALLOWED_CODECS = frozenset([
    'libx264', 'libx265', 'libvpx', 'libvpx-vp9', 'libaom-av1',
    'copy', 'mpeg4', 'h264_nvenc', 'hevc_nvenc', 'h264_vaapi',
])
ALLOWED_AUDIO_CODECS = frozenset([
    'aac', 'libmp3lame', 'libvorbis', 'libopus', 'copy', 'ac3', 'flac',
])
ALLOWED_PRESETS = frozenset([
    'ultrafast', 'superfast', 'veryfast', 'faster', 'fast',
    'medium', 'slow', 'slower', 'veryslow',
])
ALLOWED_LOG_LEVELS = frozenset(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
ALLOWED_EXTENSIONS = frozenset([
    'avi', 'mkv', 'mov', 'mp4', 'flv', 'wmv', 'mpg', 'mpeg', 'm4v',
    'webm', 'ts', 'vob', 'ogv', '3gp', 'divx',
])
# Regex: audio bitrate must be digits followed by 'k' or 'M'
AUDIO_BITRATE_RE = re.compile(r'^\d{1,4}[kM]$')
# Max concurrent workers to prevent resource exhaustion
MAX_WORKERS_LIMIT = 8
# Max conversion timeout: 24 hours (prevents zombie processes)
MAX_CONVERSION_TIMEOUT = 86400
# Max file size for conversion: 100 GB
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024 * 1024
# Minimum free disk space limits (in GB)
MIN_FREE_SPACE_GB_DEFAULT = 10
MIN_FREE_SPACE_GB_MIN = 1
MIN_FREE_SPACE_GB_MAX = 100
# Maximum files to discover per scan to prevent memory exhaustion
MAX_DISCOVERED_FILES = 10000

# FHS-compliant default paths
DEFAULT_CONFIG_PATH = '/etc/video-converter/config.yaml'
DEFAULT_STATE_DIR = '/var/lib/video-converter'
DEFAULT_LOG_DIR = '/var/log/video-converter'
VERSION = '2.0.0'


class ConfigValidationError(Exception):
    """Raised when configuration values fail validation."""
    pass


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Video Converter Daemon - Automatically converts video files to .m4v format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Start daemon with default config
  video_converter_daemon.py

  # Use custom config file
  video_converter_daemon.py --config /path/to/config.yaml

  # Test mode (log what would be done without converting)
  video_converter_daemon.py --dry-run

  # Validate config without starting daemon
  video_converter_daemon.py --validate-config

  # Show version
  video_converter_daemon.py --version
        '''
    )

    parser.add_argument(
        '--config',
        type=str,
        default=DEFAULT_CONFIG_PATH,
        help=f'Path to config file (default: {DEFAULT_CONFIG_PATH})'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Test mode: log what would be done without converting files'
    )
    parser.add_argument(
        '--validate-config',
        action='store_true',
        help='Validate configuration and exit'
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'Video Converter Daemon v{VERSION}'
    )

    return parser.parse_args()


class VideoConverterDaemon:
    def __init__(self, config_path: str = "config.yaml", dry_run: bool = False, validate_only: bool = False):
        """Initialize the daemon with configuration

        Args:
            config_path: Path to YAML configuration file
            dry_run: If True, log actions without actually converting files
            validate_only: If True, only load and validate config, don't initialize daemon
        """
        self.running = True
        self.dry_run = dry_run
        self.conversion_times = {}  # Initialize early so load_processed_files can use it
        self._sftp_conn = None  # Initialize before validate_config may reference it
        self.config = self.load_config(config_path)
        self.validate_config()

        # If validate_only, skip the rest of initialization
        if validate_only:
            return

        self.setup_logging()
        self.processed_files = self.load_processed_files()
        self.converting = set()
        self._converting_lock = threading.Lock()
        self._processed_lock = threading.Lock()

        # Cache resolved allowed directories to avoid repeated resolve() calls
        self._resolved_allowed_dirs = []
        for d in self.config.get('directories', []):
            try:
                resolved = Path(d).resolve(strict=True)
                if resolved.is_dir():
                    self._resolved_allowed_dirs.append(resolved)
            except OSError:
                pass

        # Discovery cache to avoid redundant full traversals
        self._discovery_cache = []
        self._cache_time = 0.0

        # Security: Create work directory with restrictive permissions
        work_dir = Path(self.config['processing']['work_dir'])
        work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        # Initialize remote SFTP connection if remote mode is enabled
        if self._is_remote_mode():
            self._init_remote()

        # Register signal handlers
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)

        self.logger.info("Video Converter Daemon initialized%s",
                         " (remote mode)" if self._is_remote_mode() else "")

    def _is_remote_mode(self) -> bool:
        """Check if remote mode is enabled in config."""
        remote = self.config.get('remote', {})
        return bool(remote and remote.get('enabled', False))

    def _init_remote(self):
        """Initialize remote SFTP connection (lazy import of paramiko)."""
        try:
            from sftp_ops import SFTPConnection
        except ImportError:
            raise ImportError(
                "paramiko is required for remote mode. Install it with: pip install paramiko>=3.0.0"
            )

        remote = self.config['remote']
        self._sftp_conn = SFTPConnection(
            host=remote['host'],
            user=remote['user'],
            port=remote.get('port', 22),
            key_file=remote.get('key_file'),
            connect_timeout=remote.get('connect_timeout', 30),
            custom_logger=self.logger,
        )
        self._sftp_conn.connect()

    def load_config(self, config_path: str) -> dict:
        """Load configuration from YAML file"""
        # Security: Resolve to absolute path and verify it is a regular file
        config_resolved = Path(config_path).resolve()
        if not config_resolved.is_file():
            raise FileNotFoundError(f"Config file not found: {config_resolved}")
        with open(config_resolved, 'r') as f:
            return yaml.safe_load(f)

    def validate_config(self):
        """Validate all configuration values against allowlists.

        This prevents injection through malicious config values that end up
        in subprocess arguments or file paths.
        """
        conv = self.config.get('conversion', {})
        proc = self.config.get('processing', {})
        daemon = self.config.get('daemon', {})

        # Validate codec
        codec = conv.get('codec', '')
        if codec not in ALLOWED_CODECS:
            raise ConfigValidationError(
                f"Invalid codec '{codec}'. Allowed: {sorted(ALLOWED_CODECS)}"
            )

        # Validate audio codec
        audio_codec = conv.get('audio_codec', '')
        if audio_codec not in ALLOWED_AUDIO_CODECS:
            raise ConfigValidationError(
                f"Invalid audio_codec '{audio_codec}'. Allowed: {sorted(ALLOWED_AUDIO_CODECS)}"
            )

        # Validate preset
        preset = conv.get('preset', '')
        if preset not in ALLOWED_PRESETS:
            raise ConfigValidationError(
                f"Invalid preset '{preset}'. Allowed: {sorted(ALLOWED_PRESETS)}"
            )

        # Validate CRF (integer 0-51)
        crf = conv.get('crf', 23)
        if not isinstance(crf, int) or crf < 0 or crf > 51:
            raise ConfigValidationError(
                f"Invalid crf '{crf}'. Must be integer 0-51."
            )

        # Validate audio bitrate format
        audio_bitrate = conv.get('audio_bitrate', '')
        if not AUDIO_BITRATE_RE.match(str(audio_bitrate)):
            raise ConfigValidationError(
                f"Invalid audio_bitrate '{audio_bitrate}'. Must match pattern like '128k' or '2M'."
            )

        # Security: Reject extra_options entirely -- these are unconstrained
        # CLI arguments that could be used to inject arbitrary ffmpeg flags
        # (e.g., -filter_complex with lavfi exploits, -f to overwrite arbitrary files).
        extra_options = conv.get('extra_options', [])
        if extra_options:
            raise ConfigValidationError(
                "extra_options is disabled for security. Define specific "
                "conversion parameters in the configuration schema instead."
            )

        # Validate log level
        log_level = daemon.get('log_level', 'INFO')
        if log_level not in ALLOWED_LOG_LEVELS:
            raise ConfigValidationError(
                f"Invalid log_level '{log_level}'. Allowed: {sorted(ALLOWED_LOG_LEVELS)}"
            )

        # Validate max_workers (bounded)
        max_workers = daemon.get('max_workers', 2)
        if not isinstance(max_workers, int) or max_workers < 1 or max_workers > MAX_WORKERS_LIMIT:
            raise ConfigValidationError(
                f"Invalid max_workers '{max_workers}'. Must be 1-{MAX_WORKERS_LIMIT}."
            )

        # Validate scan_interval (at least 30 seconds to prevent busy-loop)
        scan_interval = daemon.get('scan_interval', 300)
        if not isinstance(scan_interval, (int, float)) or scan_interval < 30:
            raise ConfigValidationError(
                f"Invalid scan_interval '{scan_interval}'. Must be >= 30 seconds."
            )

        # Validate min_free_space_gb
        min_free_space_gb = proc.get('min_free_space_gb', MIN_FREE_SPACE_GB_DEFAULT)
        if (not isinstance(min_free_space_gb, (int, float))
                or min_free_space_gb < MIN_FREE_SPACE_GB_MIN
                or min_free_space_gb > MIN_FREE_SPACE_GB_MAX):
            raise ConfigValidationError(
                f"Invalid min_free_space_gb '{min_free_space_gb}'. "
                f"Must be {MIN_FREE_SPACE_GB_MIN}-{MIN_FREE_SPACE_GB_MAX}."
            )

        # Validate include_extensions against allowlist
        extensions = proc.get('include_extensions', [])
        for ext in extensions:
            if ext.lower() not in ALLOWED_EXTENSIONS:
                raise ConfigValidationError(
                    f"Invalid extension '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}"
                )

        # Validate directories exist and are absolute paths
        directories = self.config.get('directories', [])
        for d in directories:
            dir_path = Path(d)
            if not dir_path.is_absolute():
                raise ConfigValidationError(
                    f"Directory '{d}' must be an absolute path."
                )

        # Validate work_dir is an absolute path
        work_dir = proc.get('work_dir', '')
        if not Path(work_dir).is_absolute():
            raise ConfigValidationError(
                f"work_dir '{work_dir}' must be an absolute path."
            )

        # Validate state_dir is an absolute path (if specified)
        state_dir = proc.get('state_dir', DEFAULT_STATE_DIR)
        if not Path(state_dir).is_absolute():
            raise ConfigValidationError(
                f"state_dir '{state_dir}' must be an absolute path."
            )

        # Validate log_file is an absolute path
        log_file = daemon.get('log_file', '')
        if not Path(log_file).is_absolute():
            raise ConfigValidationError(
                f"log_file '{log_file}' must be an absolute path."
            )

        # Validate remote section (if enabled)
        remote = self.config.get('remote', {})
        if remote and remote.get('enabled', False):
            # host: non-empty string
            host = remote.get('host', '')
            if not isinstance(host, str) or not host.strip():
                raise ConfigValidationError(
                    "remote.host must be a non-empty string."
                )

            # user: non-empty string
            user = remote.get('user', '')
            if not isinstance(user, str) or not user.strip():
                raise ConfigValidationError(
                    "remote.user must be a non-empty string."
                )

            # port: integer 1-65535
            port = remote.get('port', 22)
            if not isinstance(port, int) or port < 1 or port > 65535:
                raise ConfigValidationError(
                    f"remote.port '{port}' must be an integer 1-65535."
                )

            # key_file: absolute path if specified
            key_file = remote.get('key_file')
            if key_file is not None:
                if not isinstance(key_file, str) or not key_file.strip():
                    raise ConfigValidationError(
                        "remote.key_file must be a non-empty string if specified."
                    )
                if not posixpath.isabs(key_file):
                    raise ConfigValidationError(
                        f"remote.key_file '{key_file}' must be an absolute path."
                    )

            # directories: non-empty list of absolute POSIX paths
            remote_dirs = remote.get('directories', [])
            if not isinstance(remote_dirs, list) or len(remote_dirs) == 0:
                raise ConfigValidationError(
                    "remote.directories must be a non-empty list."
                )
            for d in remote_dirs:
                if not isinstance(d, str) or not posixpath.isabs(d):
                    raise ConfigValidationError(
                        f"remote.directories entry '{d}' must be an absolute POSIX path."
                    )

            # connect_timeout: >= 1
            connect_timeout = remote.get('connect_timeout', 30)
            if not isinstance(connect_timeout, (int, float)) or connect_timeout < 1:
                raise ConfigValidationError(
                    f"remote.connect_timeout '{connect_timeout}' must be >= 1."
                )

            # transfer_timeout: >= 60
            transfer_timeout = remote.get('transfer_timeout', 3600)
            if not isinstance(transfer_timeout, (int, float)) or transfer_timeout < 60:
                raise ConfigValidationError(
                    f"remote.transfer_timeout '{transfer_timeout}' must be >= 60."
                )

    def setup_logging(self):
        """Configure logging"""
        log_file = self.config['daemon']['log_file']
        log_dir = os.path.dirname(log_file)

        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True, mode=0o750)

        log_level = getattr(logging, self.config['daemon']['log_level'])

        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                RotatingFileHandler(
                    log_file, maxBytes=50*1024*1024, backupCount=5
                ),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('VideoConverter')

    def load_processed_files(self) -> Set[str]:
        """Load list of already processed files

        Supports both old format (list of hashes) and new format (dict with metadata)
        Also loads conversion timing data into self.conversion_times
        """
        state_dir = self.config['processing'].get('state_dir', DEFAULT_STATE_DIR)
        db_file = Path(state_dir) / 'processed.json'
        if db_file.exists():
            with open(db_file, 'r') as f:
                data = json.load(f)

                # Support both old format (list) and new format (dict)
                if isinstance(data, dict):
                    # New format: {hash: {timestamp, duration_seconds}}
                    hashes = set(data.keys())
                    # Validate hashes and load timing data
                    for hash_val, metadata in data.items():
                        if not isinstance(hash_val, str) or not re.match(r'^[a-f0-9]{64}$', hash_val):
                            self.logger.warning("processed.json contains invalid hash, resetting")
                            return set()
                        # Store timing data if available
                        if isinstance(metadata, dict) and isinstance(metadata.get('timestamp'), (int, float)):
                            self.conversion_times[hash_val] = metadata
                    return hashes
                elif isinstance(data, list):
                    # Old format: list of hashes - will be converted to new format on save
                    for item in data:
                        if not isinstance(item, str) or not re.match(r'^[a-f0-9]{64}$', item):
                            self.logger.warning("processed.json contains invalid hash, resetting")
                            return set()
                    return set(data)
                else:
                    self.logger.warning("processed.json has invalid format, resetting")
                    return set()
        return set()

    def save_processed_files(self):
        """Save list of processed files with timing data atomically to prevent corruption"""
        state_dir = self.config['processing'].get('state_dir', DEFAULT_STATE_DIR)
        db_file = Path(state_dir) / 'processed.json'
        tmp_file = db_file.with_suffix('.json.tmp')

        with self._processed_lock:
            try:
                # Build data structure with timing information
                data = {}
                for file_hash in self.processed_files:
                    if file_hash in self.conversion_times:
                        data[file_hash] = self.conversion_times[file_hash]
                    else:
                        # For legacy hashes without timing data, just store timestamp
                        data[file_hash] = {"timestamp": int(time.time())}

                # Security: Write to temp file first, then atomic rename
                fd = os.open(str(tmp_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w') as f:
                    json.dump(data, f, indent=2)
                os.replace(str(tmp_file), str(db_file))
            except Exception:
                # Clean up temp file on failure
                tmp_file.unlink(missing_ok=True)
                raise

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info("Received signal %d, shutting down...", signum)
        self.running = False
        if self._sftp_conn is not None:
            try:
                self._sftp_conn.disconnect()
            except Exception:
                pass

    def get_file_hash(self, file_path: str) -> str:
        """Generate unique hash for file path using SHA-256"""
        # Security: Use SHA-256 instead of MD5 (MD5 is cryptographically broken)
        return hashlib.sha256(file_path.encode()).hexdigest()

    def _is_safe_path(self, path: Path, allowed_dirs: List[str] = None) -> bool:
        """Verify a path resolves within one of the allowed directories.

        This prevents symlink-based path traversal attacks where a symlink
        inside a watched directory points outside of it.

        Uses cached resolved directories when available for performance.
        """
        try:
            resolved = path.resolve(strict=True)
        except (OSError, ValueError):
            return False

        # Use cached resolved dirs if available, otherwise resolve on the fly
        if hasattr(self, '_resolved_allowed_dirs') and self._resolved_allowed_dirs:
            resolved_dirs = self._resolved_allowed_dirs
        else:
            resolved_dirs = []
            for d in (allowed_dirs or []):
                try:
                    resolved_dirs.append(Path(d).resolve(strict=True))
                except OSError:
                    continue

        for allowed_resolved in resolved_dirs:
            try:
                resolved.relative_to(allowed_resolved)
                return True
            except ValueError:
                continue
        return False

    def discover_videos(self) -> List[Union[Path, str]]:
        """Discover video files in configured directories.

        Returns Path objects for local mode, string paths for remote mode.
        """
        if self._is_remote_mode():
            return self._discover_videos_remote()
        return self._discover_videos_local()

    def _discover_videos_remote(self) -> List[str]:
        """Discover video files on the remote host via SFTP."""
        from sftp_ops import sftp_list_videos, validate_remote_path

        remote = self.config['remote']
        remote_dirs = remote['directories']
        extensions = self.config['processing']['include_extensions']
        exclude_patterns = self.config['processing']['exclude_patterns']

        try:
            self._sftp_conn.ensure_connected()
            all_videos = sftp_list_videos(
                self._sftp_conn, remote_dirs, extensions, exclude_patterns
            )

            # Validate all discovered paths against allowed directories
            safe_videos = []
            for video_path in all_videos:
                if validate_remote_path(video_path, remote_dirs):
                    safe_videos.append(video_path)
                else:
                    self.logger.warning(
                        "Skipping remote file outside allowed directories: %s",
                        video_path
                    )

            self.logger.info("Discovered %d remote video files", len(safe_videos))
            return safe_videos
        except Exception as e:
            self.logger.error("Error discovering remote videos: %s", e)
            return []

    def _discover_videos_local(self) -> List[Path]:
        """Discover video files in local configured directories.

        Uses a single os.walk() pass per directory instead of separate glob
        calls per extension, reducing filesystem traversals from N*extensions
        to N (one per directory).
        """
        directories = self.config['directories']
        extensions = self.config['processing']['include_extensions']
        exclude_patterns = self.config['processing']['exclude_patterns']

        # Build extension set once for O(1) lookups
        ext_set = {f".{e.lower()}" for e in extensions}

        all_videos = []

        for directory in directories:
            dir_path = Path(directory)

            if not dir_path.exists():
                self.logger.warning("Directory does not exist: %s", directory)
                continue

            # Security: Verify the directory itself resolves safely
            try:
                resolved_dir = dir_path.resolve(strict=True)
                if not resolved_dir.is_dir():
                    self.logger.warning("Path is not a directory: %s", directory)
                    continue
            except OSError:
                self.logger.warning("Cannot resolve directory: %s", directory)
                continue

            self.logger.debug("Scanning %s", directory)

            try:
                for dirpath, _dirnames, filenames in os.walk(str(resolved_dir)):
                    for filename in filenames:
                        if len(all_videos) >= MAX_DISCOVERED_FILES:
                            self.logger.warning(
                                "Discovery cap reached (%d files), stopping scan",
                                MAX_DISCOVERED_FILES
                            )
                            break

                        video_file = Path(dirpath) / filename

                        # Check extension match
                        if video_file.suffix.lower() not in ext_set:
                            continue

                        # Security: Only process regular files
                        if not video_file.is_file():
                            continue

                        # Security: Verify resolved path stays within allowed directories
                        if not self._is_safe_path(video_file, directories):
                            self.logger.warning(
                                "Skipping file outside allowed directories "
                                "(possible symlink traversal): %s", video_file
                            )
                            continue

                        # Check exclude patterns
                        should_exclude = False
                        for exclude_pattern in exclude_patterns:
                            if video_file.match(exclude_pattern):
                                should_exclude = True
                                break

                        if not should_exclude:
                            all_videos.append(video_file)

                    if len(all_videos) >= MAX_DISCOVERED_FILES:
                        break

            except Exception as e:
                self.logger.error("Exception scanning %s: %s", directory, e)

        self.logger.info("Discovered %d total video files", len(all_videos))
        return all_videos

    def should_process(self, video_path: Union[Path, str]) -> bool:
        """Check if file should be processed.

        Args:
            video_path: Path object (local mode) or string (remote mode).
        """
        if self._is_remote_mode():
            return self._should_process_remote(str(video_path))
        return self._should_process_local(Path(video_path))

    def _should_process_remote(self, video_path: str) -> bool:
        """Check if a remote file should be processed."""
        from sftp_ops import sftp_exists, sftp_stat, SFTPOperationError

        file_hash = self.get_file_hash(video_path)

        # Skip if already processed
        if file_hash in self.processed_files:
            return False

        # Skip if currently converting
        with self._converting_lock:
            if file_hash in self.converting:
                return False

        # Skip if already .m4v
        _, ext = posixpath.splitext(video_path)
        if ext.lower() == '.m4v':
            return False

        # Skip if output already exists on remote
        output_path = posixpath.splitext(video_path)[0] + '.m4v'
        try:
            if output_path != video_path and sftp_exists(self._sftp_conn, output_path):
                self.logger.debug("Remote output already exists: %s", output_path)
                return False
        except Exception as e:
            self.logger.warning("Error checking remote output %s: %s", output_path, e)

        # Check remote file size
        try:
            size, _ = sftp_stat(self._sftp_conn, video_path)
            if size > MAX_FILE_SIZE_BYTES:
                self.logger.warning(
                    "Skipping remote file exceeding size limit (%d bytes): %s",
                    size, video_path
                )
                return False
            if size == 0:
                self.logger.warning("Skipping empty remote file: %s", video_path)
                return False
        except SFTPOperationError as e:
            self.logger.warning("Cannot stat remote file %s: %s", video_path, e)
            return False

        return True

    def _should_process_local(self, video_path: Path) -> bool:
        """Check if a local file should be processed."""
        file_hash = self.get_file_hash(str(video_path))

        # Skip if already processed
        if file_hash in self.processed_files:
            return False

        # Skip if currently converting (thread-safe check)
        with self._converting_lock:
            if file_hash in self.converting:
                return False

        # Skip if output already exists
        output_path = video_path.with_suffix('.m4v')
        if output_path.exists() and output_path != video_path:
            self.logger.debug("Output already exists: %s", output_path)
            return False

        # Skip if already .m4v
        if video_path.suffix.lower() == '.m4v':
            return False

        # Security: Skip files that are too large (resource exhaustion prevention)
        try:
            file_size = video_path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                self.logger.warning(
                    "Skipping file exceeding size limit (%d bytes): %s",
                    file_size, video_path
                )
                return False
            if file_size == 0:
                self.logger.warning("Skipping empty file: %s", video_path)
                return False
        except OSError as e:
            self.logger.warning("Cannot stat file %s: %s", video_path, e)
            return False

        return True

    def convert_video(self, video_path: Union[Path, str]) -> bool:
        """Convert a single video file.

        Args:
            video_path: Path object (local mode) or string (remote mode).

        Returns:
            True if conversion successful, False otherwise.
        """
        if self._is_remote_mode():
            return self._convert_video_remote(str(video_path))
        return self._convert_video_local(Path(video_path))

    def _convert_video_remote(self, video_path: str) -> bool:
        """Convert a remote video: download, convert locally, upload result."""
        from sftp_ops import (
            sftp_download, sftp_upload, sftp_delete, sftp_stat,
            sftp_utime, validate_remote_path, SFTPOperationError,
        )

        file_hash = self.get_file_hash(video_path)
        work_dir = Path(self.config['processing']['work_dir'])
        remote = self.config['remote']
        transfer_timeout = remote.get('transfer_timeout', 3600)
        start_time = time.time()

        _, remote_ext = posixpath.splitext(video_path)
        local_input = work_dir / f"{file_hash}_input{remote_ext}"
        local_output = work_dir / f"{file_hash}_output.m4v"
        remote_output = posixpath.splitext(video_path)[0] + '.m4v'

        try:
            with self._converting_lock:
                self.converting.add(file_hash)

            self.logger.info("Starting remote conversion: %s", video_path)

            # Dry-run mode
            if self.dry_run:
                self.logger.info("[DRY-RUN] Would download: %s", video_path)
                self.logger.info("[DRY-RUN] Would convert and upload to: %s", remote_output)
                with self._processed_lock:
                    self.processed_files.add(file_hash)
                    self.conversion_times[file_hash] = {
                        "timestamp": int(start_time),
                        "duration_seconds": int(time.time() - start_time),
                        "dry_run": True
                    }
                self.save_processed_files()
                return True

            # Security: Validate remote path
            if not validate_remote_path(video_path, remote['directories']):
                self.logger.error("Remote path fails validation: %s", video_path)
                return False

            # Step 1: Download remote file
            self.logger.info("Downloading %s", video_path)
            try:
                sftp_download(self._sftp_conn, video_path, str(local_input), transfer_timeout)
            except SFTPOperationError as e:
                self.logger.error("Download failed for %s: %s", video_path, e)
                return False

            # Step 2: Convert locally with FFmpeg
            self.logger.info("Converting %s", posixpath.basename(video_path))
            ffmpeg_cmd = self.build_ffmpeg_command(local_input, local_output)

            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True,
                timeout=MAX_CONVERSION_TIMEOUT,
            )

            if result.returncode != 0:
                stderr_truncated = result.stderr[:2000] if result.stderr else "(no stderr)"
                self.logger.error(
                    "Conversion failed for %s: %s", video_path, stderr_truncated
                )
                return False

            if not local_output.is_file():
                self.logger.error("Conversion output is not a regular file: %s", local_output)
                return False

            # Step 3: Upload converted file
            self.logger.info("Uploading to %s", remote_output)
            try:
                sftp_upload(self._sftp_conn, str(local_output), remote_output, transfer_timeout)
            except SFTPOperationError as e:
                self.logger.error("Upload failed for %s: %s", remote_output, e)
                return False

            # Step 4: Preserve timestamps
            try:
                _, mtime = sftp_stat(self._sftp_conn, video_path)
                sftp_utime(self._sftp_conn, remote_output, (mtime, mtime))
            except Exception as e:
                self.logger.warning("Could not preserve remote timestamps: %s", e)

            # Step 5: Optionally delete original
            if not self.config['processing']['keep_original']:
                self.logger.info("Deleting remote original: %s", video_path)
                try:
                    sftp_delete(self._sftp_conn, video_path)
                except Exception as e:
                    self.logger.error("Failed to delete remote original: %s", e)

            # Mark as processed
            duration = int(time.time() - start_time)
            with self._processed_lock:
                self.processed_files.add(file_hash)
                self.conversion_times[file_hash] = {
                    "timestamp": int(start_time),
                    "duration_seconds": duration
                }
            self.save_processed_files()

            self.logger.info(
                "Successfully converted remote file: %s (took %d seconds)",
                video_path, duration
            )
            return True

        except subprocess.TimeoutExpired:
            self.logger.error(
                "Conversion timeout (%ds) for %s", MAX_CONVERSION_TIMEOUT, video_path
            )
            return False
        except Exception as e:
            self.logger.error("Exception converting %s: %s", video_path, e, exc_info=True)
            return False
        finally:
            with self._converting_lock:
                self.converting.discard(file_hash)
            # Cleanup local temp files
            local_input.unlink(missing_ok=True)
            local_output.unlink(missing_ok=True)

    def _convert_video_local(self, video_path: Path) -> bool:
        """Convert a single local video file.

        Args:
            video_path: Path to video file to convert.

        Returns:
            True if conversion successful, False otherwise.
        """
        file_hash = self.get_file_hash(str(video_path))
        work_dir = Path(self.config['processing']['work_dir'])
        start_time = time.time()

        try:
            with self._converting_lock:
                self.converting.add(file_hash)

            self.logger.info("Starting conversion: %s", video_path)

            # Dry-run mode: log what would be done without converting
            if self.dry_run:
                self.logger.info("[DRY-RUN] Would convert: %s", video_path)
                self.logger.info("[DRY-RUN] Would output to: %s", video_path.with_suffix('.m4v'))
                with self._processed_lock:
                    self.processed_files.add(file_hash)
                    # Store timing even for dry-run
                    self.conversion_times[file_hash] = {
                        "timestamp": int(start_time),
                        "duration_seconds": int(time.time() - start_time),
                        "dry_run": True
                    }
                self.save_processed_files()
                return True

            # Security: Re-verify the file still exists and is safe before conversion
            if not video_path.is_file():
                self.logger.error("File no longer exists: %s", video_path)
                return False

            if not self._is_safe_path(video_path, self.config['directories']):
                self.logger.error(
                    "File path resolution changed (possible TOCTOU attack): %s",
                    video_path
                )
                return False

            # Check disk space before starting conversion
            min_free_gb = self.config['processing'].get(
                'min_free_space_gb', MIN_FREE_SPACE_GB_DEFAULT
            )
            min_free_bytes = int(min_free_gb * 1024 * 1024 * 1024)
            try:
                work_free = shutil.disk_usage(str(work_dir)).free
                output_free = shutil.disk_usage(str(video_path.parent)).free
                if work_free < min_free_bytes:
                    self.logger.error(
                        "Insufficient disk space in work_dir %s: %d MB free (need %d MB)",
                        work_dir, work_free // (1024*1024),
                        min_free_bytes // (1024*1024)
                    )
                    return False
                if output_free < min_free_bytes:
                    self.logger.error(
                        "Insufficient disk space in output dir %s: %d MB free (need %d MB)",
                        video_path.parent, output_free // (1024*1024),
                        min_free_bytes // (1024*1024)
                    )
                    return False
            except OSError as e:
                self.logger.error("Cannot check disk space: %s", e)
                return False

            # Generate output filename
            output_path = video_path.with_suffix('.m4v')
            temp_output = work_dir / f"{file_hash}_output.m4v"

            # Security: Verify temp output is within work_dir
            try:
                temp_output.resolve().relative_to(work_dir.resolve())
            except ValueError:
                self.logger.error("Temp output path escapes work directory")
                return False

            # Convert video
            self.logger.info("Converting %s", video_path.name)
            ffmpeg_cmd = self.build_ffmpeg_command(video_path, temp_output)

            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True,
                # Security: Set a timeout to prevent zombie processes
                timeout=MAX_CONVERSION_TIMEOUT,
            )

            if result.returncode != 0:
                # Security: Truncate stderr to prevent log flooding from malicious files
                stderr_truncated = result.stderr[:2000] if result.stderr else "(no stderr)"
                self.logger.error(
                    "Conversion failed for %s: %s", video_path, stderr_truncated
                )
                temp_output.unlink(missing_ok=True)
                return False

            # Security: Verify the temp output is a regular file before moving
            if not temp_output.is_file():
                self.logger.error("Temp output is not a regular file: %s", temp_output)
                return False

            # Move converted file to final location
            self.logger.info("Moving converted file to %s", output_path)
            shutil.move(str(temp_output), str(output_path))

            # Preserve timestamps
            try:
                stat = video_path.stat()
                os.utime(output_path, (stat.st_atime, stat.st_mtime))
            except Exception as e:
                self.logger.warning("Could not preserve timestamps: %s", e)

            # Delete original if configured
            if not self.config['processing']['keep_original']:
                self.logger.info("Deleting original: %s", video_path)
                try:
                    video_path.unlink()
                except Exception as e:
                    self.logger.error("Failed to delete original: %s", e)

            # Mark as processed with timing data
            duration = int(time.time() - start_time)
            with self._processed_lock:
                self.processed_files.add(file_hash)
                self.conversion_times[file_hash] = {
                    "timestamp": int(start_time),
                    "duration_seconds": duration
                }
            self.save_processed_files()

            self.logger.info("Successfully converted: %s (took %d seconds)", video_path, duration)
            return True

        except subprocess.TimeoutExpired:
            self.logger.error(
                "Conversion timeout (%ds) for %s", MAX_CONVERSION_TIMEOUT, video_path
            )
            return False
        except Exception as e:
            self.logger.error("Exception converting %s: %s", video_path, e, exc_info=True)
            return False
        finally:
            with self._converting_lock:
                self.converting.discard(file_hash)
            # Cleanup temp files
            temp_output = work_dir / f"{file_hash}_output.m4v"
            temp_output.unlink(missing_ok=True)

    def build_ffmpeg_command(self, input_path: Path, output_path: Path) -> List[str]:
        """Build FFmpeg command from validated configuration.

        Security notes:
        - All config values are validated in validate_config() at startup.
        - Arguments are passed as a list (no shell=True), preventing shell injection.
        - extra_options is disabled to prevent arbitrary flag injection.
        - The -nostdin flag prevents ffmpeg from reading stdin (avoids hanging).
        """
        config = self.config['conversion']

        cmd = [
            'ffmpeg',
            '-nostdin',      # Security: prevent ffmpeg from reading stdin
            '-i', str(input_path),
            '-c:v', config['codec'],
            '-crf', str(config['crf']),
            '-preset', config['preset'],
            '-c:a', config['audio_codec'],
            '-b:a', config['audio_bitrate'],
            '-y', str(output_path),
        ]

        return cmd

    def process_batch(self, videos: List[Path]):
        """Process a batch of videos with concurrent workers"""
        max_workers = self.config['daemon']['max_workers']

        # Filter videos that need processing
        to_process = [v for v in videos if self.should_process(v)]

        if not to_process:
            self.logger.debug("No new videos to process")
            return

        self.logger.info(
            "Processing %d videos with %d workers", len(to_process), max_workers
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.convert_video, video): video
                      for video in to_process}

            for future in as_completed(futures):
                video = futures[future]
                try:
                    success = future.result()
                    if success:
                        self.logger.info("Completed: %s", video)
                    else:
                        self.logger.warning("Failed: %s", video)
                except Exception as e:
                    self.logger.error("Exception processing %s: %s", video, e)

    def run(self):
        """Main daemon loop"""
        scan_interval = self.config['daemon']['scan_interval']

        self.logger.info("Video Converter Daemon started")
        self.logger.info("Scan interval: %d seconds", scan_interval)
        self.logger.info("Monitoring directories: %s", self.config['directories'])

        # In dry-run mode, only do one scan cycle
        if self.dry_run:
            self.logger.info("DRY-RUN MODE: Running single scan cycle")
            try:
                videos = self.discover_videos()
                self.process_batch(videos)
                self.logger.info("Scan cycle complete")
            except Exception as e:
                self.logger.error("Error in scan cycle: %s", e, exc_info=True)
            return

        while self.running:
            try:
                self.logger.info("Starting scan cycle...")

                # Use cached discovery results if cache is fresh and no work was pending
                cache_max_age = scan_interval * 3
                cache_age = time.time() - self._cache_time
                if (self._discovery_cache
                        and cache_age < cache_max_age
                        and not any(self.should_process(v) for v in self._discovery_cache)):
                    self.logger.debug(
                        "Using cached discovery (%d files, %.0fs old)",
                        len(self._discovery_cache), cache_age
                    )
                    videos = self._discovery_cache
                else:
                    videos = self.discover_videos()
                    self._discovery_cache = videos
                    self._cache_time = time.time()

                # Process videos
                self.process_batch(videos)

                self.logger.info(
                    "Scan cycle complete. Sleeping for %d seconds", scan_interval
                )

                # Sleep with interruption check
                sleep_elapsed = 0
                while sleep_elapsed < scan_interval and self.running:
                    time.sleep(min(5, scan_interval - sleep_elapsed))
                    sleep_elapsed += 5

            except Exception as e:
                self.logger.error("Error in main loop: %s", e, exc_info=True)
                time.sleep(30)

        # Disconnect SFTP on exit
        if self._sftp_conn is not None:
            try:
                self._sftp_conn.disconnect()
            except Exception:
                pass

        self.logger.info("Video Converter Daemon stopped")

def main():
    """Main entry point"""
    args = parse_arguments()

    # Security: Resolve to absolute path
    config_resolved = Path(args.config).resolve()
    if not config_resolved.is_file():
        print(f"Error: Config file not found: {config_resolved}")
        sys.exit(1)

    try:
        # For --validate-config, only validate config without starting daemon
        if args.validate_config:
            # Load and validate config without initializing full daemon
            config = VideoConverterDaemon(str(config_resolved), validate_only=True).config
            print("✓ Configuration is valid")
            sys.exit(0)

        # Start daemon (with optional dry-run mode)
        daemon = VideoConverterDaemon(str(config_resolved), dry_run=args.dry_run)
        if args.dry_run:
            daemon.logger.info("Starting in DRY-RUN mode - no files will be converted")
        daemon.run()
    except ConfigValidationError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

"""Unit tests for Video Converter Daemon"""

import pytest
import tempfile
import json
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from video_converter_daemon import (
    VideoConverterDaemon,
    ConfigValidationError,
    parse_arguments,
    DEFAULT_CONFIG_PATH,
)


class TestArgumentParsing:
    """Test CLI argument parsing"""

    def test_default_config_path(self, monkeypatch):
        """Test that default config path is used when not specified"""
        monkeypatch.setattr(sys, 'argv', ['daemon'])
        args = parse_arguments()
        assert args.config == DEFAULT_CONFIG_PATH

    def test_custom_config_path(self, monkeypatch):
        """Test that custom config path is accepted"""
        monkeypatch.setattr(sys, 'argv', ['daemon', '--config', '/custom/path.yaml'])
        args = parse_arguments()
        assert args.config == '/custom/path.yaml'

    def test_dry_run_flag(self, monkeypatch):
        """Test that --dry-run flag is recognized"""
        monkeypatch.setattr(sys, 'argv', ['daemon', '--dry-run'])
        args = parse_arguments()
        assert args.dry_run is True

    def test_validate_config_flag(self, monkeypatch):
        """Test that --validate-config flag is recognized"""
        monkeypatch.setattr(sys, 'argv', ['daemon', '--validate-config'])
        args = parse_arguments()
        assert args.validate_config is True


class TestConfigValidation:
    """Test configuration validation"""

    @pytest.fixture
    def minimal_config(self):
        """Create a minimal valid config"""
        return {
            'directories': ['/tmp'],
            'conversion': {
                'codec': 'libx264',
                'crf': 23,
                'preset': 'medium',
                'audio_codec': 'aac',
                'audio_bitrate': '128k',
                'extra_options': [],
            },
            'processing': {
                'work_dir': '/tmp/work',
                'state_dir': '/tmp/state',
                'include_extensions': ['mp4'],
                'exclude_patterns': [],
                'keep_original': True,
            },
            'daemon': {
                'log_level': 'INFO',
                'log_file': '/tmp/daemon.log',
                'scan_interval': 300,
                'max_workers': 2,
            },
        }

    def test_invalid_codec(self, minimal_config):
        """Test that invalid codec is rejected"""
        minimal_config['conversion']['codec'] = 'invalid_codec'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with patch('video_converter_daemon.Path.resolve') as mock_resolve:
                    mock_resolve.return_value.is_file.return_value = True
                daemon = VideoConverterDaemon(f.name)
                with pytest.raises(ConfigValidationError):
                    pass  # Error should be raised in __init__
            finally:
                os.unlink(f.name)

    def test_extra_options_disabled(self, minimal_config):
        """Test that extra_options are disabled for security"""
        minimal_config['conversion']['extra_options'] = ['-movflags', '+faststart']
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="extra_options is disabled"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_invalid_preset(self, minimal_config):
        """Test that invalid preset is rejected"""
        minimal_config['conversion']['preset'] = 'invalid_preset'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_invalid_audio_bitrate(self, minimal_config):
        """Test that invalid audio bitrate is rejected"""
        minimal_config['conversion']['audio_bitrate'] = 'invalid'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)


class TestProcessedFiles:
    """Test processed files save/load"""

    @pytest.fixture
    def temp_config(self, tmp_path):
        """Create a temp config with temp state dir"""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "daemon.log"

        config = {
            'directories': [str(tmp_path)],
            'conversion': {
                'codec': 'libx264',
                'crf': 23,
                'preset': 'medium',
                'audio_codec': 'aac',
                'audio_bitrate': '128k',
                'extra_options': [],
            },
            'processing': {
                'work_dir': str(work_dir),
                'state_dir': str(state_dir),
                'include_extensions': ['mp4'],
                'exclude_patterns': [],
                'keep_original': True,
            },
            'daemon': {
                'log_level': 'INFO',
                'log_file': str(log_file),
                'scan_interval': 300,
                'max_workers': 2,
            },
        }

        config_file = tmp_path / "config.yaml"
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        return config_file, state_dir

    def test_save_and_load_processed_files(self, temp_config):
        """Test saving and loading processed files"""
        config_file, state_dir = temp_config
        daemon = VideoConverterDaemon(str(config_file))

        # Add some hashes and save
        test_hash = 'a' * 64  # SHA-256 hash
        daemon.processed_files.add(test_hash)
        daemon.save_processed_files()

        # Verify the file was created
        db_file = state_dir / 'processed.json'
        assert db_file.exists()

        # Create new daemon instance and load
        daemon2 = VideoConverterDaemon(str(config_file))
        assert test_hash in daemon2.processed_files

    def test_load_invalid_processed_files(self, temp_config):
        """Test that invalid processed files are handled gracefully"""
        config_file, state_dir = temp_config

        # Create invalid processed.json
        db_file = state_dir / 'processed.json'
        with open(db_file, 'w') as f:
            json.dump(['invalid_hash_too_short'], f)

        daemon = VideoConverterDaemon(str(config_file))
        # Should reset to empty set on invalid data
        assert len(daemon.processed_files) == 0


class TestPathSecurity:
    """Test path security functions"""

    @pytest.fixture
    def daemon_instance(self, tmp_path):
        """Create a daemon instance for testing"""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "daemon.log"

        config = {
            'directories': [str(tmp_path / "allowed")],
            'conversion': {
                'codec': 'libx264',
                'crf': 23,
                'preset': 'medium',
                'audio_codec': 'aac',
                'audio_bitrate': '128k',
                'extra_options': [],
            },
            'processing': {
                'work_dir': str(work_dir),
                'state_dir': str(state_dir),
                'include_extensions': ['mp4'],
                'exclude_patterns': [],
                'keep_original': True,
            },
            'daemon': {
                'log_level': 'INFO',
                'log_file': str(log_file),
                'scan_interval': 300,
                'max_workers': 2,
            },
        }

        config_file = tmp_path / "config.yaml"
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        return VideoConverterDaemon(str(config_file))

    def test_safe_path_within_allowed(self, daemon_instance, tmp_path):
        """Test that safe path within allowed dir is accepted"""
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        test_file = allowed_dir / "video.mp4"
        test_file.touch()

        is_safe = daemon_instance._is_safe_path(test_file, [str(allowed_dir)])
        assert is_safe is True

    def test_safe_path_outside_allowed(self, daemon_instance, tmp_path):
        """Test that path outside allowed dir is rejected"""
        disallowed_file = tmp_path / "outside.mp4"
        disallowed_file.touch()

        is_safe = daemon_instance._is_safe_path(disallowed_file, [str(tmp_path / "allowed")])
        assert is_safe is False


class TestFileHash:
    """Test file hash generation"""

    @pytest.fixture
    def daemon_instance(self, tmp_path):
        """Create a minimal daemon for testing"""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "daemon.log"

        config = {
            'directories': [str(tmp_path)],
            'conversion': {
                'codec': 'libx264',
                'crf': 23,
                'preset': 'medium',
                'audio_codec': 'aac',
                'audio_bitrate': '128k',
                'extra_options': [],
            },
            'processing': {
                'work_dir': str(work_dir),
                'state_dir': str(state_dir),
                'include_extensions': ['mp4'],
                'exclude_patterns': [],
                'keep_original': True,
            },
            'daemon': {
                'log_level': 'INFO',
                'log_file': str(log_file),
                'scan_interval': 300,
                'max_workers': 2,
            },
        }

        config_file = tmp_path / "config.yaml"
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        return VideoConverterDaemon(str(config_file))

    def test_file_hash_is_sha256(self, daemon_instance):
        """Test that file hash is SHA-256 (64 hex chars)"""
        file_path = "/some/video/file.mp4"
        hash_value = daemon_instance.get_file_hash(file_path)

        # SHA-256 produces 64 hex characters
        assert len(hash_value) == 64
        assert all(c in '0123456789abcdef' for c in hash_value)

    def test_file_hash_deterministic(self, daemon_instance):
        """Test that same file produces same hash"""
        file_path = "/some/video/file.mp4"
        hash1 = daemon_instance.get_file_hash(file_path)
        hash2 = daemon_instance.get_file_hash(file_path)
        assert hash1 == hash2

    def test_file_hash_different_for_different_paths(self, daemon_instance):
        """Test that different paths produce different hashes"""
        hash1 = daemon_instance.get_file_hash("/video1.mp4")
        hash2 = daemon_instance.get_file_hash("/video2.mp4")
        assert hash1 != hash2

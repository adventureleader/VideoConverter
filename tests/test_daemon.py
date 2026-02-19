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
                with pytest.raises(ConfigValidationError):
                    daemon = VideoConverterDaemon(f.name)
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
                    daemon = VideoConverterDaemon(f.name)
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
                    daemon = VideoConverterDaemon(f.name)
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


class TestConversionTiming:
    """Test conversion timing tracking"""

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

    def test_conversion_time_saved(self, temp_config):
        """Test that conversion timing is saved to processed.json"""
        config_file, state_dir = temp_config
        daemon = VideoConverterDaemon(str(config_file))

        test_hash = 'a' * 64
        daemon.processed_files.add(test_hash)
        daemon.conversion_times[test_hash] = {
            "timestamp": 1234567890,
            "duration_seconds": 42
        }
        daemon.save_processed_files()

        # Load and verify
        db_file = state_dir / 'processed.json'
        with open(db_file, 'r') as f:
            data = json.load(f)

        assert test_hash in data
        assert data[test_hash]['duration_seconds'] == 42
        assert data[test_hash]['timestamp'] == 1234567890

    def test_load_old_format_processed_files(self, temp_config):
        """Test backward compatibility with old list format"""
        config_file, state_dir = temp_config

        # Create old format processed.json
        db_file = state_dir / 'processed.json'
        old_format = ['a' * 64, 'b' * 64]
        with open(db_file, 'w') as f:
            json.dump(old_format, f)

        # Load should succeed
        daemon = VideoConverterDaemon(str(config_file))
        assert len(daemon.processed_files) == 2
        assert 'a' * 64 in daemon.processed_files

    def test_new_format_processed_files_with_timing(self, temp_config):
        """Test loading new format with timing data"""
        config_file, state_dir = temp_config

        # Create new format processed.json
        db_file = state_dir / 'processed.json'
        new_format = {
            'a' * 64: {'timestamp': 1000000, 'duration_seconds': 30},
            'b' * 64: {'timestamp': 1000030, 'duration_seconds': 45}
        }
        with open(db_file, 'w') as f:
            json.dump(new_format, f)

        # Load should succeed and restore timing data
        daemon = VideoConverterDaemon(str(config_file))
        assert len(daemon.processed_files) == 2
        assert daemon.conversion_times['a' * 64]['duration_seconds'] == 30
        assert daemon.conversion_times['b' * 64]['duration_seconds'] == 45


class TestConfigValidationEdgeCases:
    """Test edge cases in configuration validation"""

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

    def test_invalid_crf_value(self, minimal_config):
        """Test that invalid CRF value is rejected"""
        minimal_config['conversion']['crf'] = 99  # Max is 51
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="Invalid crf"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_invalid_max_workers(self, minimal_config):
        """Test that max_workers > 8 is rejected"""
        minimal_config['daemon']['max_workers'] = 10
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="max_workers"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_invalid_scan_interval(self, minimal_config):
        """Test that scan_interval < 30 is rejected"""
        minimal_config['daemon']['scan_interval'] = 10
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="scan_interval"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_relative_directory_path_rejected(self, minimal_config):
        """Test that relative paths are rejected"""
        minimal_config['directories'] = ['./videos']
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="must be an absolute path"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_relative_work_dir_rejected(self, minimal_config):
        """Test that relative work_dir is rejected"""
        minimal_config['processing']['work_dir'] = './work'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="work_dir"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_invalid_audio_codec(self, minimal_config):
        """Test that invalid audio codec is rejected"""
        minimal_config['conversion']['audio_codec'] = 'invalid_codec'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="audio_codec"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_invalid_log_level(self, minimal_config):
        """Test that invalid log level is rejected"""
        minimal_config['daemon']['log_level'] = 'INVALID'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="log_level"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)


class TestFFmpegCommandBuilding:
    """Test FFmpeg command building"""

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
            'directories': [str(tmp_path)],
            'conversion': {
                'codec': 'libx264',
                'crf': 23,
                'preset': 'slow',
                'audio_codec': 'aac',
                'audio_bitrate': '192k',
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

    def test_ffmpeg_command_includes_codec(self, daemon_instance, tmp_path):
        """Test that FFmpeg command includes specified codec"""
        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon_instance.build_ffmpeg_command(input_file, output_file)

        assert 'ffmpeg' in cmd
        assert '-c:v' in cmd
        assert 'libx264' in cmd

    def test_ffmpeg_command_includes_crf(self, daemon_instance, tmp_path):
        """Test that FFmpeg command includes CRF value"""
        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon_instance.build_ffmpeg_command(input_file, output_file)

        assert '-crf' in cmd
        crf_index = cmd.index('-crf')
        assert cmd[crf_index + 1] == '23'

    def test_ffmpeg_command_includes_preset(self, daemon_instance, tmp_path):
        """Test that FFmpeg command includes preset"""
        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon_instance.build_ffmpeg_command(input_file, output_file)

        assert '-preset' in cmd
        preset_index = cmd.index('-preset')
        assert cmd[preset_index + 1] == 'slow'

    def test_ffmpeg_command_includes_audio_settings(self, daemon_instance, tmp_path):
        """Test that FFmpeg command includes audio codec and bitrate"""
        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon_instance.build_ffmpeg_command(input_file, output_file)

        assert '-c:a' in cmd
        assert 'aac' in cmd
        assert '-b:a' in cmd
        assert '192k' in cmd

    def test_ffmpeg_command_includes_nostdin(self, daemon_instance, tmp_path):
        """Test that FFmpeg command includes -nostdin flag for security"""
        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon_instance.build_ffmpeg_command(input_file, output_file)

        assert '-nostdin' in cmd


# ============================================================================
# PHASE 1: CRITICAL PATH TESTING (HIGH PRIORITY)
# ============================================================================

class TestSignalHandling:
    """Test signal handling for graceful shutdown"""

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

    def test_handle_shutdown_sigterm(self, daemon_instance):
        """Test SIGTERM handler sets running=False"""
        import signal
        daemon_instance.running = True
        daemon_instance.handle_shutdown(signal.SIGTERM, None)
        assert daemon_instance.running is False

    def test_handle_shutdown_sigint(self, daemon_instance):
        """Test SIGINT handler sets running=False"""
        import signal
        daemon_instance.running = True
        daemon_instance.handle_shutdown(signal.SIGINT, None)
        assert daemon_instance.running is False


class TestDryRunMode:
    """Test dry-run mode functionality"""

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

        return VideoConverterDaemon(str(config_file), dry_run=True)

    def test_run_dry_run_single_cycle(self, daemon_instance, tmp_path):
        """Test dry-run mode exits after one scan cycle"""
        # Create test video
        video = tmp_path / "test.mp4"
        video.write_bytes(b"dummy video data")

        # Run daemon (should exit after one cycle in dry-run mode)
        daemon_instance.run()

        # Verify no actual conversion occurred (no output file)
        assert not (tmp_path / "test.m4v").exists()
        # Verify file was marked as processed
        assert daemon_instance.get_file_hash(str(video)) in daemon_instance.processed_files


class TestMainLoop:
    """Test main daemon loop execution and interruption"""

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

    def test_run_main_loop_graceful_shutdown(self, daemon_instance):
        """Test main loop exits gracefully when running=False"""
        with patch('time.sleep'):
            with patch.object(daemon_instance, 'discover_videos', return_value=[]):
                with patch.object(daemon_instance, 'process_batch') as mock_batch:
                    # Simulate shutdown after first iteration
                    def stop_after_one(*args, **kwargs):
                        daemon_instance.running = False

                    mock_batch.side_effect = stop_after_one
                    daemon_instance.run()

                    # Verify one scan cycle completed
                    assert daemon_instance.discover_videos.call_count >= 1

    def test_run_exception_in_loop_continues(self, daemon_instance):
        """Test daemon continues after exception in scan cycle"""
        call_count = 0

        def discover_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temporary error")
            # On second call, stop the loop and return empty
            daemon_instance.running = False
            return []

        with patch('time.sleep'):
            with patch.object(daemon_instance, 'discover_videos', side_effect=discover_side_effect) as mock_discover:
                with patch.object(daemon_instance, 'process_batch'):
                    daemon_instance.run()

                    # Verify continued after exception (called twice)
                    assert mock_discover.call_count == 2

    def test_run_sleep_interruption(self, daemon_instance):
        """Test loop doesn't execute when running=False"""
        with patch('time.sleep') as mock_sleep:
            with patch.object(daemon_instance, 'discover_videos', return_value=[]) as mock_discover:
                with patch.object(daemon_instance, 'process_batch'):
                    # Stop immediately
                    daemon_instance.running = False
                    daemon_instance.run()

                    # Should not enter the loop at all
                    assert mock_discover.call_count == 0
                    assert mock_sleep.call_count == 0


class TestConversionErrors:
    """Test error handling during video conversion"""

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

    def test_convert_video_timeout_expired(self, daemon_instance, tmp_path):
        """Test conversion timeout is handled gracefully"""
        import subprocess
        video = tmp_path / "huge_video.mp4"
        video.touch()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=['ffmpeg'], timeout=86400
            )

            result = daemon_instance.convert_video(video)
            assert result is False

    def test_convert_video_ffmpeg_failure(self, daemon_instance, tmp_path):
        """Test FFmpeg failure is handled"""
        video = tmp_path / "corrupt.mp4"
        video.touch()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Invalid data")

            result = daemon_instance.convert_video(video)
            assert result is False

    def test_convert_video_general_exception(self, daemon_instance, tmp_path):
        """Test unexpected exception during conversion"""
        video = tmp_path / "test.mp4"
        video.touch()

        with patch.object(daemon_instance, 'build_ffmpeg_command') as mock_build:
            mock_build.side_effect = Exception("Unexpected error")

            result = daemon_instance.convert_video(video)
            assert result is False


# ============================================================================
# PHASE 2: ERROR PATH TESTING (MEDIUM PRIORITY)
# ============================================================================

class TestDiscoveryErrors:
    """Test error handling in video discovery"""

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

    def test_discover_videos_nonexistent_directory(self, daemon_instance, tmp_path):
        """Test warning for nonexistent directory"""
        daemon_instance.config['directories'] = ['/nonexistent/path']

        videos = daemon_instance.discover_videos()
        assert len(videos) == 0

    def test_discover_videos_path_not_directory(self, daemon_instance, tmp_path):
        """Test handling when path is a file, not directory"""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.touch()
        daemon_instance.config['directories'] = [str(file_path)]

        videos = daemon_instance.discover_videos()
        assert len(videos) == 0

    def test_discover_videos_excludes_non_files(self, daemon_instance, tmp_path):
        """Test that only regular files are included"""
        video_dir = tmp_path / "videos"
        video_dir.mkdir()
        daemon_instance.config['directories'] = [str(video_dir)]

        # Create a video file
        video_file = video_dir / "test.mp4"
        video_file.touch()

        videos = daemon_instance.discover_videos()
        # Should include the file
        assert any('test.mp4' in str(v) for v in videos)

    def test_discover_videos_applies_exclude_patterns(self, daemon_instance, tmp_path):
        """Test exclude patterns are applied"""
        daemon_instance.config['directories'] = [str(tmp_path)]
        daemon_instance.config['processing']['exclude_patterns'] = ['*.backup.*']

        # Create test files
        (tmp_path / "good.mp4").touch()
        (tmp_path / "bad.backup.mp4").touch()

        videos = daemon_instance.discover_videos()

        assert any('good.mp4' in str(v) for v in videos)
        assert not any('backup' in str(v) for v in videos)

    def test_discover_videos_rejects_symlink_traversal(self, daemon_instance, tmp_path):
        """Test symlinks to outside directories are rejected"""
        watched_dir = tmp_path / "watched"
        watched_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()

        # Create symlink from watched to outside
        symlink = watched_dir / "link_to_outside"
        outside_video = outside_dir / "outside.mp4"
        outside_video.touch()
        symlink.symlink_to(outside_video)

        daemon_instance.config['directories'] = [str(watched_dir)]
        videos = daemon_instance.discover_videos()

        # Should not include symlinked file outside directory
        assert len(videos) == 0


class TestFileProcessingChecks:
    """Test file processing validation"""

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

    def test_should_process_already_processed(self, daemon_instance, tmp_path):
        """Test file already in processed_files is skipped"""
        video = tmp_path / "test.mp4"
        video.touch()

        file_hash = daemon_instance.get_file_hash(str(video))
        daemon_instance.processed_files.add(file_hash)

        assert daemon_instance.should_process(video) is False

    def test_should_process_currently_converting(self, daemon_instance, tmp_path):
        """Test file currently being converted is skipped"""
        video = tmp_path / "test.mp4"
        video.touch()

        file_hash = daemon_instance.get_file_hash(str(video))
        daemon_instance.converting.add(file_hash)

        assert daemon_instance.should_process(video) is False

    def test_should_process_output_exists(self, daemon_instance, tmp_path):
        """Test file with existing output is skipped"""
        video = tmp_path / "test.mp4"
        video.touch()
        output = tmp_path / "test.m4v"
        output.touch()

        assert daemon_instance.should_process(video) is False

    def test_should_process_already_m4v(self, daemon_instance, tmp_path):
        """Test .m4v files are skipped"""
        video = tmp_path / "test.m4v"
        video.touch()

        assert daemon_instance.should_process(video) is False

    def test_should_process_exceeds_size_limit(self, daemon_instance, tmp_path):
        """Test files exceeding size limit are skipped"""
        video = tmp_path / "huge.mp4"
        video.touch()

        with patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value = MagicMock(st_size=101 * 1024**3)  # 101 GB

            assert daemon_instance.should_process(video) is False

    def test_should_process_empty_file(self, daemon_instance, tmp_path):
        """Test empty files are skipped"""
        video = tmp_path / "empty.mp4"
        video.touch()

        assert daemon_instance.should_process(video) is False

    def test_should_process_stat_error(self, daemon_instance, tmp_path):
        """Test OSError during stat is handled"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"data")

        original_stat = Path.stat

        def stat_side_effect(self_path, *args, **kwargs):
            if self_path == video:
                raise OSError("Permission denied")
            return original_stat(self_path, *args, **kwargs)

        with patch.object(Path, 'stat', stat_side_effect):
            assert daemon_instance.should_process(video) is False


class TestConversionEdgeCases:
    """Test edge cases in video conversion"""

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

    def test_convert_video_file_disappeared(self, daemon_instance, tmp_path):
        """Test TOCTOU: file deleted between check and conversion"""
        video = tmp_path / "transient.mp4"
        video.touch()

        # Delete file before conversion
        video.unlink()

        result = daemon_instance.convert_video(video)
        assert result is False

    def test_convert_video_path_changed_toctou(self, daemon_instance, tmp_path):
        """Test TOCTOU: symlink changed to point outside"""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()

        video_link = allowed / "video.mp4"
        original_target = allowed / "real_video.mp4"
        original_target.touch()
        video_link.symlink_to(original_target)

        # Simulate path becoming unsafe during conversion
        with patch.object(daemon_instance, '_is_safe_path') as mock_safe:
            # First call (in should_process check) returns True
            # Second call (before conversion) returns False
            mock_safe.side_effect = [True, False]

            result = daemon_instance.convert_video(video_link)
            assert result is False

    def test_convert_video_temp_not_regular_file(self, daemon_instance, tmp_path):
        """Test conversion fails if temp output isn't a regular file"""
        video = tmp_path / "test.mp4"
        video.touch()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            with patch.object(Path, 'is_file', return_value=False):
                result = daemon_instance.convert_video(video)
                assert result is False

    def test_convert_video_preserve_timestamps_error(self, daemon_instance, tmp_path):
        """Test conversion succeeds even if timestamp preservation fails"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video data")
        work_dir = Path(daemon_instance.config['processing']['work_dir'])
        file_hash = daemon_instance.get_file_hash(str(video))
        temp_output = work_dir / f"{file_hash}_output.m4v"

        def fake_ffmpeg(*args, **kwargs):
            # Create the temp output file to simulate successful conversion
            temp_output.write_bytes(b"converted data")
            return MagicMock(returncode=0)

        with patch('subprocess.run', side_effect=fake_ffmpeg):
            with patch('os.utime') as mock_utime:
                mock_utime.side_effect = OSError("Permission denied")

                result = daemon_instance.convert_video(video)
                # Should succeed despite timestamp error
                assert result is True
                assert mock_utime.called

    def test_convert_video_delete_original_error(self, daemon_instance, tmp_path):
        """Test conversion succeeds even if delete original fails"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video data")
        daemon_instance.config['processing']['keep_original'] = False
        work_dir = Path(daemon_instance.config['processing']['work_dir'])
        file_hash = daemon_instance.get_file_hash(str(video))
        temp_output = work_dir / f"{file_hash}_output.m4v"

        def fake_ffmpeg(*args, **kwargs):
            # Create the temp output file to simulate successful conversion
            temp_output.write_bytes(b"converted data")
            return MagicMock(returncode=0)

        original_unlink = Path.unlink

        def selective_unlink(self_path, *args, **kwargs):
            if self_path == video:
                raise OSError("Permission denied")
            return original_unlink(self_path, *args, **kwargs)

        with patch('subprocess.run', side_effect=fake_ffmpeg):
            with patch.object(Path, 'unlink', selective_unlink):
                result = daemon_instance.convert_video(video)
                # Should log error but still mark as processed
                assert result is True


# ============================================================================
# PHASE 3: VALIDATION & CLEANUP TESTING (LOW-MEDIUM PRIORITY)
# ============================================================================

class TestConfigValidationExtended:
    """Test additional configuration validation scenarios"""

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

    def test_invalid_extension_rejected(self, minimal_config):
        """Test invalid file extension is rejected"""
        minimal_config['processing']['include_extensions'] = ['exe', 'mp4']

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="Invalid extension"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_relative_state_dir_rejected(self, minimal_config):
        """Test relative state_dir path is rejected"""
        minimal_config['processing']['state_dir'] = './state'

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="state_dir"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)

    def test_relative_log_file_rejected(self, minimal_config):
        """Test relative log_file path is rejected"""
        minimal_config['daemon']['log_file'] = './daemon.log'

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            import yaml
            yaml.dump(minimal_config, f)
            f.flush()
            try:
                with pytest.raises(ConfigValidationError, match="log_file"):
                    VideoConverterDaemon(f.name)
            finally:
                os.unlink(f.name)


class TestProcessedFilesErrorHandling:
    """Test error handling when loading/saving processed files"""

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

    def test_load_processed_files_invalid_dict_hash(self, temp_config):
        """Test invalid hash in dict format triggers reset"""
        config_file, state_dir = temp_config

        # Create invalid dict format with short hash
        db_file = state_dir / 'processed.json'
        invalid_data = {
            "too_short_hash": {"timestamp": 123, "duration_seconds": 10}
        }
        with open(db_file, 'w') as f:
            json.dump(invalid_data, f)

        daemon = VideoConverterDaemon(str(config_file))
        # Should reset to empty on invalid hash
        assert len(daemon.processed_files) == 0

    def test_load_processed_files_invalid_format_neither_dict_nor_list(self, temp_config):
        """Test invalid format (not dict/list) triggers reset"""
        config_file, state_dir = temp_config

        # Create invalid format
        db_file = state_dir / 'processed.json'
        with open(db_file, 'w') as f:
            json.dump("invalid_string_format", f)

        daemon = VideoConverterDaemon(str(config_file))
        assert len(daemon.processed_files) == 0

    def test_save_processed_files_cleanup_on_error(self, temp_config):
        """Test temp file cleanup on save error"""
        config_file, state_dir = temp_config
        daemon = VideoConverterDaemon(str(config_file))

        daemon.processed_files.add('a' * 64)

        with patch('os.open') as mock_open:
            mock_open.side_effect = OSError("Disk full")

            with pytest.raises(OSError):
                daemon.save_processed_files()

            # Verify temp file was cleaned up
            temp_files = list(state_dir.glob('*.json.tmp'))
            assert len(temp_files) == 0


class TestPathSecurityExtended:
    """Test additional path security scenarios"""

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

    def test_is_safe_path_with_nonexistent_file(self, daemon_instance):
        """Test path security with nonexistent file"""
        nonexistent = Path("/tmp/nonexistent_file_xyz.mp4")

        is_safe = daemon_instance._is_safe_path(nonexistent, ["/tmp"])
        assert is_safe is False

    def test_is_safe_path_with_permission_error(self, daemon_instance, tmp_path):
        """Test path security when resolve() fails with permission error"""
        restricted = tmp_path / "restricted.mp4"
        restricted.touch()

        with patch.object(Path, 'resolve') as mock_resolve:
            mock_resolve.side_effect = OSError("Permission denied")

            is_safe = daemon_instance._is_safe_path(restricted, [str(tmp_path)])
            assert is_safe is False


class TestBatchProcessingErrors:
    """Test error handling in batch processing"""

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

    def test_process_batch_empty_list(self, daemon_instance):
        """Test empty video list is handled"""
        daemon_instance.process_batch([])
        # Should return without error

    def test_process_batch_future_exception(self, daemon_instance, tmp_path):
        """Test exception in worker thread is handled"""
        video = tmp_path / "test.mp4"
        video.touch()

        with patch.object(daemon_instance, 'convert_video') as mock_convert:
            mock_convert.side_effect = Exception("Worker failure")

            # Should handle exception gracefully
            daemon_instance.process_batch([video])
            # No assertion needed, just verify no crash


class TestMainEntryPoint:
    """Test main entry point argument parsing and error handling"""

    def test_main_config_not_found(self, monkeypatch, capsys):
        """Test main() handles missing config file"""
        monkeypatch.setattr(sys, 'argv', ['daemon', '--config', '/nonexistent.yaml'])

        from video_converter_daemon import main
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert 'Config file not found' in captured.out

    def test_main_validate_config_mode(self, monkeypatch, tmp_path, capsys):
        """Test main() with --validate-config flag"""
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

        monkeypatch.setattr(sys, 'argv', ['daemon', '--config', str(config_file), '--validate-config'])

        from video_converter_daemon import main
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert 'Configuration is valid' in captured.out

    def test_main_config_validation_error(self, monkeypatch, tmp_path, capsys):
        """Test main() handles ConfigValidationError"""
        bad_config = tmp_path / "bad_config.yaml"
        with open(bad_config, 'w') as f:
            import yaml
            yaml.dump({'conversion': {'codec': 'invalid'}}, f)

        monkeypatch.setattr(sys, 'argv', ['daemon', '--config', str(bad_config)])

        from video_converter_daemon import main
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert 'Configuration error' in captured.out


# ============================================================================
# REMOTE MODE TESTS (all mock paramiko — no real SSH)
# ============================================================================


def _make_remote_config(tmp_path, remote_overrides=None):
    """Helper to create a config dict with remote section enabled."""
    work_dir = tmp_path / "work"
    work_dir.mkdir(exist_ok=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "daemon.log"

    remote = {
        'enabled': True,
        'host': 'nas01',
        'user': 'root',
        'port': 22,
        'key_file': '/root/.ssh/id_ed25519',
        'directories': ['/media', '/mnt/smallmedia'],
        'connect_timeout': 30,
        'transfer_timeout': 3600,
    }
    if remote_overrides:
        remote.update(remote_overrides)

    config = {
        'directories': [str(tmp_path)],
        'remote': remote,
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
            'include_extensions': ['mp4', 'mkv'],
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
    return config


def _write_config(tmp_path, config):
    """Write config dict to a YAML file and return its path."""
    import yaml
    config_file = tmp_path / "config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)
    return str(config_file)


class TestRemoteConfigValidation:
    """Test remote configuration validation"""

    def test_valid_remote_config(self, tmp_path):
        """Test valid remote config passes validation"""
        config = _make_remote_config(tmp_path)
        config_file = _write_config(tmp_path, config)
        daemon = VideoConverterDaemon(config_file, validate_only=True)
        assert daemon._is_remote_mode() is True

    def test_remote_missing_host(self, tmp_path):
        """Test missing remote.host is rejected"""
        config = _make_remote_config(tmp_path, {'host': ''})
        config_file = _write_config(tmp_path, config)
        with pytest.raises(ConfigValidationError, match="remote.host"):
            VideoConverterDaemon(config_file, validate_only=True)

    def test_remote_missing_user(self, tmp_path):
        """Test missing remote.user is rejected"""
        config = _make_remote_config(tmp_path, {'user': ''})
        config_file = _write_config(tmp_path, config)
        with pytest.raises(ConfigValidationError, match="remote.user"):
            VideoConverterDaemon(config_file, validate_only=True)

    def test_remote_bad_port(self, tmp_path):
        """Test invalid remote.port is rejected"""
        config = _make_remote_config(tmp_path, {'port': 70000})
        config_file = _write_config(tmp_path, config)
        with pytest.raises(ConfigValidationError, match="remote.port"):
            VideoConverterDaemon(config_file, validate_only=True)

    def test_remote_port_zero(self, tmp_path):
        """Test remote.port=0 is rejected"""
        config = _make_remote_config(tmp_path, {'port': 0})
        config_file = _write_config(tmp_path, config)
        with pytest.raises(ConfigValidationError, match="remote.port"):
            VideoConverterDaemon(config_file, validate_only=True)

    def test_remote_relative_key_file(self, tmp_path):
        """Test relative key_file path is rejected"""
        config = _make_remote_config(tmp_path, {'key_file': './id_rsa'})
        config_file = _write_config(tmp_path, config)
        with pytest.raises(ConfigValidationError, match="remote.key_file"):
            VideoConverterDaemon(config_file, validate_only=True)

    def test_remote_empty_directories(self, tmp_path):
        """Test empty remote.directories is rejected"""
        config = _make_remote_config(tmp_path, {'directories': []})
        config_file = _write_config(tmp_path, config)
        with pytest.raises(ConfigValidationError, match="remote.directories"):
            VideoConverterDaemon(config_file, validate_only=True)

    def test_remote_relative_directory(self, tmp_path):
        """Test relative remote directory path is rejected"""
        config = _make_remote_config(tmp_path, {'directories': ['relative/path']})
        config_file = _write_config(tmp_path, config)
        with pytest.raises(ConfigValidationError, match="remote.directories"):
            VideoConverterDaemon(config_file, validate_only=True)

    def test_remote_connect_timeout_too_low(self, tmp_path):
        """Test connect_timeout < 1 is rejected"""
        config = _make_remote_config(tmp_path, {'connect_timeout': 0})
        config_file = _write_config(tmp_path, config)
        with pytest.raises(ConfigValidationError, match="remote.connect_timeout"):
            VideoConverterDaemon(config_file, validate_only=True)

    def test_remote_transfer_timeout_too_low(self, tmp_path):
        """Test transfer_timeout < 60 is rejected"""
        config = _make_remote_config(tmp_path, {'transfer_timeout': 10})
        config_file = _write_config(tmp_path, config)
        with pytest.raises(ConfigValidationError, match="remote.transfer_timeout"):
            VideoConverterDaemon(config_file, validate_only=True)

    def test_remote_disabled_skips_validation(self, tmp_path):
        """Test disabled remote section doesn't trigger remote validation"""
        config = _make_remote_config(tmp_path, {'enabled': False, 'host': ''})
        config_file = _write_config(tmp_path, config)
        # Should not raise — remote validation skipped when enabled=False
        daemon = VideoConverterDaemon(config_file, validate_only=True)
        assert daemon._is_remote_mode() is False


class TestRemotePathValidation:
    """Test remote path validation via validate_remote_path"""

    def test_normal_path_accepted(self):
        """Test normal path within allowed dir is accepted"""
        from sftp_ops import validate_remote_path
        assert validate_remote_path('/media/movies/file.mkv', ['/media']) is True

    def test_traversal_rejected(self):
        """Test path traversal with '..' is rejected"""
        from sftp_ops import validate_remote_path
        assert validate_remote_path('/media/../etc/passwd', ['/media']) is False

    def test_relative_path_rejected(self):
        """Test relative path is rejected"""
        from sftp_ops import validate_remote_path
        assert validate_remote_path('media/file.mkv', ['/media']) is False

    def test_exact_dir_match(self):
        """Test exact directory match is accepted"""
        from sftp_ops import validate_remote_path
        assert validate_remote_path('/media', ['/media']) is True

    def test_outside_allowed_dir(self):
        """Test path outside allowed dirs is rejected"""
        from sftp_ops import validate_remote_path
        assert validate_remote_path('/etc/passwd', ['/media']) is False

    def test_multiple_allowed_dirs(self):
        """Test path in second allowed dir is accepted"""
        from sftp_ops import validate_remote_path
        assert validate_remote_path('/mnt/data/file.mp4', ['/media', '/mnt/data']) is True

    def test_partial_dir_name_rejected(self):
        """Test that /media2 is not matched by /media"""
        from sftp_ops import validate_remote_path
        assert validate_remote_path('/media2/file.mp4', ['/media']) is False


class TestRemoteDiscovery:
    """Test remote video discovery with mocked SFTP"""

    @pytest.fixture
    def remote_daemon(self, tmp_path):
        """Create a daemon with remote mode and mocked SFTP connection"""
        config = _make_remote_config(tmp_path)
        config_file = _write_config(tmp_path, config)

        with patch('video_converter_daemon.VideoConverterDaemon._init_remote'):
            daemon = VideoConverterDaemon(config_file)

        # Set up mock SFTP connection
        daemon._sftp_conn = MagicMock()
        return daemon

    def test_discover_remote_videos(self, remote_daemon):
        """Test remote discovery returns validated file list"""
        with patch('sftp_ops.sftp_list_videos') as mock_list:
            mock_list.return_value = [
                '/media/movies/film.mkv',
                '/media/shows/ep01.mp4',
            ]
            with patch('sftp_ops.validate_remote_path', return_value=True):
                videos = remote_daemon.discover_videos()

                assert len(videos) == 2
                assert '/media/movies/film.mkv' in videos

    def test_discover_remote_filters_unsafe_paths(self, remote_daemon):
        """Test remote discovery filters out paths failing validation"""
        with patch('sftp_ops.sftp_list_videos') as mock_list:
            mock_list.return_value = [
                '/media/good.mkv',
                '/etc/passwd',
            ]
            with patch('sftp_ops.validate_remote_path') as mock_validate:
                mock_validate.side_effect = lambda p, d: p.startswith('/media')
                videos = remote_daemon.discover_videos()

                assert len(videos) == 1
                assert '/media/good.mkv' in videos

    def test_discover_remote_sftp_error(self, remote_daemon):
        """Test remote discovery handles SFTP errors gracefully"""
        remote_daemon._sftp_conn.ensure_connected.side_effect = Exception("Connection lost")

        videos = remote_daemon.discover_videos()
        assert len(videos) == 0


class TestRemoteShouldProcess:
    """Test remote should_process logic"""

    @pytest.fixture
    def remote_daemon(self, tmp_path):
        """Create a daemon with remote mode and mocked SFTP"""
        config = _make_remote_config(tmp_path)
        config_file = _write_config(tmp_path, config)

        with patch('video_converter_daemon.VideoConverterDaemon._init_remote'):
            daemon = VideoConverterDaemon(config_file)

        daemon._sftp_conn = MagicMock()
        return daemon

    def test_already_processed_skipped(self, remote_daemon):
        """Test already-processed file is skipped"""
        video = '/media/movies/film.mkv'
        file_hash = remote_daemon.get_file_hash(video)
        remote_daemon.processed_files.add(file_hash)

        assert remote_daemon.should_process(video) is False

    def test_m4v_skipped(self, remote_daemon):
        """Test .m4v files are skipped"""
        assert remote_daemon.should_process('/media/already.m4v') is False

    def test_output_exists_skipped(self, remote_daemon):
        """Test file with existing output on remote is skipped"""
        with patch('sftp_ops.sftp_exists', return_value=True):
            with patch('sftp_ops.sftp_stat', return_value=(1024, 1000.0)):
                assert remote_daemon.should_process('/media/film.mkv') is False

    def test_oversized_file_skipped(self, remote_daemon):
        """Test oversized remote file is skipped"""
        with patch('sftp_ops.sftp_exists', return_value=False):
            with patch('sftp_ops.sftp_stat', return_value=(200 * 1024**3, 1000.0)):
                assert remote_daemon.should_process('/media/huge.mkv') is False

    def test_empty_file_skipped(self, remote_daemon):
        """Test empty remote file is skipped"""
        with patch('sftp_ops.sftp_exists', return_value=False):
            with patch('sftp_ops.sftp_stat', return_value=(0, 1000.0)):
                assert remote_daemon.should_process('/media/empty.mkv') is False

    def test_valid_file_accepted(self, remote_daemon):
        """Test valid remote file passes should_process"""
        with patch('sftp_ops.sftp_exists', return_value=False):
            with patch('sftp_ops.sftp_stat', return_value=(1024 * 1024, 1000.0)):
                assert remote_daemon.should_process('/media/good.mkv') is True


class TestRemoteConversion:
    """Test remote conversion workflow with mocked SFTP and FFmpeg"""

    @pytest.fixture
    def remote_daemon(self, tmp_path):
        """Create a daemon with remote mode and mocked SFTP"""
        config = _make_remote_config(tmp_path)
        config_file = _write_config(tmp_path, config)

        with patch('video_converter_daemon.VideoConverterDaemon._init_remote'):
            daemon = VideoConverterDaemon(config_file)

        daemon._sftp_conn = MagicMock()
        return daemon

    def test_remote_conversion_happy_path(self, remote_daemon, tmp_path):
        """Test successful remote conversion: download, convert, upload"""
        work_dir = Path(remote_daemon.config['processing']['work_dir'])
        video_path = '/media/movies/film.mkv'
        file_hash = remote_daemon.get_file_hash(video_path)

        def fake_download(conn, remote, local, timeout):
            Path(local).write_bytes(b"video data")

        def fake_ffmpeg(*args, **kwargs):
            output_file = work_dir / f"{file_hash}_output.m4v"
            output_file.write_bytes(b"converted data")
            return MagicMock(returncode=0)

        with patch('sftp_ops.sftp_download', side_effect=fake_download):
            with patch('sftp_ops.validate_remote_path', return_value=True):
                with patch('subprocess.run', side_effect=fake_ffmpeg):
                    with patch('sftp_ops.sftp_upload') as mock_upload:
                        with patch('sftp_ops.sftp_stat', return_value=(1024, 1000.0)):
                            with patch('sftp_ops.sftp_utime'):
                                result = remote_daemon.convert_video(video_path)

                                assert result is True
                                mock_upload.assert_called_once()
                                assert file_hash in remote_daemon.processed_files

    def test_remote_conversion_download_fails(self, remote_daemon):
        """Test remote conversion handles download failure"""
        from sftp_ops import SFTPOperationError

        with patch('sftp_ops.validate_remote_path', return_value=True):
            with patch('sftp_ops.sftp_download') as mock_dl:
                mock_dl.side_effect = SFTPOperationError("Download failed")

                result = remote_daemon.convert_video('/media/movies/film.mkv')
                assert result is False

    def test_remote_conversion_ffmpeg_fails(self, remote_daemon, tmp_path):
        """Test remote conversion handles FFmpeg failure"""
        def fake_download(conn, remote, local, timeout):
            Path(local).write_bytes(b"video data")

        with patch('sftp_ops.validate_remote_path', return_value=True):
            with patch('sftp_ops.sftp_download', side_effect=fake_download):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(returncode=1, stderr="FFmpeg error")

                    result = remote_daemon.convert_video('/media/movies/film.mkv')
                    assert result is False

    def test_remote_conversion_upload_fails(self, remote_daemon, tmp_path):
        """Test remote conversion handles upload failure and cleans up"""
        from sftp_ops import SFTPOperationError
        work_dir = Path(remote_daemon.config['processing']['work_dir'])
        video_path = '/media/movies/film.mkv'
        file_hash = remote_daemon.get_file_hash(video_path)

        def fake_download(conn, remote, local, timeout):
            Path(local).write_bytes(b"video data")

        def fake_ffmpeg(*args, **kwargs):
            output_file = work_dir / f"{file_hash}_output.m4v"
            output_file.write_bytes(b"converted data")
            return MagicMock(returncode=0)

        with patch('sftp_ops.validate_remote_path', return_value=True):
            with patch('sftp_ops.sftp_download', side_effect=fake_download):
                with patch('subprocess.run', side_effect=fake_ffmpeg):
                    with patch('sftp_ops.sftp_upload') as mock_upload:
                        mock_upload.side_effect = SFTPOperationError("Upload failed")

                        result = remote_daemon.convert_video(video_path)
                        assert result is False

                        # Verify temp files cleaned up
                        local_input = work_dir / f"{file_hash}_input.mkv"
                        local_output = work_dir / f"{file_hash}_output.m4v"
                        assert not local_input.exists()
                        assert not local_output.exists()

    def test_remote_conversion_path_validation_fails(self, remote_daemon):
        """Test remote conversion rejects invalid paths"""
        with patch('sftp_ops.validate_remote_path', return_value=False):
            result = remote_daemon.convert_video('/media/../etc/passwd')
            assert result is False

    def test_remote_dry_run(self, remote_daemon):
        """Test remote dry-run mode marks processed without actual work"""
        remote_daemon.dry_run = True
        video_path = '/media/movies/film.mkv'

        result = remote_daemon.convert_video(video_path)
        assert result is True

        file_hash = remote_daemon.get_file_hash(video_path)
        assert file_hash in remote_daemon.processed_files
        assert remote_daemon.conversion_times[file_hash].get('dry_run') is True


class TestLocalModeUnchanged:
    """Verify local mode is not affected by remote mode additions"""

    @pytest.fixture
    def local_daemon(self, tmp_path):
        """Create a daemon without remote config (local mode)"""
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

    def test_local_mode_is_not_remote(self, local_daemon):
        """Test daemon without remote config is in local mode"""
        assert local_daemon._is_remote_mode() is False
        assert local_daemon._sftp_conn is None

    def test_local_discover_videos_works(self, local_daemon, tmp_path):
        """Test local discovery still works unchanged"""
        video = tmp_path / "test.mp4"
        video.touch()

        videos = local_daemon.discover_videos()
        assert any('test.mp4' in str(v) for v in videos)

    def test_local_should_process_works(self, local_daemon, tmp_path):
        """Test local should_process still works unchanged"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"data")

        assert local_daemon.should_process(video) is True

    def test_local_dry_run_conversion(self, tmp_path):
        """Test local dry-run conversion still works"""
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

        daemon = VideoConverterDaemon(str(config_file), dry_run=True)
        video = tmp_path / "test.mp4"
        video.write_bytes(b"video data")

        result = daemon.convert_video(video)
        assert result is True

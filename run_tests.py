#!/usr/bin/env python3
"""Manual test runner for Video Converter Daemon tests"""

import sys
import os
import tempfile
import json
import traceback
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from video_converter_daemon import (
    VideoConverterDaemon,
    ConfigValidationError,
    parse_arguments,
)

class TestRunner:
    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures = []

    def assert_equal(self, actual, expected, msg=""):
        """Assert that actual equals expected"""
        if actual != expected:
            raise AssertionError(f"Expected {expected!r}, got {actual!r}. {msg}")

    def assert_true(self, value, msg=""):
        """Assert that value is True"""
        if not value:
            raise AssertionError(f"Expected True, got {value!r}. {msg}")

    def assert_false(self, value, msg=""):
        """Assert that value is False"""
        if value:
            raise AssertionError(f"Expected False, got {value!r}. {msg}")

    def assert_in(self, item, container, msg=""):
        """Assert that item is in container"""
        if item not in container:
            raise AssertionError(f"Expected {item!r} in {container!r}. {msg}")

    def assert_raises(self, exception_type, callable_obj, *args, **kwargs):
        """Assert that callable raises exception_type"""
        try:
            callable_obj(*args, **kwargs)
            raise AssertionError(f"Expected {exception_type.__name__} but nothing was raised")
        except exception_type:
            pass  # Expected

    def run_test(self, test_func, test_name):
        """Run a single test and track results"""
        try:
            test_func()
            self.tests_passed += 1
            print(f"✓ {test_name}")
        except Exception as e:
            self.tests_failed += 1
            self.failures.append((test_name, e, traceback.format_exc()))
            print(f"✗ {test_name}")

    def create_temp_config(self):
        """Create a temporary config for testing"""
        tmp_path = Path(tempfile.mkdtemp())
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
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        return config_file, state_dir, tmp_path

    # ============ Tests ============

    def test_config_validation_invalid_codec(self):
        """Test that invalid codec is rejected"""
        config_file, _, _ = self.create_temp_config()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config = yaml.safe_load(open(config_file))
            config['conversion']['codec'] = 'invalid_codec'
            yaml.dump(config, f)
            f.flush()
            try:
                self.assert_raises(ConfigValidationError, VideoConverterDaemon, f.name)
            finally:
                os.unlink(f.name)

    def test_config_validation_extra_options_disabled(self):
        """Test that extra_options are disabled"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_file, _, tmp_path = self.create_temp_config()
            config = yaml.safe_load(open(config_file))
            config['conversion']['extra_options'] = ['-movflags', '+faststart']
            yaml.dump(config, f)
            f.flush()
            try:
                self.assert_raises(ConfigValidationError, VideoConverterDaemon, f.name)
            finally:
                os.unlink(f.name)

    def test_config_validation_invalid_preset(self):
        """Test that invalid preset is rejected"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_file, _, _ = self.create_temp_config()
            config = yaml.safe_load(open(config_file))
            config['conversion']['preset'] = 'invalid_preset'
            yaml.dump(config, f)
            f.flush()
            try:
                self.assert_raises(ConfigValidationError, VideoConverterDaemon, f.name)
            finally:
                os.unlink(f.name)

    def test_config_validation_invalid_crf(self):
        """Test that invalid CRF is rejected"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_file, _, _ = self.create_temp_config()
            config = yaml.safe_load(open(config_file))
            config['conversion']['crf'] = 99
            yaml.dump(config, f)
            f.flush()
            try:
                self.assert_raises(ConfigValidationError, VideoConverterDaemon, f.name)
            finally:
                os.unlink(f.name)

    def test_config_validation_invalid_max_workers(self):
        """Test that max_workers > 8 is rejected"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_file, _, _ = self.create_temp_config()
            config = yaml.safe_load(open(config_file))
            config['daemon']['max_workers'] = 10
            yaml.dump(config, f)
            f.flush()
            try:
                self.assert_raises(ConfigValidationError, VideoConverterDaemon, f.name)
            finally:
                os.unlink(f.name)

    def test_config_validation_invalid_scan_interval(self):
        """Test that scan_interval < 30 is rejected"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_file, _, _ = self.create_temp_config()
            config = yaml.safe_load(open(config_file))
            config['daemon']['scan_interval'] = 10
            yaml.dump(config, f)
            f.flush()
            try:
                self.assert_raises(ConfigValidationError, VideoConverterDaemon, f.name)
            finally:
                os.unlink(f.name)

    def test_save_and_load_processed_files(self):
        """Test saving and loading processed files"""
        config_file, state_dir, _ = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        # Add hash and save
        test_hash = 'a' * 64
        daemon.processed_files.add(test_hash)
        daemon.save_processed_files()

        # Verify file exists
        db_file = state_dir / 'processed.json'
        self.assert_true(db_file.exists())

        # Create new daemon and verify hash is loaded
        daemon2 = VideoConverterDaemon(str(config_file))
        self.assert_in(test_hash, daemon2.processed_files)

    def test_load_invalid_processed_files(self):
        """Test that invalid processed files are handled"""
        config_file, state_dir, _ = self.create_temp_config()

        # Create invalid processed.json
        db_file = state_dir / 'processed.json'
        with open(db_file, 'w') as f:
            json.dump(['invalid_hash_too_short'], f)

        # Should reset to empty on invalid data
        daemon = VideoConverterDaemon(str(config_file))
        self.assert_equal(len(daemon.processed_files), 0)

    def test_conversion_timing_saved(self):
        """Test that conversion timing is saved"""
        config_file, state_dir, _ = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        test_hash = 'a' * 64
        daemon.processed_files.add(test_hash)
        daemon.conversion_times[test_hash] = {
            "timestamp": 1234567890,
            "duration_seconds": 42
        }
        daemon.save_processed_files()

        # Verify
        db_file = state_dir / 'processed.json'
        with open(db_file, 'r') as f:
            data = json.load(f)

        self.assert_in(test_hash, data)
        self.assert_equal(data[test_hash]['duration_seconds'], 42)
        self.assert_equal(data[test_hash]['timestamp'], 1234567890)

    def test_load_old_format_processed_files(self):
        """Test backward compatibility with old format"""
        config_file, state_dir, _ = self.create_temp_config()

        # Create old format
        db_file = state_dir / 'processed.json'
        old_format = ['a' * 64, 'b' * 64]
        with open(db_file, 'w') as f:
            json.dump(old_format, f)

        # Should load successfully
        daemon = VideoConverterDaemon(str(config_file))
        self.assert_equal(len(daemon.processed_files), 2)
        self.assert_in('a' * 64, daemon.processed_files)

    def test_file_hash_is_sha256(self):
        """Test that file hash is SHA-256"""
        config_file, _, _ = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        hash_value = daemon.get_file_hash("/some/file.mp4")
        self.assert_equal(len(hash_value), 64)
        self.assert_true(all(c in '0123456789abcdef' for c in hash_value))

    def test_file_hash_deterministic(self):
        """Test that same file produces same hash"""
        config_file, _, _ = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        hash1 = daemon.get_file_hash("/some/file.mp4")
        hash2 = daemon.get_file_hash("/some/file.mp4")
        self.assert_equal(hash1, hash2)

    def test_file_hash_different_paths(self):
        """Test that different paths produce different hashes"""
        config_file, _, _ = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        hash1 = daemon.get_file_hash("/video1.mp4")
        hash2 = daemon.get_file_hash("/video2.mp4")
        self.assert_equal(hash1 == hash2, False)

    def test_safe_path_within_allowed(self):
        """Test that path within allowed dir is accepted"""
        config_file, _, tmp_path = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        test_file = tmp_path / "video.mp4"
        test_file.touch()

        is_safe = daemon._is_safe_path(test_file, [str(tmp_path)])
        self.assert_true(is_safe)

    def test_safe_path_outside_allowed(self):
        """Test that path outside allowed dir is rejected"""
        config_file, _, tmp_path = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        disallowed_file = tmp_path / "outside.mp4"
        disallowed_file.touch()

        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()

        is_safe = daemon._is_safe_path(disallowed_file, [str(allowed_dir)])
        self.assert_false(is_safe)

    def test_ffmpeg_command_includes_codec(self):
        """Test FFmpeg command includes codec"""
        config_file, _, tmp_path = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon.build_ffmpeg_command(input_file, output_file)

        self.assert_in('ffmpeg', cmd)
        self.assert_in('-c:v', cmd)
        self.assert_in('libx264', cmd)

    def test_ffmpeg_command_includes_crf(self):
        """Test FFmpeg command includes CRF"""
        config_file, _, tmp_path = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon.build_ffmpeg_command(input_file, output_file)

        self.assert_in('-crf', cmd)
        crf_index = cmd.index('-crf')
        self.assert_equal(cmd[crf_index + 1], '23')

    def test_ffmpeg_command_includes_preset(self):
        """Test FFmpeg command includes preset"""
        config_file, _, tmp_path = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon.build_ffmpeg_command(input_file, output_file)

        self.assert_in('-preset', cmd)
        preset_index = cmd.index('-preset')
        self.assert_equal(cmd[preset_index + 1], 'medium')

    def test_ffmpeg_command_includes_audio(self):
        """Test FFmpeg command includes audio settings"""
        config_file, _, tmp_path = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon.build_ffmpeg_command(input_file, output_file)

        self.assert_in('-c:a', cmd)
        self.assert_in('aac', cmd)
        self.assert_in('-b:a', cmd)
        self.assert_in('128k', cmd)

    def test_ffmpeg_command_includes_nostdin(self):
        """Test FFmpeg command includes -nostdin flag"""
        config_file, _, tmp_path = self.create_temp_config()
        daemon = VideoConverterDaemon(str(config_file))

        input_file = tmp_path / "input.mp4"
        input_file.touch()
        output_file = tmp_path / "output.m4v"

        cmd = daemon.build_ffmpeg_command(input_file, output_file)

        self.assert_in('-nostdin', cmd)

    def run_all_tests(self):
        """Run all tests"""
        print("=" * 60)
        print("Video Converter Daemon - Manual Test Suite")
        print("=" * 60)
        print()

        # Config validation tests
        print("Config Validation Tests:")
        self.run_test(self.test_config_validation_invalid_codec, "Invalid codec rejected")
        self.run_test(self.test_config_validation_extra_options_disabled, "Extra options disabled")
        self.run_test(self.test_config_validation_invalid_preset, "Invalid preset rejected")
        self.run_test(self.test_config_validation_invalid_crf, "Invalid CRF rejected")
        self.run_test(self.test_config_validation_invalid_max_workers, "Invalid max_workers rejected")
        self.run_test(self.test_config_validation_invalid_scan_interval, "Invalid scan_interval rejected")
        print()

        # Processed files tests
        print("Processed Files Tests:")
        self.run_test(self.test_save_and_load_processed_files, "Save and load processed files")
        self.run_test(self.test_load_invalid_processed_files, "Invalid processed files handled")
        print()

        # Timing tests
        print("Conversion Timing Tests:")
        self.run_test(self.test_conversion_timing_saved, "Conversion timing saved")
        self.run_test(self.test_load_old_format_processed_files, "Old format backward compatible")
        print()

        # File hash tests
        print("File Hash Tests:")
        self.run_test(self.test_file_hash_is_sha256, "File hash is SHA-256")
        self.run_test(self.test_file_hash_deterministic, "File hash deterministic")
        self.run_test(self.test_file_hash_different_paths, "Different paths produce different hashes")
        print()

        # Path security tests
        print("Path Security Tests:")
        self.run_test(self.test_safe_path_within_allowed, "Safe path within allowed")
        self.run_test(self.test_safe_path_outside_allowed, "Safe path outside allowed")
        print()

        # FFmpeg command tests
        print("FFmpeg Command Tests:")
        self.run_test(self.test_ffmpeg_command_includes_codec, "FFmpeg command includes codec")
        self.run_test(self.test_ffmpeg_command_includes_crf, "FFmpeg command includes CRF")
        self.run_test(self.test_ffmpeg_command_includes_preset, "FFmpeg command includes preset")
        self.run_test(self.test_ffmpeg_command_includes_audio, "FFmpeg command includes audio")
        self.run_test(self.test_ffmpeg_command_includes_nostdin, "FFmpeg command includes -nostdin")
        print()

        # Summary
        print("=" * 60)
        print(f"Results: {self.tests_passed} passed, {self.tests_failed} failed")
        print("=" * 60)

        if self.failures:
            print("\nFailed Tests:")
            for test_name, error, trace in self.failures:
                print(f"\n{test_name}:")
                print(f"  {error}")

        return self.tests_failed == 0


if __name__ == "__main__":
    runner = TestRunner()
    success = runner.run_all_tests()
    sys.exit(0 if success else 1)

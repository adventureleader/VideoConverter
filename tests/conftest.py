"""Pytest configuration and fixtures for Video Converter Daemon tests"""

import pytest
import tempfile
from pathlib import Path
import yaml


@pytest.fixture
def tmp_project_dir():
    """Create a temporary project directory structure"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create necessary subdirectories
        (tmp_path / "work").mkdir()
        (tmp_path / "state").mkdir()
        (tmp_path / "logs").mkdir()
        (tmp_path / "videos").mkdir()

        yield tmp_path


@pytest.fixture
def minimal_config(tmp_project_dir):
    """Create a minimal valid configuration"""
    config = {
        'directories': [str(tmp_project_dir / "videos")],
        'conversion': {
            'codec': 'libx264',
            'crf': 23,
            'preset': 'medium',
            'audio_codec': 'aac',
            'audio_bitrate': '128k',
            'extra_options': [],
        },
        'processing': {
            'work_dir': str(tmp_project_dir / "work"),
            'state_dir': str(tmp_project_dir / "state"),
            'include_extensions': ['mp4', 'mkv'],
            'exclude_patterns': ['*.backup.*', '*_temp_*'],
            'keep_original': True,
        },
        'daemon': {
            'log_level': 'INFO',
            'log_file': str(tmp_project_dir / "logs" / "daemon.log"),
            'scan_interval': 30,
            'max_workers': 2,
        },
    }
    return config


@pytest.fixture
def config_file(tmp_project_dir, minimal_config):
    """Create a config file from minimal config"""
    config_path = tmp_project_dir / "config.yaml"
    with open(config_path, 'w') as f:
        yaml.dump(minimal_config, f)
    return config_path


@pytest.fixture
def test_video_file(tmp_project_dir):
    """Create a dummy video file for testing"""
    video_path = tmp_project_dir / "videos" / "test_video.mp4"
    # Create a minimal MP4-like file (just for testing, not a real video)
    video_path.write_bytes(b"ftypisom\x00\x00\x00\x00")
    return video_path

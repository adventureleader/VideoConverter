#!/usr/bin/env python3
"""
Video Converter Daemon
Automatically discovers and converts video files to .m4v format
Designed to run locally on nas01
"""

import os
import sys
import time
import yaml
import logging
import subprocess
import hashlib
import shutil
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Set
import signal
import json

class VideoConverterDaemon:
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize the daemon with configuration"""
        self.running = True
        self.config = self.load_config(config_path)
        self.setup_logging()
        self.processed_files = self.load_processed_files()
        self.converting = set()

        # Create work directory
        work_dir = Path(self.config['processing']['work_dir'])
        work_dir.mkdir(parents=True, exist_ok=True)

        # Register signal handlers
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        signal.signal(signal.SIGINT, self.handle_shutdown)

        self.logger.info("Video Converter Daemon initialized")

    def load_config(self, config_path: str) -> dict:
        """Load configuration from YAML file"""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def setup_logging(self):
        """Configure logging"""
        log_file = self.config['daemon']['log_file']
        log_dir = os.path.dirname(log_file)

        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        log_level = getattr(logging, self.config['daemon']['log_level'])

        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('VideoConverter')

    def load_processed_files(self) -> Set[str]:
        """Load list of already processed files"""
        db_file = Path(self.config['processing']['work_dir']) / 'processed.json'
        if db_file.exists():
            with open(db_file, 'r') as f:
                return set(json.load(f))
        return set()

    def save_processed_files(self):
        """Save list of processed files"""
        db_file = Path(self.config['processing']['work_dir']) / 'processed.json'
        with open(db_file, 'w') as f:
            json.dump(list(self.processed_files), f, indent=2)

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def get_file_hash(self, file_path: str) -> str:
        """Generate unique hash for file path"""
        return hashlib.md5(file_path.encode()).hexdigest()

    def discover_videos(self) -> List[Path]:
        """Discover video files in configured directories"""
        directories = self.config['directories']
        extensions = self.config['processing']['include_extensions']
        exclude_patterns = self.config['processing']['exclude_patterns']

        all_videos = []

        for directory in directories:
            dir_path = Path(directory)

            if not dir_path.exists():
                self.logger.warning(f"Directory does not exist: {directory}")
                continue

            self.logger.debug(f"Scanning {directory}")

            try:
                # Find all video files recursively
                for ext in extensions:
                    pattern = f"**/*.{ext}"
                    for video_file in dir_path.glob(pattern):
                        if video_file.is_file():
                            # Check exclude patterns
                            should_exclude = False
                            for exclude_pattern in exclude_patterns:
                                if video_file.match(exclude_pattern):
                                    should_exclude = True
                                    break

                            if not should_exclude:
                                all_videos.append(video_file)

            except Exception as e:
                self.logger.error(f"Exception scanning {directory}: {e}")

        self.logger.info(f"Discovered {len(all_videos)} total video files")
        return all_videos

    def should_process(self, video_path: Path) -> bool:
        """Check if file should be processed"""
        file_hash = self.get_file_hash(str(video_path))

        # Skip if already processed
        if file_hash in self.processed_files:
            return False

        # Skip if currently converting
        if file_hash in self.converting:
            return False

        # Skip if output already exists
        output_path = video_path.with_suffix('.m4v')
        if output_path.exists() and output_path != video_path:
            self.logger.debug(f"Output already exists: {output_path}")
            return False

        # Skip if already .m4v
        if video_path.suffix.lower() == '.m4v':
            return False

        return True

    def convert_video(self, video_path: Path) -> bool:
        """Convert a single video file"""
        file_hash = self.get_file_hash(str(video_path))
        work_dir = Path(self.config['processing']['work_dir'])

        try:
            self.converting.add(file_hash)
            self.logger.info(f"Starting conversion: {video_path}")

            # Generate output filename
            output_path = video_path.with_suffix('.m4v')
            temp_output = work_dir / f"{file_hash}_output.m4v"

            # Convert video
            self.logger.info(f"Converting {video_path.name}")
            ffmpeg_cmd = self.build_ffmpeg_command(video_path, temp_output)

            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True,
                timeout=None  # No timeout for video conversion
            )

            if result.returncode != 0:
                self.logger.error(f"Conversion failed for {video_path}: {result.stderr}")
                temp_output.unlink(missing_ok=True)
                return False

            # Move converted file to final location
            self.logger.info(f"Moving converted file to {output_path}")
            shutil.move(str(temp_output), str(output_path))

            # Preserve timestamps
            try:
                stat = video_path.stat()
                os.utime(output_path, (stat.st_atime, stat.st_mtime))
            except Exception as e:
                self.logger.warning(f"Could not preserve timestamps: {e}")

            # Delete original if configured
            if not self.config['processing']['keep_original']:
                self.logger.info(f"Deleting original: {video_path}")
                try:
                    video_path.unlink()
                except Exception as e:
                    self.logger.error(f"Failed to delete original: {e}")

            # Mark as processed
            self.processed_files.add(file_hash)
            self.save_processed_files()

            self.logger.info(f"Successfully converted: {video_path}")
            return True

        except subprocess.TimeoutExpired:
            self.logger.error(f"Conversion timeout for {video_path}")
            return False
        except Exception as e:
            self.logger.error(f"Exception converting {video_path}: {e}", exc_info=True)
            return False
        finally:
            self.converting.discard(file_hash)
            # Cleanup temp files
            temp_output = work_dir / f"{file_hash}_output.m4v"
            temp_output.unlink(missing_ok=True)

    def build_ffmpeg_command(self, input_path: Path, output_path: Path) -> List[str]:
        """Build FFmpeg command from configuration"""
        config = self.config['conversion']

        cmd = [
            'ffmpeg',
            '-i', str(input_path),
            '-c:v', config['codec'],
            '-crf', str(config['crf']),
            '-preset', config['preset'],
            '-c:a', config['audio_codec'],
            '-b:a', config['audio_bitrate'],
        ]

        # Add extra options
        cmd.extend(config.get('extra_options', []))

        # Add output file
        cmd.extend(['-y', str(output_path)])

        return cmd

    def process_batch(self, videos: List[Path]):
        """Process a batch of videos with concurrent workers"""
        max_workers = self.config['daemon']['max_workers']

        # Filter videos that need processing
        to_process = [v for v in videos if self.should_process(v)]

        if not to_process:
            self.logger.debug("No new videos to process")
            return

        self.logger.info(f"Processing {len(to_process)} videos with {max_workers} workers")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.convert_video, video): video
                      for video in to_process}

            for future in as_completed(futures):
                video = futures[future]
                try:
                    success = future.result()
                    if success:
                        self.logger.info(f"Completed: {video}")
                    else:
                        self.logger.warning(f"Failed: {video}")
                except Exception as e:
                    self.logger.error(f"Exception processing {video}: {e}")

    def run(self):
        """Main daemon loop"""
        scan_interval = self.config['daemon']['scan_interval']

        self.logger.info("Video Converter Daemon started")
        self.logger.info(f"Scan interval: {scan_interval} seconds")
        self.logger.info(f"Monitoring directories: {self.config['directories']}")

        while self.running:
            try:
                self.logger.info("Starting scan cycle...")

                # Discover videos
                videos = self.discover_videos()

                # Process videos
                self.process_batch(videos)

                self.logger.info(f"Scan cycle complete. Sleeping for {scan_interval} seconds")

                # Sleep with interruption check
                sleep_elapsed = 0
                while sleep_elapsed < scan_interval and self.running:
                    time.sleep(min(5, scan_interval - sleep_elapsed))
                    sleep_elapsed += 5

            except Exception as e:
                self.logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(30)

        self.logger.info("Video Converter Daemon stopped")

def main():
    """Main entry point"""
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"

    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    daemon = VideoConverterDaemon(config_path)
    daemon.run()

if __name__ == "__main__":
    main()

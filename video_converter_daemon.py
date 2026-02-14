#!/usr/bin/env python3
"""
Video Converter Daemon
Automatically discovers and converts video files from remote server to .m4v format
"""

import os
import sys
import time
import yaml
import logging
import subprocess
import hashlib
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

    def get_file_hash(self, remote_path: str) -> str:
        """Generate unique hash for remote file"""
        return hashlib.md5(remote_path.encode()).hexdigest()

    def discover_videos(self) -> List[str]:
        """Discover video files on remote server"""
        remote_host = self.config['remote']['host']
        directories = self.config['remote']['directories']
        extensions = self.config['processing']['include_extensions']
        exclude_patterns = self.config['processing']['exclude_patterns']

        all_videos = []

        for directory in directories:
            self.logger.debug(f"Scanning {remote_host}:{directory}")

            # Build find command to discover video files
            ext_conditions = " -o ".join([f"-iname '*.{ext}'" for ext in extensions])
            exclude_conditions = " ".join([f"! -path '{pattern}'" for pattern in exclude_patterns])

            find_cmd = f"find '{directory}' -type f \\( {ext_conditions} \\) {exclude_conditions} 2>/dev/null"
            ssh_cmd = f"ssh {remote_host} \"{find_cmd}\""

            try:
                result = subprocess.run(
                    ssh_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if result.returncode == 0:
                    files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
                    all_videos.extend(files)
                    self.logger.debug(f"Found {len(files)} videos in {directory}")
                else:
                    self.logger.error(f"Error scanning {directory}: {result.stderr}")

            except subprocess.TimeoutExpired:
                self.logger.error(f"Timeout scanning {directory}")
            except Exception as e:
                self.logger.error(f"Exception scanning {directory}: {e}")

        self.logger.info(f"Discovered {len(all_videos)} total video files")
        return all_videos

    def should_process(self, remote_path: str) -> bool:
        """Check if file should be processed"""
        file_hash = self.get_file_hash(remote_path)

        # Skip if already processed
        if file_hash in self.processed_files:
            return False

        # Skip if currently converting
        if file_hash in self.converting:
            return False

        # Skip if output already exists
        if remote_path.lower().endswith('.m4v'):
            return False

        return True

    def convert_video(self, remote_path: str) -> bool:
        """Convert a single video file"""
        file_hash = self.get_file_hash(remote_path)
        remote_host = self.config['remote']['host']
        work_dir = Path(self.config['processing']['work_dir'])

        try:
            self.converting.add(file_hash)
            self.logger.info(f"Starting conversion: {remote_path}")

            # Generate output filename
            input_path = Path(remote_path)
            output_filename = input_path.stem + '.m4v'
            local_input = work_dir / f"{file_hash}_input{input_path.suffix}"
            local_output = work_dir / f"{file_hash}_output.m4v"
            remote_output = str(input_path.parent / output_filename)

            # Step 1: Download file
            self.logger.info(f"Downloading {remote_path}")
            rsync_cmd = [
                'rsync', '-avz', '--progress',
                f'{remote_host}:{remote_path}',
                str(local_input)
            ]

            result = subprocess.run(rsync_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.error(f"Download failed: {result.stderr}")
                return False

            # Step 2: Convert video
            self.logger.info(f"Converting {input_path.name}")
            ffmpeg_cmd = self.build_ffmpeg_command(local_input, local_output)

            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.error(f"Conversion failed: {result.stderr}")
                local_input.unlink(missing_ok=True)
                return False

            # Step 3: Upload converted file
            self.logger.info(f"Uploading {output_filename}")
            rsync_cmd = [
                'rsync', '-avz', '--progress',
                str(local_output),
                f'{remote_host}:{remote_output}'
            ]

            result = subprocess.run(rsync_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.error(f"Upload failed: {result.stderr}")
                local_input.unlink(missing_ok=True)
                local_output.unlink(missing_ok=True)
                return False

            # Step 4: Delete original if configured
            if not self.config['processing']['keep_original']:
                self.logger.info(f"Deleting original: {remote_path}")
                ssh_cmd = f"ssh {remote_host} 'rm \"{remote_path}\"'"
                subprocess.run(ssh_cmd, shell=True, capture_output=True)

            # Cleanup local files
            local_input.unlink(missing_ok=True)
            local_output.unlink(missing_ok=True)

            # Mark as processed
            self.processed_files.add(file_hash)
            self.save_processed_files()

            self.logger.info(f"Successfully converted: {remote_path}")
            return True

        except Exception as e:
            self.logger.error(f"Exception converting {remote_path}: {e}")
            return False
        finally:
            self.converting.discard(file_hash)

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

    def process_batch(self, videos: List[str]):
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
        self.logger.info(f"Remote host: {self.config['remote']['host']}")
        self.logger.info(f"Monitoring directories: {self.config['remote']['directories']}")

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

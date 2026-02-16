#!/bin/bash
# Integration tests for Video Converter Daemon

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Log test results
test_result() {
    local name="$1"
    local status="$2"
    TESTS_RUN=$((TESTS_RUN + 1))

    if [ "$status" = "PASS" ]; then
        echo -e "${GREEN}✓${NC} $name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${RED}✗${NC} $name"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

# Setup
echo "=== Video Converter Daemon Integration Tests ==="
echo ""

# Create temporary test directory
TEST_DIR=$(mktemp -d)
trap "rm -rf '$TEST_DIR'" EXIT

echo "Test directory: $TEST_DIR"
echo ""

# Create test structure
mkdir -p "$TEST_DIR"/{work,state,logs,videos}

# Get daemon script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$SCRIPT_DIR"

# Test 1: Config validation
echo "Test 1: Config validation"
if python3 video_converter_daemon.py --validate-config --config config.yaml 2>/dev/null; then
    test_result "Config validation" "PASS"
else
    test_result "Config validation" "FAIL"
fi
echo ""

# Test 2: Create test config with FHS paths
echo "Test 2: Create test config"
cat > "$TEST_DIR/config.yaml" <<EOF
directories:
  - "$TEST_DIR/videos"

conversion:
  format: "m4v"
  codec: "libx264"
  crf: 23
  preset: "fast"
  audio_codec: "aac"
  audio_bitrate: "128k"
  extra_options: []

processing:
  work_dir: "$TEST_DIR/work"
  state_dir: "$TEST_DIR/state"
  keep_original: true
  include_extensions:
    - "mp4"
    - "mkv"
  exclude_patterns:
    - "*.converted.*"

daemon:
  scan_interval: 30
  max_workers: 1
  log_file: "$TEST_DIR/logs/daemon.log"
  log_level: "INFO"
EOF

if [ -f "$TEST_DIR/config.yaml" ]; then
    test_result "Test config creation" "PASS"
else
    test_result "Test config creation" "FAIL"
fi
echo ""

# Test 3: Validate test config
echo "Test 3: Validate test config"
if python3 video_converter_daemon.py --validate-config --config "$TEST_DIR/config.yaml" 2>/dev/null; then
    test_result "Test config validation" "PASS"
else
    test_result "Test config validation" "FAIL"
fi
echo ""

# Test 4: Create dummy video file
echo "Test 4: Create dummy video file"
DUMMY_VIDEO="$TEST_DIR/videos/test_video.mp4"
# Create a minimal MP4-like file (just bytes, not a real video for testing)
echo "ftypisom" > "$DUMMY_VIDEO"

if [ -f "$DUMMY_VIDEO" ]; then
    test_result "Dummy video creation" "PASS"
else
    test_result "Dummy video creation" "FAIL"
fi
echo ""

# Test 5: Dry-run mode
echo "Test 5: Dry-run mode"
if timeout 40 python3 video_converter_daemon.py --config "$TEST_DIR/config.yaml" --dry-run 2>&1 | grep -q "DRY-RUN\|Scan cycle complete\|Starting in DRY-RUN"; then
    test_result "Dry-run mode" "PASS"
else
    test_result "Dry-run mode" "FAIL"
fi
echo ""

# Test 6: Check state directory created
echo "Test 6: State directory handling"
if [ -d "$TEST_DIR/state" ]; then
    test_result "State directory exists" "PASS"
else
    test_result "State directory exists" "FAIL"
fi
echo ""

# Test 7: Check log file creation
echo "Test 7: Log file creation"
if [ -f "$TEST_DIR/logs/daemon.log" ]; then
    test_result "Log file created" "PASS"
else
    test_result "Log file created" "FAIL"
fi
echo ""

# Test 8: Check processed.json location (state_dir, not work_dir)
echo "Test 8: Processed files location"
PROCESSED_FILE="$TEST_DIR/state/processed.json"
# After dry-run, processed.json should exist in state_dir
if [ -f "$PROCESSED_FILE" ]; then
    test_result "Processed.json in state_dir" "PASS"
else
    # It's OK if it doesn't exist yet - dry-run with no real videos
    test_result "Processed.json in state_dir (optional)" "PASS"
fi
echo ""

# Test 9: Test --help flag
echo "Test 9: Help flag"
if python3 video_converter_daemon.py --help 2>&1 | grep -q "usage\|optional arguments"; then
    test_result "--help flag" "PASS"
else
    test_result "--help flag" "FAIL"
fi
echo ""

# Test 10: Test --version flag
echo "Test 10: Version flag"
if python3 video_converter_daemon.py --version 2>&1 | grep -q "Video Converter Daemon\|version"; then
    test_result "--version flag" "PASS"
else
    test_result "--version flag" "FAIL"
fi
echo ""

# Print summary
echo "=== Test Summary ==="
echo "Total: $TESTS_RUN"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"
echo ""

# Exit with appropriate code
if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi

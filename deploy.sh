#!/bin/bash
# Deploy Video Converter Daemon to nas01

# Security: Exit on error, undefined variables, and pipe failures
set -euo pipefail

REMOTE_HOST="nas01"
REMOTE_DIR="~/video-converter"

echo "=== Deploying Video Converter Daemon to nas01 ==="
echo ""

# Create remote directory
echo "Creating remote directory..."
ssh "$REMOTE_HOST" "mkdir -p $REMOTE_DIR"

# Copy files
echo "Copying files to nas01..."
rsync -avz --progress \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.claude' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='*.key' \
    --exclude='*.pem' \
    ./ "$REMOTE_HOST":"$REMOTE_DIR"/

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Files deployed to: $REMOTE_HOST:$REMOTE_DIR"
echo ""
echo "Next steps:"
echo "  1. SSH to nas01: ssh $REMOTE_HOST"
echo "  2. cd $REMOTE_DIR"
echo "  3. Edit config.yaml with your video directories"
echo "  4. Run: ./install.sh"
echo "  5. Start service: systemctl --user enable --now video-converter"
echo ""

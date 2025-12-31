#!/bin/bash
# Setup script for JobSniper - creates directories and sets permissions

set -e

echo "🚀 JobSniper Setup Script"
echo "=========================="
echo ""

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "📁 Creating required directories..."
mkdir -p logs data grafana_data prometheus_data

echo "🔐 Setting permissions..."
# App logs and data (UID 1000 - non-root user in Docker)
sudo chown -R 1000:1000 logs data 2>/dev/null || chown -R 1000:1000 logs data
chmod -R 755 logs data

# Grafana data (UID 472 - Grafana user in container)
sudo chown -R 472:472 grafana_data 2>/dev/null || {
    echo "⚠️  Warning: Could not set grafana_data ownership to 472:472"
    echo "   You may need to run: sudo chown -R 472:472 grafana_data"
}
chmod -R 755 grafana_data

# Prometheus data (UID 65534 - nobody user in container)
sudo chown -R 65534:65534 prometheus_data 2>/dev/null || {
    echo "⚠️  Warning: Could not set prometheus_data ownership to 65534:65534"
    echo "   You may need to run: sudo chown -R 65534:65534 prometheus_data"
}
chmod -R 755 prometheus_data

echo ""
echo "✅ Directories created and permissions set!"
echo ""
echo "📝 Next steps:"
echo "   1. Copy .env.example to .env: cp .env.example .env"
echo "   2. Edit .env with your API keys: nano .env"
echo "   3. (Optional) Add your CV: cp /path/to/cv.pdf data/cv.pdf"
echo "   4. Build and start: DOCKER_BUILDKIT=1 docker-compose build && docker-compose up -d"
echo ""

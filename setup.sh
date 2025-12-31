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
if sudo chown -R 1000:1000 logs data 2>/dev/null; then
    echo "   ✅ Set ownership for logs/ and data/ to 1000:1000"
else
    echo "   ⚠️  Could not set ownership for logs/ and data/"
    echo "      You may need to run: sudo chown -R 1000:1000 logs data"
fi
chmod -R 755 logs data 2>/dev/null || sudo chmod -R 755 logs data

# Grafana data (UID 472 - Grafana user in container)
if sudo chown -R 472:472 grafana_data 2>/dev/null; then
    echo "   ✅ Set ownership for grafana_data/ to 472:472"
else
    echo "   ⚠️  Could not set ownership for grafana_data/"
    echo "      You may need to run: sudo chown -R 472:472 grafana_data"
fi
if sudo chmod -R 755 grafana_data 2>/dev/null; then
    echo "   ✅ Set permissions for grafana_data/"
else
    echo "   ⚠️  Could not set permissions for grafana_data/"
fi

# Prometheus data (UID 65534 - nobody user in container)
if sudo chown -R 65534:65534 prometheus_data 2>/dev/null; then
    echo "   ✅ Set ownership for prometheus_data/ to 65534:65534"
else
    echo "   ⚠️  Could not set ownership for prometheus_data/"
    echo "      You may need to run: sudo chown -R 65534:65534 prometheus_data"
fi
if sudo chmod -R 755 prometheus_data 2>/dev/null; then
    echo "   ✅ Set permissions for prometheus_data/"
else
    echo "   ⚠️  Could not set permissions for prometheus_data/"
fi

echo ""
echo "✅ Directories created and permissions set!"
echo ""
echo "📝 Next steps:"
echo "   1. Copy .env.example to .env: cp .env.example .env"
echo "   2. Edit .env with your API keys: nano .env"
echo "   3. (Optional) Add your CV: cp /path/to/cv.pdf data/cv.pdf"
echo "   4. Build and start: DOCKER_BUILDKIT=1 docker-compose build && docker-compose up -d"
echo ""

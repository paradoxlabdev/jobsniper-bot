#!/bin/bash
# Run JobSniper tests with various options

set -e  # Exit on error

echo "🧪 JobSniper Test Suite"
echo "======================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}❌ pytest not found. Installing...${NC}"
    pip install pytest pytest-asyncio pytest-cov
fi

# Parse arguments
COVERAGE=false
VERBOSE=false
FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--coverage)
            COVERAGE=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -f|--file)
            FILE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./run_tests.sh [-c|--coverage] [-v|--verbose] [-f|--file <path>]"
            exit 1
            ;;
    esac
done

# Build pytest command
CMD="pytest"

if [ -n "$FILE" ]; then
    CMD="$CMD $FILE"
else
    CMD="$CMD tests/"
fi

if [ "$VERBOSE" = true ]; then
    CMD="$CMD -v"
fi

if [ "$COVERAGE" = true ]; then
    CMD="$CMD --cov=services --cov=main --cov-report=html --cov-report=term"
fi

# Run tests
echo -e "${YELLOW}Running: $CMD${NC}"
echo ""

if $CMD; then
    echo ""
    echo -e "${GREEN}✅ All tests passed!${NC}"
    
    if [ "$COVERAGE" = true ]; then
        echo ""
        echo -e "${GREEN}📊 Coverage report generated: htmlcov/index.html${NC}"
        echo "   Open with: open htmlcov/index.html"
    fi
    
    exit 0
else
    echo ""
    echo -e "${RED}❌ Tests failed!${NC}"
    exit 1
fi

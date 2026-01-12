#!/bin/bash
# TyK Notebook Test Runner
# Usage: ./run_tests.sh [test_module]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}================================${NC}"
echo -e "${YELLOW}TyK Notebook Test Suite${NC}"
echo -e "${YELLOW}================================${NC}"
echo ""

# Check if specific test module provided
if [ -z "$1" ]; then
    echo "Running ALL tests..."
    python -c "import os; os.environ['DJANGO_SETTINGS_MODULE']='tyk_notebook_app.settings'; import django; django.setup(); from django.core.management import call_command; call_command('test', 'tyk_notebook_app.tests', verbosity=2)"
else
    echo "Running tests for: $1"
    python -c "import os; os.environ['DJANGO_SETTINGS_MODULE']='tyk_notebook_app.settings'; import django; django.setup(); from django.core.management import call_command; call_command('test', 'tyk_notebook_app.tests.$1', verbosity=2)"
fi

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Test run complete!${NC}"
echo -e "${GREEN}================================${NC}"

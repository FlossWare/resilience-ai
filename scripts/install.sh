#!/bin/bash
# Install resilience-ai from GitHub
set -e
echo "Installing resilience-ai..."
pip install "git+https://github.com/FlossWare/resilience-ai.git"
echo "resilience-ai installed successfully."
python3 -c "import resilience_ai; print(f'Version: {resilience_ai.__version__}')"

#!/bin/bash
set -e

echo "Setting up CC Usage Tracker..."

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

echo ""
echo "Setup complete! Run the app with:"
echo "  source .venv/bin/activate && python app.py"

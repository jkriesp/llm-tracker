#!/usr/bin/env bash
set -euo pipefail

echo "==> Cleaning previous build..."
rm -rf build dist

echo "==> Building CC Usage Tracker.app..."
python setup.py py2app

echo ""
echo "==> Done! App bundle is at:"
echo "    dist/CC Usage Tracker.app"
echo ""
echo "To install, copy it to /Applications:"
echo "    cp -R \"dist/CC Usage Tracker.app\" /Applications/"
echo ""
echo "To run:"
echo "    open \"dist/CC Usage Tracker.app\""

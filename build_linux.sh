#!/bin/bash
set -e

source .venv_linux/bin/activate

echo "Running PyInstaller..."
pyinstaller --clean ImageAligner_Linux.spec

echo "Build complete. Check dist/ImageAligner_Linux"

#!/bin/bash
set -e

echo "Updating package lists..."
sudo apt-get update

echo "Installing system dependencies..."
sudo apt-get install -y python3 python3-pip python3-venv libgl1 libglib2.0-0

echo "Creating virtual environment..."
python3 -m venv .venv_linux
source .venv_linux/bin/activate

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Installing PyInstaller..."
pip install pyinstalle

echo "Setup complete."

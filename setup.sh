#!/bin/bash

# 1. Create and activate virtual environment
if [ -d "venv" ]; then
    echo "Removing existing virtual environment..."
    rm -rf venv
fi

echo "Creating new virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 2. Upgrade pip
python3 -m pip install --upgrade pip

# 3. Install dependencies
pip install -r requirements.txt

echo "Setup complete!"
# 1. Create and activate virtual environment
if (Test-Path "venv") {
    Write-Host "Removing existing virtual environment..."
    Remove-Item -Recurse -Force venv
}

Write-Host "Creating new virtual environment..."
python -m venv venv
.\venv\Scripts\Activate

# 2. Upgrade pip
python -m pip install --upgrade pip

# 3. Install dependencies with platform check
pip install -r requirements.txt

Write-Host "Setup complete!"
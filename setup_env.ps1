$ErrorActionPreference = "Stop"

Write-Host "Creating an isolated Python Virtual Environment (.venv)..."
python -m venv .venv

Write-Host "Activating the virtual environment..."
$env:VIRTUAL_ENV = "$PWD\.venv"
$env:Path = "$PWD\.venv\Scripts;$env:Path"

Write-Host "Upgrading pip..."
python -m pip install --upgrade pip

Write-Host "Installing Python dependencies (PyMuPDF, Torch, Transformers, CTranslate2)..."
pip install -r requirements.txt

Write-Host '---------------------------------------------------------'
Write-Host 'Environment setup complete!'
Write-Host 'To use this isolated environment:'
Write-Host '1. Activate it in PowerShell using: .\.venv\Scripts\Activate.ps1'
Write-Host '2. Before running the readDoc app, ensure the app uses this environment by setting:'
Write-Host '   $env:READDOC_PYTHON="$PWD\.venv\Scripts\python.exe"'
Write-Host '---------------------------------------------------------'

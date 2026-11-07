# Build the portable folder on Windows. ASCII-only for Windows PowerShell 5.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONUTF8 = "1"
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean packaging/lab_uncertainty.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$docs = Join-Path $Root "dist\LabUncertainty\docs"
New-Item -ItemType Directory -Force -Path $docs | Out-Null
Copy-Item -Path (Join-Path $Root "docs\*") -Destination $docs -Recurse -Force
Copy-Item (Join-Path $Root "README.md") (Join-Path $Root "dist\LabUncertainty\README.md") -Force
Write-Host "Built dist\LabUncertainty\LabUncertainty.exe"

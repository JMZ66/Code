# Build the portable folder on Windows. ASCII-only so Windows PowerShell 5
# does not misread this file when it has no UTF-8 BOM.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONUTF8 = "1"
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean packaging/chem_warehouse.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$docs = Join-Path $Root "dist\ChemWarehouse\docs"
New-Item -ItemType Directory -Force -Path $docs | Out-Null
$env:PYTHONPATH = "src"
python -m chem_wh.docpdf --out $docs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Get-ChildItem -Path (Join-Path $Root "docs") -File | Copy-Item -Destination $docs -Force
Get-ChildItem -Path (Join-Path $Root "packaging") -Filter *.txt | Copy-Item -Destination (Join-Path $Root "dist\ChemWarehouse") -Force
Write-Host "Built dist\ChemWarehouse\ChemWarehouse.exe"

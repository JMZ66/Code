# Build the portable folder on Windows. Run from chem_warehouse or anywhere.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean packaging/chem_warehouse.spec
New-Item -ItemType Directory -Force -Path "dist\ChemWarehouse\docs" | Out-Null
$env:PYTHONPATH = "src"
python -m chem_wh.docpdf --out "dist\ChemWarehouse\docs"
Copy-Item "docs\用户手册.md" "dist\ChemWarehouse\docs\用户手册.md" -Force
Copy-Item "docs\测试报告.md" "dist\ChemWarehouse\docs\测试报告.md" -Force -ErrorAction SilentlyContinue
Copy-Item "packaging\使用说明.txt" "dist\ChemWarehouse\使用说明.txt" -Force
Copy-Item "packaging\DISCLAIMER.txt" "dist\ChemWarehouse\DISCLAIMER.txt" -Force
Write-Host "Built dist\ChemWarehouse\ChemWarehouse.exe"

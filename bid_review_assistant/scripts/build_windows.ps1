# Build the portable folder on Windows. ASCII-only for Windows PowerShell 5 (no UTF-8 BOM issues).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONUTF8 = "1"
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean packaging/bid_review_assistant.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$dist = Join-Path $Root "dist\BidReviewAssistant"
$docs = Join-Path $dist "docs"
New-Item -ItemType Directory -Force -Path $docs | Out-Null
Get-ChildItem -Path (Join-Path $Root "docs") -File | Copy-Item -Destination $docs -Force
Get-ChildItem -Path (Join-Path $Root "packaging") -Filter *.txt | Copy-Item -Destination $dist -Force
Copy-Item -Force (Join-Path $Root "LICENSE") $dist
Copy-Item -Recurse -Force (Join-Path $Root "config") (Join-Path $dist "config")
Write-Host "Built dist\BidReviewAssistant\BidReviewAssistant.exe"

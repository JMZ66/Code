# Build the portable folder on Windows. ASCII-only for Windows PowerShell 5.
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
Copy-Item -Force (Join-Path $Root "docs\*") $docs
Copy-Item -Force (Join-Path $Root "packaging\使用说明.txt") $dist
Copy-Item -Force (Join-Path $Root "packaging\DISCLAIMER.txt") $dist
Copy-Item -Force (Join-Path $Root "LICENSE") $dist
Copy-Item -Recurse -Force (Join-Path $Root "config") (Join-Path $dist "config")
Write-Host "Built dist\BidReviewAssistant\BidReviewAssistant.exe"

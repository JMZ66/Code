# Windows 离线打包（文件夹分发，避免单文件解压问题）
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

python -m pip install -r requirements.txt -r requirements-dev.txt
$env:PYTHONPATH = "src"
python -m pytest tests -q
python -m PyInstaller packaging/bid_review.spec --noconfirm --clean

$dist = Join-Path (Get-Location) "dist/BidReviewAssistant"
Copy-Item -Recurse -Force docs $dist/
Copy-Item -Force README.md $dist/
Copy-Item -Force LICENSE $dist/ -ErrorAction SilentlyContinue

$zip = Join-Path (Get-Location) "dist/BidReviewAssistant-windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $dist -DestinationPath $zip
Write-Host "Built: $zip"

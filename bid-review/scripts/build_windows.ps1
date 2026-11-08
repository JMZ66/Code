$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller packaging/bidreview.spec --noconfirm --clean
if (-not (Test-Path "dist\BidReview\BidReview.exe")) {
    throw "BidReview.exe was not produced"
}
New-Item -ItemType Directory -Force -Path "dist\BidReview\docs" | Out-Null
Copy-Item README.md, LICENSE "dist\BidReview\" -Force
Copy-Item "packaging\usage.txt" "dist\BidReview\usage.txt" -Force
Copy-Item "docs\*" "dist\BidReview\docs\" -Recurse -Force
Write-Host "Built dist\BidReview\BidReview.exe"

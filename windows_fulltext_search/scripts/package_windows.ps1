$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$release = Join-Path $root "target\release"
$dist = Join-Path $root "dist\LocalSearch"
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $dist "fonts") | Out-Null
Copy-Item (Join-Path $release "LocalSearch.exe") $dist
Copy-Item (Join-Path $release "local-search-parse.exe") $dist
Copy-Item (Join-Path $root "fonts\DroidSansFallbackFull.ttf") (Join-Path $dist "fonts")
Copy-Item (Join-Path $root "licenses") (Join-Path $dist "licenses") -Recurse
Copy-Item (Join-Path $root "docs") (Join-Path $dist "docs") -Recurse
Set-Content -Path (Join-Path $dist "portable.marker") -Value "portable" -Encoding ascii
$version = "1.0.0"
$zip = Join-Path $root "dist\LocalSearch-$version-windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dist -DestinationPath $zip
Write-Host "wrote $zip"

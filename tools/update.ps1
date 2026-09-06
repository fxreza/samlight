# Rebuild the Kodi repository from the current source and publish it.
# Run from anywhere:  pwsh tools\update.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

git checkout main
python tools/build.py
git add -A
if (git status --porcelain) { git commit -m "Rebuild repository" }
git push origin main
Write-Host "Done. Kodi will pick it up on its next repository check." -ForegroundColor Green

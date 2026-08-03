# Pull upstream's latest, merge it into your tweaks, rebuild, publish.
# Run from anywhere:  pwsh tools\update.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

git checkout main
python tools/sync_upstream.py
git push origin upstream

git merge upstream --no-edit
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Merge conflict: upstream changed lines you also changed." -ForegroundColor Yellow
    Write-Host "Fix the marked files, then:  git add -A; git commit; python tools/build.py" -ForegroundColor Yellow
    exit 1
}

python tools/build.py
git add -A
if (git status --porcelain) { git commit -m "Rebuild repository" }
git push origin main
Write-Host "Done. Kodi will pick it up on its next repository check." -ForegroundColor Green

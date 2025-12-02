Param(
  [string]$RepoName = "AlphaCouncil-AI",
  [string]$RemoteUrl = "",
  [switch]$Public = $true
)

$ErrorActionPreference = "Stop"

Write-Host "[STEP] Preparing repo" -ForegroundColor Cyan
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

if (-not (Test-Path ".git")) {
  Write-Host "[STEP] git init" -ForegroundColor Cyan
  git init
}

Write-Host "[STEP] Ensuring .gitignore present" -ForegroundColor Cyan
if (-not (Test-Path ".gitignore")) { Set-Content ".gitignore" "config/app.json`n" }

Write-Host "[STEP] Staging files" -ForegroundColor Cyan
git add .

Write-Host "[STEP] Commit" -ForegroundColor Cyan
try { git commit -m "Initial public release" } catch { Write-Host "[WARN] commit skipped: $_" -ForegroundColor Yellow }

function Test-GhInstalled {
  try { Get-Command gh -ErrorAction Stop | Out-Null; return $true } catch { return $false }
}

if (Test-GhInstalled) {
  Write-Host "[STEP] Creating GitHub repo via gh" -ForegroundColor Cyan
  if ($Public) { $vis = "--public" } else { $vis = "--private" }
  try {
    gh repo create $RepoName $vis --source . --remote origin --push
    Write-Host "[OK] Pushed to GitHub: $RepoName" -ForegroundColor Green
    exit 0
  } catch {
    Write-Host "[WARN] gh create failed: $_" -ForegroundColor Yellow
  }
}

if ($RemoteUrl) {
  Write-Host "[STEP] Set remote and push" -ForegroundColor Cyan
  try {
    if (-not (git remote | Select-String -Quiet "origin")) { git remote add origin $RemoteUrl }
    git branch -M main
    git push -u origin main
    Write-Host "[OK] Pushed to $RemoteUrl" -ForegroundColor Green
    exit 0
  } catch {
    Write-Host "[ERROR] Push failed: $_" -ForegroundColor Red
    exit 1
  }
} else {
  Write-Host "[INFO] gh not installed or not logged in, and no RemoteUrl provided. Local init and first commit done." -ForegroundColor Yellow
  Write-Host ('[HINT] gh repo create ' + $RepoName + ' --public --source . --remote origin --push') -ForegroundColor DarkGray
}


Param(
  [string]$OutputZip = "AlphaCouncil-AI.zip"
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

$root = (Get-Location).Path
$outDir = Join-Path $root "build/public_release"
if (Test-Path $outDir) { Remove-Item $outDir -Recurse -Force }
New-Item -ItemType Directory -Path $outDir | Out-Null

Write-Host "[STEP] Copying sanitized selection" -ForegroundColor Cyan

# app
Copy-Item (Join-Path $root "app") (Join-Path $outDir "app") -Recurse -Force

# build: keep requirements and version info
New-Item -ItemType Directory -Path (Join-Path $outDir "build") | Out-Null
foreach ($f in @("build/requirements.txt","build/VERSION","build/version_info.txt")) {
  if (Test-Path (Join-Path $root $f)) { Copy-Item (Join-Path $root $f) (Join-Path $outDir $f) -Force }
}

# config: sample only
New-Item -ItemType Directory -Path (Join-Path $outDir "config") | Out-Null
if (Test-Path "config/app.sample.json") { Copy-Item "config/app.sample.json" (Join-Path $outDir "config/app.sample.json") -Force }

# scripts
Copy-Item (Join-Path $root "scripts") (Join-Path $outDir "scripts") -Recurse -Force

# services: exclude __pycache__
New-Item -ItemType Directory -Path (Join-Path $outDir "services") | Out-Null
Get-ChildItem -Path (Join-Path $root "services") -Recurse -Force | Where-Object { $_.PSIsContainer -eq $false -and $_.FullName -notmatch "__pycache__" } | ForEach-Object {
  $rel = $_.FullName.Substring((Join-Path $root "services").Length).TrimStart('\\/')
  $target = Join-Path (Join-Path $outDir "services") $rel
  $dir = Split-Path $target -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  Copy-Item $_.FullName $target -Force
}

# data: include algorithms and symbols.txt only
New-Item -ItemType Directory -Path (Join-Path $outDir "data") | Out-Null
if (Test-Path (Join-Path $root "data/algorithms")) { Copy-Item (Join-Path $root "data/algorithms") (Join-Path $outDir "data/algorithms") -Recurse -Force }
if (Test-Path (Join-Path $root "data/symbols.txt")) { Copy-Item (Join-Path $root "data/symbols.txt") (Join-Path $outDir "data/symbols.txt") -Force }

# top-level files
foreach ($f in @("AUTHORS","CHANGELOG.md","README.md","FILES-EXPLANATION.txt","COMMON-COMMANDS.txt","docs")) {
  if (Test-Path (Join-Path $root $f)) { Copy-Item (Join-Path $root $f) (Join-Path $outDir $f) -Recurse -Force }
}

Write-Host "[STEP] Creating zip" -ForegroundColor Cyan
if (Test-Path $OutputZip) { Remove-Item $OutputZip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($outDir, (Join-Path $root $OutputZip))
Write-Host ("[OK] Zip ready: " + (Join-Path $root $OutputZip)) -ForegroundColor Green


param(
    [string]$PythonExe = "",
    [switch]$SkipInstall,
    [switch]$StartApp
)

$ErrorActionPreference = "Stop"

Write-Host "[STEP] Preparing workspace" -ForegroundColor Cyan
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "../../"))

Write-Host "[STEP] Cleaning build/ and dist/" -ForegroundColor Cyan
foreach ($p in @("build","dist")) { if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue } }

$py = if ([string]::IsNullOrWhiteSpace($PythonExe)) { "python" } else { $PythonExe }
if (-not $SkipInstall) {
    Write-Host "[STEP] Installing requirements" -ForegroundColor Cyan
    try { & $py -m pip install --upgrade pip } catch { Write-Host "[WARN] pip upgrade failed: $_" -ForegroundColor Yellow }
    & $py -m pip install -r "ABC/build/requirements.txt"
}

Write-Host "[STEP] Running PyInstaller" -ForegroundColor Cyan
$args = @(
    '-m','PyInstaller',
    '--noconfirm','--clean','--onefile','--noconsole',
    '--name','AlphaCouncil',
    '--add-data','ABC/app/ui;app/ui',
    '--add-data','ABC/build/VERSION;.',
    '--version-file','ABC/build/version_info.txt',
    'ABC/app/launcher.py'
)
& $py $args

$built = "dist/AlphaCouncil.exe"
if (-not (Test-Path $built)) { throw "Build failed: dist/AlphaCouncil.exe not found" }
Write-Host "[OK]   Build output: $built" -ForegroundColor Green

$dest = "ABC/AlphaCouncil.exe"
if (Test-Path $dest) {
    $bak = "ABC/AlphaCouncil-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".bak"
    Copy-Item $dest $bak -ErrorAction SilentlyContinue
    Write-Host "[OK]   Backup: $bak" -ForegroundColor Green
}
Copy-Item $built $dest -Force
Write-Host "[OK]   Deployed: $dest" -ForegroundColor Green

if ($StartApp) { Start-Process $dest }
Write-Host "[OK]   Done" -ForegroundColor Green
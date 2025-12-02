param(
    [string]$PythonExe = "",
    [switch]$SkipInstall,
    [switch]$StartApp,
    [switch]$NoStop
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host ("[STEP] " + $msg) -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host ("[OK]   " + $msg) -ForegroundColor Green }
function Write-Warn($msg) { Write-Host ("[WARN] " + $msg) -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host ("[FAIL] " + $msg) -ForegroundColor Red }

try {
    # 1) 统一到仓库根目录
    $repoRoot = Resolve-Path (Join-Path $PSScriptRoot "../../")
    Set-Location $repoRoot
    Write-Step "Repo root: $repoRoot"

    # 2) 关闭可能占用端口的本地服务
    function Stop-Port($port) {
        try {
            $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($null -ne $conns -and $conns.Count -gt 0) {
                $pids = $conns | Select-Object -ExpandProperty OwningProcess | Select-Object -Unique
                foreach ($pid in $pids) {
                    try {
                        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                        Write-Ok "Stopped PID $pid on port $port"
                    } catch {
                        Write-Warn ("Failed stopping PID {0} on port {1}: {2}" -f $pid, $port, $_)
                    }
                }
            } else {
                Write-Step "No listener on port $port"
            }
        } catch {
            Write-Warn ("Get-NetTCPConnection unavailable or failed for port {0}: {1}" -f $port, $_)
        }
    }

    if (-not $NoStop) {
        Write-Step "Stopping services on ports 5173, 8787, 8788"
        Stop-Port 5173
        Stop-Port 8787
        Stop-Port 8788
    } else {
        Write-Step "Skip stopping services by request (-NoStop)"
    }

    # 3) 清理旧构建
    Write-Step "Cleaning build/ and dist/"
    foreach ($p in @("build", "dist")) {
        $full = Join-Path $repoRoot $p
        if (Test-Path $full) {
            Remove-Item $full -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Ok "Cleaned build and dist"

    # 4) 安装/更新依赖
    $py = if ([string]::IsNullOrWhiteSpace($PythonExe)) { "python" } else { $PythonExe }
    if (-not $SkipInstall) {
        Write-Step "Upgrading pip and installing requirements"
        try { & $py -m pip install --upgrade pip } catch { Write-Warn "pip upgrade failed: $_" }
        & $py -m pip install -r (Join-Path $repoRoot "ABC/build/requirements.txt")
        Write-Ok "Dependencies installed"
    } else {
        Write-Step "SkipInstall requested; using existing environment"
    }

    # 5) PyInstaller 打包
    Write-Step "Running PyInstaller"
    $piArgs = @(
        '-m','PyInstaller',
        '--noconfirm','--clean','--onefile','--noconsole',
        '--name','AlphaCouncil',
        '--add-data','ABC/app/ui;app/ui',
        '--add-data','ABC/build/VERSION;.',
        '--version-file','ABC/build/version_info.txt',
        'ABC/app/launcher.py'
    )
    & $py $piArgs

    $built = Join-Path $repoRoot "dist/AlphaCouncil.exe"
    if (-not (Test-Path $built)) { throw "Build failed: dist/AlphaCouncil.exe not found" }
    Write-Ok "Build output: $built"

    # 6) 备份并部署到 ABC/AlphaCouncil.exe
    $destExe = Join-Path $repoRoot "ABC/AlphaCouncil.exe"
    if (Test-Path $destExe) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $bak = Join-Path $repoRoot ("ABC/AlphaCouncil-" + $stamp + ".bak")
        Copy-Item $destExe $bak -ErrorAction SilentlyContinue
        Write-Ok "Backup created: $bak"
    }
    Copy-Item $built $destExe -Force
    Write-Ok "Deployed: $destExe"

    # 7) 可选启动应用
    if ($StartApp) {
        Write-Step "Starting application"
        Start-Process $destExe
        Write-Ok "Application launched"
    }

    Write-Ok "Repack finished"
    exit 0
} catch {
    Write-Fail "Error: $_"
    exit 1
}
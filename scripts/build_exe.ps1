Param(
  [string]$PythonExe = "python",
  [switch]$Clean = $false,
  [switch]$DeployToABC = $true,
  [switch]$SkipInstall = $false
)

if ($Clean) {
  Write-Host "[0/4] 清理旧构建产物 (build/, dist/)..." -ForegroundColor Yellow
  Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue
}

if (-not $SkipInstall) {
  Write-Host "[1/4] 升级 pip..." -ForegroundColor Cyan
  & $PythonExe -m pip install --upgrade pip

  Write-Host "[2/4] 安装打包依赖 (pywebview, pyinstaller, requests)..." -ForegroundColor Cyan
  & $PythonExe -m pip install -r "ABC/build/requirements.txt"
} else {
  Write-Host "[1-2/4] 跳过依赖安装步骤 (SkipInstall=True)" -ForegroundColor Yellow
}

Write-Host "[3/4] 执行 PyInstaller 打包..." -ForegroundColor Cyan
# 注意 --add-data 语法：src;dest（Windows 下使用分号分隔）
$pyArgs = @(
  "-m", "PyInstaller",
  "--noconfirm", "--clean", "--onefile", "--noconsole",
  "--name", "AlphaCouncil",
  "--add-data", "ABC/app/ui;app/ui",
  "--add-data", "ABC/build/VERSION;."
)
if (Test-Path "ABC/build/version_info.txt") { $pyArgs += "--version-file=ABC/build/version_info.txt" }
if (Test-Path "ABC/build/icon.ico") { $pyArgs += "--icon=ABC/build/icon.ico" }
$pyArgs += "ABC/app/launcher.py"
& $PythonExe $pyArgs

$exePath = "dist/AlphaCouncil.exe"
if (!(Test-Path $exePath)) {
  Write-Host "打包失败：未找到 $exePath" -ForegroundColor Red
  exit 1
}

Write-Host "[4/4] 打包完成：$exePath" -ForegroundColor Green

if ($DeployToABC) {
  $target = "ABC/AlphaCouncil.exe"
  if (Test-Path $target) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "ABC/AlphaCouncil-$timestamp.bak"
    Copy-Item $target $backup -Force
    Write-Host "已备份旧版本到 $backup" -ForegroundColor DarkGray
  }
  Copy-Item $exePath $target -Force
  Write-Host "已部署到 $target" -ForegroundColor Green
}
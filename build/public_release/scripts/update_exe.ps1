Param(
  [string]$PythonExe = "python",
  [switch]$Clean = $true,
  [switch]$SkipInstall = $false
)

Write-Host "开始一键更新 AlphaCouncil.exe (Clean=$Clean, SkipInstall=$SkipInstall)" -ForegroundColor Cyan

& "ABC/scripts/build_exe.ps1" -PythonExe $PythonExe -Clean:$Clean -DeployToABC:$true -SkipInstall:$SkipInstall
if ($LASTEXITCODE -ne 0) {
  Write-Host "更新失败，请检查构建日志。" -ForegroundColor Red
  exit 1
}

$target = "ABC/AlphaCouncil.exe"
if (Test-Path $target) {
  Write-Host "更新成功：$target" -ForegroundColor Green
} else {
  Write-Host "更新完成，但未发现目标 $target，请手动检查 dist/ 目录。" -ForegroundColor Yellow
}
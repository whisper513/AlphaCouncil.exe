param(
    [string]$TaskName = 'AlphaCouncilDailyUpdate',
    [string]$DailyTime = '09:00',
    [string]$ScriptPath = 'D:\Trae\ABC\scripts\run_daily_update.ps1'
)

$ErrorActionPreference = 'Stop'

Write-Host "[INFO] 注册Windows计划任务：$TaskName 每日 $DailyTime" -ForegroundColor Cyan

if (-not (Test-Path $ScriptPath)) {
    throw "脚本不存在：$ScriptPath"
}

# 使用 schtasks 以当前用户身份创建每日计划任务
$cmd = "powershell -ExecutionPolicy Bypass -File `"$ScriptPath`""

schtasks /Create /SC DAILY /ST $DailyTime /TN $TaskName /TR $cmd /F | Out-Host

Write-Host "[DONE] 已创建任务：$TaskName。可在任务计划程序中查看与修改。" -ForegroundColor Green
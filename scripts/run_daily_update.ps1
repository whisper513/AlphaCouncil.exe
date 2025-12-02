param(
    [string]$SymbolsFile = 'D:\Trae\ABC\data\symbols.txt',
    [string]$ExtraSymbols = '',
    [int]$SleepSeconds = 15
)

$ErrorActionPreference = 'Stop'

$python = 'python'
$scriptPath = 'D:\Trae\ABC\services\daily_update.py'

# 从用户环境变量中加载 ALPHAVANTAGE_API_KEY（若当前会话未设置）
if (-not $Env:ALPHAVANTAGE_API_KEY) {
    $userKey = [Environment]::GetEnvironmentVariable('ALPHAVANTAGE_API_KEY','User')
    if ($userKey) { $Env:ALPHAVANTAGE_API_KEY = $userKey }
}

if ($ExtraSymbols) {
    & $python $scriptPath -f $SymbolsFile -s $ExtraSymbols --sleep $SleepSeconds
} else {
    & $python $scriptPath -f $SymbolsFile --sleep $SleepSeconds
}
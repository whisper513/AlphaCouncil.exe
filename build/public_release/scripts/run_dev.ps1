Param(
  [int]$StaticPort = 5173,
  [int]$LLMPort = 8787,
  [int]$DataPort = 8788,
  [string]$PythonExe = "python",
  [switch]$ServeStatic = $true,
  [switch]$RunLLMProxy = $true,
  [switch]$RunDataGateway = $true,
  [switch]$RunLauncher = $false
)

Write-Host "启动开发模式 (静态:${StaticPort}, LLM:${LLMPort}, 数据:${DataPort})" -ForegroundColor Cyan

if ($ServeStatic) {
  Write-Host "→ 启动静态服务：http://localhost:${StaticPort}/alpha-dashboard.html" -ForegroundColor DarkCyan
  Start-Process -FilePath $PythonExe -ArgumentList "-m","http.server",$StaticPort -WorkingDirectory "ABC/app/ui" -WindowStyle Minimized
}

if ($RunLLMProxy) {
  Write-Host "→ 启动LLM代理：http://localhost:${LLMPort}/llm" -ForegroundColor DarkCyan
  Start-Process -FilePath $PythonExe -ArgumentList "ABC/services/llm-proxy.py" -WorkingDirectory "." -WindowStyle Minimized
}

if ($RunDataGateway) {
  Write-Host "→ 启动数据网关：http://localhost:${DataPort}/data/quote?symbol=IBM" -ForegroundColor DarkCyan
  Start-Process -FilePath $PythonExe -ArgumentList "ABC/services/data-gateway.py", $DataPort -WorkingDirectory "." -WindowStyle Minimized
}

if ($RunLauncher) {
  Write-Host "→ 启动桌面启动器 (webview)" -ForegroundColor DarkCyan
  Start-Process -FilePath $PythonExe -ArgumentList "ABC/app/launcher.py" -WorkingDirectory "."
}

Write-Host "开发模式已启动，可在浏览器访问：http://localhost:${StaticPort}/alpha-dashboard.html" -ForegroundColor Green
Write-Host "数据源API示例：/data/quote?symbol=IBM, /data/history?symbol=IBM&save=true" -ForegroundColor DarkGray
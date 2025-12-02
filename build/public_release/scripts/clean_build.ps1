Write-Host "清理构建产物：build/, dist/" -ForegroundColor Yellow
Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue
Write-Host "完成清理。" -ForegroundColor Green
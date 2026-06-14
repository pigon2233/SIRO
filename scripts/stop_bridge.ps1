# scripts/stop_bridge.ps1
#
# Stop bridge + siro-runtime
# Usage: powershell -ExecutionPolicy Bypass -File scripts\stop_bridge.ps1

Write-Host "[stop_bridge] Stopping port 8001 (bridge)..." -ForegroundColor Cyan
$port8001 = netstat -ano | Select-String ":8001 " | Select-String "LISTENING"
if ($port8001) {
    $pidLine = ($port8001 -split '\s+') | Where-Object { $_ -match '^\d+$' } | Select-Object -Last 1
    Write-Host "[stop_bridge] Killing PID $pidLine" -ForegroundColor Yellow
    Stop-Process -Id $pidLine -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "[stop_bridge] Port 8001 not occupied, skip" -ForegroundColor Gray
}

Write-Host "[stop_bridge] Stopping port 50051 (siro-runtime)..." -ForegroundColor Cyan
$port50051 = netstat -ano | Select-String ":50051 " | Select-String "LISTENING"
if ($port50051) {
    $pidLine = ($port50051 -split '\s+') | Where-Object { $_ -match '^\d+$' } | Select-Object -Last 1
    Write-Host "[stop_bridge] Killing PID $pidLine" -ForegroundColor Yellow
    Stop-Process -Id $pidLine -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "[stop_bridge] Port 50051 not occupied, skip" -ForegroundColor Gray
}

Start-Sleep -Seconds 2
Write-Host "[stop_bridge] Done" -ForegroundColor Green

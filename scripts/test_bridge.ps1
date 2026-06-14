# scripts/test_bridge.ps1
#
# 診斷 bridge 跟 WebSocket 是不是真的能連
# 從 PowerShell 直接跑、模擬 Unity 的連線

Write-Host "=== 1. Check port 8001 ===" -ForegroundColor Cyan
$port8001 = netstat -ano | Select-String ":8001 "
if ($port8001) {
    Write-Host "[OK] port 8001 in LISTENING" -ForegroundColor Green
    $port8001 | ForEach-Object { Write-Host "    $_" }
} else {
    Write-Host "[FAIL] port 8001 NOT listening, bridge not running" -ForegroundColor Red
    Write-Host "       Run: powershell -File scripts\start_bridge.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== 2. Check /health ===" -ForegroundColor Cyan
try {
    $health = Invoke-WebRequest http://127.0.0.1:8001/health -UseBasicParsing | ConvertFrom-Json
    Write-Host "[OK] bridge health: $($health.status)" -ForegroundColor Green
    Write-Host "    hermes: $($health.hermes_available)"
    Write-Host "    version: $($health.bridge_version)"
} catch {
    Write-Host "[FAIL] bridge /health did not respond: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== 3. Test WebSocket (via Python, no System.Net.WebSockets in PS5) ===" -ForegroundColor Cyan
$python = "C:\Users\jason\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"

# Write Python code to temp file (avoid PowerShell mangling ws://)
$pyFile = Join-Path $env:TEMP "test_bridge_ws.py"
@'
import asyncio, websockets, json, sys
async def t():
    try:
        uri = "ws://127.0.0.1:8001/ws"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type":"ping"}))
            r = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print("[OK] WS connected, received:", r, flush=True)
            sys.exit(0)
    except Exception as e:
        print("[FAIL] WS connect failed:", e, flush=True)
        sys.exit(1)
asyncio.run(t())
'@ | Out-File -FilePath $pyFile -Encoding utf8

try {
    $output = & $python $pyFile 2>&1
    $output | ForEach-Object { Write-Host "    $_" }
} catch {
    Write-Host "[FAIL] Python WS test failed: $_" -ForegroundColor Red
} finally {
    Remove-Item $pyFile -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "=== 4. Conclusion ===" -ForegroundColor Cyan
Write-Host "If 1-3 all [OK]: bridge is fully working, Unity issue is on Unity side" -ForegroundColor Green
Write-Host "  -> Check Unity HermesBridgeClient ServerUrl is ws://127.0.0.1:8001/ws" -ForegroundColor Yellow
Write-Host "  -> Check Unity side firewall not blocking ws://" -ForegroundColor Yellow
Write-Host "  -> Look at Unity Console error, paste it back to me" -ForegroundColor Yellow

# scripts/start_bridge.ps1
#
# PowerShell port of start_bridge.sh
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start_bridge.ps1
#
# 1. Kill orphan processes on port 8001 / 50051
# 2. Start siro-runtime (port 50051)
# 3. Start bridge (port 8001)
# 4. Verify both running

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

# Load .env
Write-Host "[start_bridge] Loading .env..." -ForegroundColor Cyan
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

# 1. Kill port 8001 occupant
Write-Host "[start_bridge] Checking port 8001..." -ForegroundColor Cyan
$port8001 = netstat -ano | Select-String ":8001 " | Select-String "LISTENING"
if ($port8001) {
    $pidLine = ($port8001 -split '\s+') | Where-Object { $_ -match '^\d+$' } | Select-Object -Last 1
    Write-Host "[start_bridge] Port 8001 occupied by PID=$pidLine, killing..." -ForegroundColor Yellow
    Stop-Process -Id $pidLine -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Kill port 50051 occupant (siro-runtime)
Write-Host "[start_bridge] Checking port 50051..." -ForegroundColor Cyan
$port50051 = netstat -ano | Select-String ":50051 " | Select-String "LISTENING"
if ($port50051) {
    $pidLine = ($port50051 -split '\s+') | Where-Object { $_ -match '^\d+$' } | Select-Object -Last 1
    Write-Host "[start_bridge] Port 50051 occupied by PID=$pidLine, killing..." -ForegroundColor Yellow
    Stop-Process -Id $pidLine -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# 2. Start siro-runtime
$siroRuntime = "$repoRoot\os-runtime\target\debug\siro-runtime.exe"
if (Test-Path $siroRuntime) {
    Write-Host "[start_bridge] Starting siro-runtime..." -ForegroundColor Cyan
    $env:PROTOC = "C:\Users\jason\tools\protoc.exe"
    $siroProc = Start-Process -FilePath $siroRuntime `
        -ArgumentList "--auto-start=false" `
        -RedirectStandardOutput "C:\Users\jason\AppData\Local\Temp\siro_runtime_out.log" `
        -RedirectStandardError "C:\Users\jason\AppData\Local\Temp\siro_runtime_err.log" `
        -NoNewWindow -PassThru
    Start-Sleep -Seconds 3
    if (Get-Process -Id $siroProc.Id -ErrorAction SilentlyContinue) {
        Write-Host "[start_bridge] [OK] siro-runtime started (PID=$($siroProc.Id), port 50051)" -ForegroundColor Green
    } else {
        Write-Host "[start_bridge] [FAIL] siro-runtime did not start, see err log" -ForegroundColor Red
        if (Test-Path "C:\Users\jason\AppData\Local\Temp\siro_runtime_err.log") {
            Get-Content "C:\Users\jason\AppData\Local\Temp\siro_runtime_err.log" -Tail 10
        }
        exit 1
    }
} else {
    Write-Host "[start_bridge] [WARN] siro-runtime binary not found: $siroRuntime" -ForegroundColor Yellow
    Write-Host "[start_bridge]        Run: cd os-runtime; cargo build" -ForegroundColor Yellow
}

# 3. Start bridge
Write-Host "[start_bridge] Starting bridge..." -ForegroundColor Cyan
$env:SIRO_RUNTIME_ENABLED = "true"
$env:SIRO_USE_AGENT_MODE = "true"
$env:SIRO_TRUST_MODE = "true"
$python = "C:\Users\jason\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"

$bridgeProc = Start-Process -FilePath $python `
    -ArgumentList "-m", "bridge.main" `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput "C:\Users\jason\AppData\Local\Temp\bridge_out.log" `
    -RedirectStandardError "C:\Users\jason\AppData\Local\Temp\bridge_err.log" `
    -NoNewWindow -PassThru
Start-Sleep -Seconds 6

# 4. Verify
if (Get-Process -Id $bridgeProc.Id -ErrorAction SilentlyContinue) {
    Write-Host "[start_bridge] [OK] bridge started (PID=$($bridgeProc.Id), port 8001)" -ForegroundColor Green
    try {
        $health = Invoke-WebRequest http://127.0.0.1:8001/health -UseBasicParsing -TimeoutSec 3 | ConvertFrom-Json
        Write-Host "[start_bridge]    /health = $($health.status) hermes=$($health.hermes_available)" -ForegroundColor Green
    } catch {
        Write-Host "[start_bridge] [WARN] /health not ready, may need more startup time" -ForegroundColor Yellow
    }
} else {
    Write-Host "[start_bridge] [FAIL] bridge did not start, see err log" -ForegroundColor Red
    if (Test-Path "C:\Users\jason\AppData\Local\Temp\bridge_err.log") {
        Get-Content "C:\Users\jason\AppData\Local\Temp\bridge_err.log" -Tail 20
    }
    exit 1
}

Write-Host ""
Write-Host "[start_bridge] All started successfully" -ForegroundColor Green
Write-Host "[start_bridge]    Bridge logs: Get-Content C:\Users\jason\AppData\Local\Temp\bridge_out.log -Tail 20 -Wait"
Write-Host "[start_bridge]    Stop: powershell -File scripts\stop_bridge.ps1"
Write-Host "[start_bridge]    Diagnostic: powershell -File scripts\test_bridge.ps1"

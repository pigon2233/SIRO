# run-bridge.ps1 — 一鍵啟動 SIRO bridge
#
# 用法：
#   .\run-bridge.ps1              # 預設（streaming on、agent_os on）
#   .\run-bridge.ps1 -NoStreaming # 關 streaming
#   .\run-bridge.ps1 -NoAgentOS   # 關 AgentOS（走 v0.2 sync 路徑）
#   .\run-bridge.ps1 -Port 8002   # 自訂 port（預設 8001）
#
# 預設行為：
#   - cwd 切到 SIRO 專案根目錄
#   - 啟用 SIRO_STREAMING=true  （TTFT < 5s 量測需要）
#   - 啟用 SIRO_USE_AGENT_OS=true（v0.4+ 預設翻 true）
#   - python -m bridge.main 跑起來
#
# 停：Ctrl+C

param(
    [switch]$NoStreaming = $false,
    [switch]$NoAgentOS = $false,
    [int]$Port = 0
)

# 切到 SIRO 專案根目錄（這支 script 所在位置）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 設環境變數
$env:SIRO_STREAMING = if ($NoStreaming) { "false" } else { "true" }
$env:SIRO_USE_AGENT_OS = if ($NoAgentOS) { "false" } else { "true" }
if ($Port -gt 0) {
    $env:BRIDGE_PORT = "$Port"
}

Write-Host ""
Write-Host "╔════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  SIRO Bridge Launcher                  ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  cwd:           $(Get-Location)" -ForegroundColor Gray
Write-Host "  SIRO_STREAMING: $env:SIRO_STREAMING" -ForegroundColor $(if ($env:SIRO_STREAMING -eq "true") { "Green" } else { "Yellow" })
Write-Host "  SIRO_USE_AGENT_OS: $env:SIRO_USE_AGENT_OS" -ForegroundColor $(if ($env:SIRO_USE_AGENT_OS -eq "true") { "Green" } else { "Yellow" })
if ($Port -gt 0) {
    Write-Host "  BRIDGE_PORT:   $Port" -ForegroundColor Yellow
} else {
    Write-Host "  BRIDGE_PORT:   8001 (default)" -ForegroundColor Gray
}
Write-Host ""
Write-Host "  按 Ctrl+C 停止" -ForegroundColor Gray
Write-Host ""

# 啟動 bridge
python -m bridge.main

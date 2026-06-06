# run-bridge.ps1 - One-click SIRO bridge launcher
#
# Usage:
#   .\run-bridge.ps1                       # default (streaming on, agent_os on, port 8001)
#   .\run-bridge.ps1 -NoStreaming          # disable SSE streaming
#   .\run-bridge.ps1 -NoAgentOS            # disable AgentOS (v0.2 sync path)
#   .\run-bridge.ps1 -Port 8002            # custom port (default 8001)
#   .\run-bridge.ps1 -HermesPath "C:\path\to\hermes.exe"  # explicit hermes path
#
# Defaults:
#   - SIRO_STREAMING=true        (TTFT < 5s measurement)
#   - SIRO_USE_AGENT_OS=true     (v0.4+ default)
#   - python -m bridge.main
#
# Stop: Ctrl+C

param(
    [switch]$NoStreaming = $false,
    [switch]$NoAgentOS = $false,
    [int]$Port = 0,
    [string]$HermesPath = ""
)

# Switch to SIRO project root (where this script lives)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Set environment variables
$env:SIRO_STREAMING = if ($NoStreaming) { "false" } else { "true" }
$env:SIRO_USE_AGENT_OS = if ($NoAgentOS) { "false" } else { "true" }
if ($Port -gt 0) {
    $env:BRIDGE_PORT = "$Port"
}
if ($HermesPath -ne "") {
    $env:HERMES_BIN_PATH = $HermesPath
}

# Print config banner
$streamingColor = if ($env:SIRO_STREAMING -eq "true") { "Green" } else { "Yellow" }
$agentOSColor = if ($env:SIRO_USE_AGENT_OS -eq "true") { "Green" } else { "Yellow" }
$portColor = if ($Port -gt 0) { "Yellow" } else { "Gray" }
$portValue = if ($Port -gt 0) { "$Port" } else { "8001 (default)" }
$hermesValue = if ($env:HERMES_BIN_PATH) { $env:HERMES_BIN_PATH } else { "(not set, will use PATH lookup)" }
$hermesColor = if ($env:HERMES_BIN_PATH) { "Green" } else { "Gray" }
$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) { $pythonPath = "python not found" }

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  SIRO Bridge Launcher" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  cwd:               $(Get-Location)" -ForegroundColor Gray
Write-Host "  python:            $pythonPath" -ForegroundColor Gray
Write-Host "  SIRO_STREAMING:    $env:SIRO_STREAMING" -ForegroundColor $streamingColor
Write-Host "  SIRO_USE_AGENT_OS: $env:SIRO_USE_AGENT_OS" -ForegroundColor $agentOSColor
Write-Host "  BRIDGE_PORT:       $portValue" -ForegroundColor $portColor
Write-Host "  HERMES_BIN_PATH:   $hermesValue" -ForegroundColor $hermesColor
Write-Host ""
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

# Launch bridge
python -m bridge.main


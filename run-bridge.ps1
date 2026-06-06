# run-bridge.ps1 - One-click SIRO bridge launcher
#
# Usage:
#   .\run-bridge.ps1                              # default (streaming on, agent_os on, port 8001)
#   .\run-bridge.ps1 -NoStreaming                 # disable SSE streaming
#   .\run-bridge.ps1 -NoAgentOS                   # disable AgentOS (v0.2 sync path)
#   .\run-bridge.ps1 -Port 8002                   # custom port (default 8001)
#   .\run-bridge.ps1 -HermesPath "C:\hermes.exe"  # override hermes path
#   .\run-bridge.ps1 -HermesTimeout 300           # override hermes timeout (default 180s)
#
# Defaults (apply only if env var not already set):
#   - SIRO_STREAMING=true        (TTFT < 5s measurement)
#   - SIRO_USE_AGENT_OS=true     (v0.4+ default)
#   - HERMES_BIN_PATH=<user hermes-agent path>   (auto-detect or override)
#   - HERMES_TIMEOUT=180         (LLM call timeout in seconds)
#   - PYTHONPATH=<project root>  (so 'from bridge.X' imports work)
#   - python -m bridge.main
#
# Stop: Ctrl+C

param(
    [switch]$NoStreaming = $false,
    [switch]$NoAgentOS = $false,
    [int]$Port = 0,
    [string]$HermesPath = "",
    [int]$HermesTimeout = 0
)

# Switch to SIRO project root (where this script lives)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Set environment variables (only if not already set, so user override wins)
$env:SIRO_STREAMING = if ($NoStreaming) { "false" } else { "true" }
$env:SIRO_USE_AGENT_OS = if ($NoAgentOS) { "false" } else { "true" }
if ($Port -gt 0) {
    $env:BRIDGE_PORT = "$Port"
}
if ($HermesPath -ne "") {
    $env:HERMES_BIN_PATH = $HermesPath
}
if ($HermesTimeout -gt 0) {
    $env:HERMES_TIMEOUT = "$HermesTimeout"
}
if (-not $env:HERMES_BIN_PATH) {
    # Auto-detect common locations (avoid hard-coding user-specific path)
    $candidates = @(
        "$HOME\.local\bin\hermes",
        "$HOME\hermes-agent\.venv\Scripts\hermes.exe",
        "$HOME\AppData\Local\hermes\hermes-agent\.venv\Scripts\hermes.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            $env:HERMES_BIN_PATH = (Resolve-Path $candidate).Path
            break
        }
    }
}
if (-not $env:HERMES_TIMEOUT) {
    $env:HERMES_TIMEOUT = "180"
}
if (-not $env:PYTHONPATH) {
    $env:PYTHONPATH = $ScriptDir
}

# Load user-specific config if exists (git-ignored)
$userConfig = Join-Path $ScriptDir "bridge.config.ps1"
if (Test-Path $userConfig) {
    . $userConfig
    Write-Host "  Loaded: bridge.config.ps1 (user-specific overrides)" -ForegroundColor DarkGray
}

# Print config banner
$streamingColor = if ($env:SIRO_STREAMING -eq "true") { "Green" } else { "Yellow" }
$agentOSColor = if ($env:SIRO_USE_AGENT_OS -eq "true") { "Green" } else { "Yellow" }
$portColor = if ($Port -gt 0) { "Yellow" } else { "Gray" }
$portValue = if ($Port -gt 0) { "$Port" } else { "8001 (default)"
}
$hermesValue = if ($env:HERMES_BIN_PATH) { $env:HERMES_BIN_PATH } else { "(not found - chat may fail)" }
$hermesColor = if ($env:HERMES_BIN_PATH) { "Green" } else { "Red" }
$timeoutValue = $env:HERMES_TIMEOUT
$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) { $pythonPath = "python not found" }
$pypathValue = if ($env:PYTHONPATH) { $env:PYTHONPATH } else { "(not set)" }
$pypathColor = if ($env:PYTHONPATH) { "Green" } else { "Yellow" }

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  SIRO Bridge Launcher" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  cwd:               $(Get-Location)" -ForegroundColor Gray
Write-Host "  python:            $pythonPath" -ForegroundColor Gray
Write-Host "  PYTHONPATH:        $pypathValue" -ForegroundColor $pypathColor
Write-Host "  SIRO_STREAMING:    $env:SIRO_STREAMING" -ForegroundColor $streamingColor
Write-Host "  SIRO_USE_AGENT_OS: $env:SIRO_USE_AGENT_OS" -ForegroundColor $agentOSColor
Write-Host "  BRIDGE_PORT:       $portValue" -ForegroundColor $portColor
Write-Host "  HERMES_BIN_PATH:   $hermesValue" -ForegroundColor $hermesColor
Write-Host "  HERMES_TIMEOUT:    $timeoutValue" -ForegroundColor Gray
Write-Host ""
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

# If hermes not found, print helpful setup instructions (not fatal -
# MiniMax SSE can serve as primary LLM)
if (-not $env:HERMES_BIN_PATH) {
    Write-Host "================================================================" -ForegroundColor Yellow
    Write-Host "  WARNING: HERMES_BIN_PATH not set / not auto-detected" -ForegroundColor Yellow
    Write-Host "================================================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Bridge will start, but Hermes-backed LLM calls will fail." -ForegroundColor Yellow
    Write-Host "  If you use MiniMax-M3 SSE streaming (default), this is OK." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  To install Hermes, run:" -ForegroundColor White
    Write-Host "    bash agent/install.sh" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  To use a custom install path, either:" -ForegroundColor White
    Write-Host "    1. Pass to this script:    .\run-bridge.ps1 -HermesPath 'D:\hermes\hermes.exe'" -ForegroundColor Cyan
    Write-Host "    2. Set in user config:     cp bridge.config.ps1.example bridge.config.ps1" -ForegroundColor Cyan
    Write-Host "                                # then edit and uncomment HERMES_BIN_PATH" -ForegroundColor Cyan
    Write-Host "    3. Set in your PowerShell profile (permanent):" -ForegroundColor Cyan
    Write-Host "       notepad \$PROFILE   # add:  \$env:HERMES_BIN_PATH = 'D:\hermes\hermes.exe'" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Yellow
    Write-Host ""
}

# Launch bridge
python -m bridge.main


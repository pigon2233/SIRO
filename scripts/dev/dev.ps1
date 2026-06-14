# dev.ps1 - SIRO 開發一鍵啟動（Windows PowerShell）
#
# 用法：
#   .\scripts\dev\dev.ps1              # 啟動 bridge
#   .\scripts\dev\dev.ps1 -Cmd test    # 跑測試
#   .\scripts\dev\dev.ps1 -Cmd coverage
#   .\scripts\dev\dev.ps1 -Cmd check
#   .\scripts\dev\dev.ps1 -Cmd rust

[CmdletBinding()]
param(
    [string]$Cmd = "bridge"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $ProjectRoot

switch ($Cmd) {
    "bridge" {
        Write-Host "→ 啟動 bridge" -ForegroundColor Cyan
        python -m bridge.main
    }
    "test" {
        Write-Host "→ 跑 bridge tests" -ForegroundColor Cyan
        python -m pytest tests/bridge/ -v
    }
    "coverage" {
        Write-Host "→ 跑 bridge tests + coverage" -ForegroundColor Cyan
        python -m pytest tests/bridge/ --cov=bridge --cov-report=term-missing --cov-report=html
    }
    "check" {
        Write-Host "→ 環境檢查" -ForegroundColor Cyan
        python scripts/dev/check-env.py
    }
    "rust" {
        Write-Host "→ cargo build os-runtime" -ForegroundColor Cyan
        Push-Location os-runtime
        try { cargo build } finally { Pop-Location }
    }
    "fmt" {
        Write-Host "→ 格式化 Python + Rust" -ForegroundColor Cyan
        python -m black bridge/ tests/
        python -m ruff check --fix bridge/ tests/
        Push-Location os-runtime
        try { cargo fmt; cargo clippy -- -D warnings } finally { Pop-Location }
    }
    "docs" {
        Write-Host "→ 重新生成 HTML docs" -ForegroundColor Cyan
        python scripts/build-docs-html.py
    }
    default {
        Write-Host "Unknown command: $Cmd" -ForegroundColor Red
        Write-Host "Available: bridge | test | coverage | check | rust | fmt | docs" -ForegroundColor Red
        exit 1
    }
}

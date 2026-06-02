#!/usr/bin/env bash
# agent/install.sh - SIRO 專屬的 Hermes Agent 安裝腳本
#
# 這個腳本會呼叫 Hermes 官方的 install.sh，然後做 SIRO 需要的後續設定。
# 官方 install.sh 處理：uv、Python 3.11、Node.js、hermes CLI、Python venv。
# 本腳本額外處理：把 hermes 路徑寫進 .env.example 註解、產生 SIRO 用的目錄。
#
# 支援：Linux / macOS / WSL2
# Windows 原生 PowerShell 請直接跑官方 install.ps1（README 有指令）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 顏色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { printf "${GREEN}[INFO]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
error() { printf "${RED}[ERROR]${NC} %s\n" "$*"; exit 1; }

# 1. 檢查前置
info "檢查必要工具..."
command -v curl >/dev/null 2>&1 || error "缺少 curl，請先安裝"
command -v git  >/dev/null 2>&1 || error "缺少 git，請先安裝"

# 2. 呼叫官方安裝腳本
info "呼叫 Hermes Agent 官方安裝腳本..."
info "（這會安裝 uv、Python 3.11、Node.js、hermes CLI，需要幾分鐘）"
echo

curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# 3. 把 hermes 放進 PATH（如果是 ~/.local/bin/hermes）
HERMES_BIN="$HOME/.local/bin/hermes"
if [[ -x "$HERMES_BIN" ]]; then
    info "找到 hermes: $HERMES_BIN"
    # 確保 ~/.local/bin 在 PATH
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        warn "$HOME/.local/bin 不在 PATH 中"
        warn "請把以下加入你的 ~/.bashrc 或 ~/.zshrc："
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
    # 讓當前 shell 也能用
    export PATH="$HOME/.local/bin:$PATH"
else
    warn "找不到 hermes CLI，可能安裝失敗或在不同路徑"
    warn "請確認 'hermes --version' 能不能跑"
fi

# 4. 驗證安裝
info "驗證 hermes CLI..."
if "$HERMES_BIN" --version >/dev/null 2>&1; then
    VERSION=$("$HERMES_BIN" --version 2>&1 | head -1)
    info "✓ Hermes 安裝成功: $VERSION"
else
    error "Hermes 沒有安裝成功，請看上方的錯誤訊息"
fi

# 5. 提示下一步
echo
info "安裝完成！下一步："
echo "  1. 跑 'hermes setup' 設定 LLM provider 與 API key"
echo "  2. 跑 'bash agent/verify.sh' 確認可以跟 Hermes 對話"
echo "  3. 設定 .env 檔（複製 .env.example）：cp .env.example .env"
echo
info "Hermes 設定檔位置: \$HOME/.hermes/"
info "Hermes 技能位置:   \$HOME/.hermes/skills/"

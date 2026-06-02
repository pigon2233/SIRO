#!/usr/bin/env bash
# agent/install.sh - SIRO 專屬的 Hermes Agent 安裝腳本
#
# 兩種模式：
#   A) 線上（官方 installer）: curl install.sh | bash
#   B) 離線（clone repo + uv sync）: 適合 WSL installer 壞掉、或沒網路時
#
# 自動偵測哪個能用。線上優先。

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

# 0. 檢查前置
info "檢查必要工具..."
command -v curl >/dev/null 2>&1 || error "缺少 curl，請先安裝"
command -v git  >/dev/null 2>&1 || error "缺少 git，請先安裝"
command -v uv   >/dev/null 2>&1 || warn "找不到 uv（建議裝：https://docs.astral.sh/uv/）"


# Helper: 把 hermes 的實際位置寫進 SIRO/.env.example 註解
write_hermes_path_to_env_example() {
    local hermes_path="$1"
    if [[ -f "$REPO_ROOT/.env.example" ]]; then
        # .env.example 裡的 HERMES_BIN_PATH=... 換成實際路徑
        if grep -q "^HERMES_BIN_PATH=" "$REPO_ROOT/.env.example"; then
            # 用 awk 替換那一行
            local tmp_file
            tmp_file=$(mktemp)
            awk -v new_path="HERMES_BIN_PATH=$hermes_path" '
                /^HERMES_BIN_PATH=/ { print new_path; next }
                { print }
            ' "$REPO_ROOT/.env.example" > "$tmp_file"
            mv "$tmp_file" "$REPO_ROOT/.env.example"
        fi
    fi
}

# ============================================================
# 模式 A: 線上安裝（官方 installer）
# ============================================================
try_online_install() {
    info "嘗試線上安裝（官方 installer）..."

    # 測試能不能抓到 installer（快速 timeout）
    if ! curl -fsSL --max-time 15 https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh -o /tmp/hermes-install-test.sh 2>/dev/null; then
        warn "無法下載官方 installer（網路問題）"
        return 1
    fi
    rm -f /tmp/hermes-install-test.sh

    info "下載並執行官方 installer..."
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

    # 找 hermes
    local hermes_bin="$HOME/.local/bin/hermes"
    if [[ ! -x "$hermes_bin" ]]; then
        warn "installer 跑完但找不到 $hermes_bin"
        return 1
    fi

    info "✓ Hermes 透過官方 installer 安裝完成"
    write_hermes_path_to_env_example "$hermes_bin"
    return 0
}

# ============================================================
# 模式 B: 離線安裝（clone + uv sync）
# ============================================================
try_offline_install() {
    info "嘗試離線安裝（clone repo + uv sync）..."

    local hermes_repo="$HOME/hermes-agent"

    if [[ ! -d "$hermes_repo" ]]; then
        info "Clone hermes-agent repo..."
        git clone --depth 1 https://github.com/NousResearch/hermes-agent.git "$hermes_repo" || {
            warn "Clone 失敗"
            return 1
        }
    else
        info "已存在 $hermes_repo"
    fi

    cd "$hermes_repo"

    if ! command -v uv >/dev/null 2>&1; then
        warn "需要 uv 來裝依賴，請先裝：https://docs.astral.sh/uv/"
        return 1
    fi

    info "用 uv sync 裝 hermes-agent..."
    if ! uv sync --extra all 2>&1 | tail -5; then
        warn "uv sync 失敗"
        return 1
    fi

    # 路徑
    local hermes_bin
    if [[ -f "$hermes_repo/.venv/Scripts/hermes.exe" ]]; then
        # Windows
        hermes_bin="$hermes_repo/.venv/Scripts/hermes.exe"
    elif [[ -f "$hermes_repo/.venv/bin/hermes" ]]; then
        # Linux/macOS
        hermes_bin="$hermes_repo/.venv/bin/hermes"
    else
        warn "找不到 hermes binary"
        return 1
    fi

    info "✓ Hermes 透過 clone+uv 安裝完成: $hermes_bin"
    write_hermes_path_to_env_example "$hermes_bin"
    return 0
}

# ============================================================
# 主流程
# ============================================================

# 先試線上
if try_online_install; then
    :
else
    warn "線上安裝失敗，改用離線模式"
    if ! try_offline_install; then
        error "兩種安裝方式都失敗。請手動裝 Hermes 後設 HERMES_BIN_PATH 環境變數"
    fi
fi

# 最終驗證
HERMES_PATH=$(grep "^HERMES_BIN_PATH=" "$REPO_ROOT/.env.example" | cut -d= -f2-)
info "驗證 hermes (路徑: $HERMES_PATH)..."
if "$HERMES_PATH" --version 2>&1 | head -3; then
    info "✓ hermes CLI 可用"
else
    error "hermes 不可用，請看上方錯誤"
fi

# 提示下一步
echo
info "安裝完成！下一步："
echo "  1. 跑 'hermes setup' 設定 LLM provider 與 API key"
echo "  2. 跑 'bash agent/verify.sh' 確認可以跟 Hermes 對話"
echo "  3. 設定 .env 檔（複製 .env.example）：cp .env.example .env"
echo
info "Hermes 設定檔位置: \$HOME/.hermes/"
info "Hermes 技能位置:   \$HOME/.hermes/skills/"

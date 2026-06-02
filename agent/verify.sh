#!/usr/bin/env bash
# agent/verify.sh - 驗證 Hermes Agent 已經正確安裝且能回應
#
# 這個腳本做四件事：
#   1. 檢查 hermes CLI 存在
#   2. 跑 hermes --version
#   3. 跑 hermes doctor（如果存在）
#   4. 跑一次 hermes -p（prompt 模式）問個簡單問題
#
# 如果全部通過，bridge/ 才能正常運作。

set -uo pipefail

# 顏色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { printf "${GREEN}✓${NC} %s\n" "$*"; }
fail() { printf "${RED}✗${NC} %s\n" "$*"; }
info() { printf "${BLUE}[INFO]${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }

ERRORS=0

# 找 hermes 二進位
HERMES_BIN="${HERMES_BIN:-}"
if [[ -z "$HERMES_BIN" ]]; then
    if command -v hermes >/dev/null 2>&1; then
        HERMES_BIN="$(command -v hermes)"
    elif [[ -x "$HOME/.local/bin/hermes" ]]; then
        HERMES_BIN="$HOME/.local/bin/hermes"
    fi
fi

# 1. 檢查 hermes CLI
info "Step 1: 檢查 hermes CLI 存在"
if [[ -z "$HERMES_BIN" ]]; then
    fail "找不到 hermes 指令"
    echo "  請先跑 'bash agent/install.sh' 安裝 Hermes"
    ERRORS=$((ERRORS+1))
else
    pass "找到 hermes: $HERMES_BIN"
fi

# 2. 跑 hermes --version
info "Step 2: 檢查 hermes 版本"
if [[ -n "$HERMES_BIN" ]]; then
    if VERSION=$("$HERMES_BIN" --version 2>&1); then
        pass "版本: $VERSION"
    else
        fail "hermes --version 執行失敗"
        ERRORS=$((ERRORS+1))
    fi
fi

# 3. 跑 hermes doctor（如果支援）
info "Step 3: 跑 hermes doctor（如果支援）"
if [[ -n "$HERMES_BIN" ]]; then
    if "$HERMES_BIN" doctor --help >/dev/null 2>&1 || "$HERMES_BIN" help doctor >/dev/null 2>&1; then
        if "$HERMES_BIN" doctor 2>&1 | tail -20; then
            pass "doctor 跑完，看上面有沒有錯誤"
        else
            warn "doctor 沒跑完，可能設定有問題"
        fi
    else
        warn "這個版本的 hermes 沒有 doctor 指令，跳過"
    fi
fi

# 4. 測試 prompt（單次對話）
info "Step 4: 測試單次對話 (hermes -p '請用一句話回應')"
if [[ -n "$HERMES_BIN" ]]; then
    echo "（這會呼叫 LLM API，可能花 5-30 秒）"
    if "$HERMES_BIN" -p "請用一句話回應：測試成功" 2>&1 | head -5; then
        pass "對話測試有輸出"
    else
        fail "對話測試沒輸出（可能 API key 沒設或 LLM provider 沒設定）"
        echo "  請跑 'hermes setup' 設定 LLM provider"
        ERRORS=$((ERRORS+1))
    fi
fi

# 5. 檢查 .env 設定
info "Step 5: 檢查 .env 設定"
if [[ -f "$PWD/.env" ]]; then
    pass ".env 存在"
    if grep -q "your_nous_api_key_here\|your_openrouter_key_here" "$PWD/.env" 2>/dev/null; then
        warn ".env 還在用預設 API key，記得改成你的"
    fi
else
    warn ".env 不存在，bridge 會用 hermes 自己的設定"
    echo "  如果想用 .env 覆蓋：cp .env.example .env"
fi

# 結論
echo
if [[ $ERRORS -eq 0 ]]; then
    pass "所有檢查通過，bridge/ 應該能正常運作"
    exit 0
else
    fail "$ERRORS 個檢查失敗，請看上方的錯誤訊息"
    exit 1
fi

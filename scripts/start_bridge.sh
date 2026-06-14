#!/usr/bin/env bash
# scripts/start_bridge.sh
#
# 啟動 bridge、順便清掉佔 port 的 orphan process
# 用法：./scripts/start_bridge.sh
#
# v0.4+ 跨平台：自動偵測 Windows / Linux / macOS
# Windows (Git Bash / WSL)：用 powershell + taskkill
# Linux / macOS：用 lsof + kill
#
# v1.5+ env vars 從 .env 讀

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# 偵測 platform
detect_platform() {
    case "$OSTYPE" in
        msys*|cygwin*|win32*)
            echo "windows"
            ;;
        darwin*)
            echo "macos"
            ;;
        linux*)
            echo "linux"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

PLATFORM=$(detect_platform)
echo "[start_bridge] platform: $PLATFORM ($OSTYPE)"

# 砍佔 port 的 process（v0.4+ 跨平台）
free_port() {
    local port=$1
    local pid=""

    case "$PLATFORM" in
        windows)
            # Windows (Git Bash / MSYS)
            pid=$(netstat -ano 2>/dev/null | grep ":$port " | grep LISTENING | awk '{print $NF}' | head -1 || true)
            if [ -n "$pid" ]; then
                echo "[start_bridge]   port $port 被 PID $pid 佔、taskkill..."
                taskkill //F //PID "$pid" 2>/dev/null || powershell -Command "Stop-Process -Id $pid -Force" 2>/dev/null || true
                sleep 2
            fi
            ;;
        macos|linux|*)
            # Linux / macOS：用 lsof
            pid=$(lsof -ti:"$port" 2>/dev/null | head -1 || true)
            if [ -n "$pid" ]; then
                echo "[start_bridge]   port $port 被 PID $pid 佔、kill..."
                kill -9 "$pid" 2>/dev/null || true
                sleep 2
            fi
            ;;
    esac
}

# 檢查 port 是否有人 listen
port_in_use() {
    local port=$1
    case "$PLATFORM" in
        windows)
            netstat -ano 2>/dev/null | grep ":$port " | grep -q LISTENING
            ;;
        *)
            lsof -ti:"$port" >/dev/null 2>&1 || \
            ss -tln 2>/dev/null | grep -q ":$port "
            ;;
    esac
}

# Free port 8001
echo "[start_bridge] 檢查 port 8001..."
if port_in_use 8001; then
    echo "[start_bridge] port 8001 被佔、清掉..."
    free_port 8001
fi

# Free port 50051 (siro-runtime)
echo "[start_bridge] 檢查 port 50051..."
if port_in_use 50051; then
    echo "[start_bridge] port 50051 被佔、清掉..."
    free_port 50051
fi

# 啟動 siro-runtime（v0.4+ 跨平台 binary 偵測）
RUNTIME_BIN="os-runtime/target/debug/siro-runtime"
[ -f "${RUNTIME_BIN}.exe" ] && RUNTIME_BIN="${RUNTIME_BIN}.exe"

# protoc 偵測：env var > PATH
PROTOC_BIN="${PROTOC:-protoc}"
if ! command -v "$PROTOC_BIN" > /dev/null 2>&1; then
    case "$PLATFORM" in
        windows) PROTOC_BIN="protoc.exe" ;;
        *) PROTOC_BIN="protoc" ;;
    esac
fi

if [ -f "$RUNTIME_BIN" ]; then
    echo "[start_bridge] 啟動 siro-runtime ($RUNTIME_BIN)..."
    cd os-runtime
    PROTOC="$PROTOC_BIN" nohup "$RUNTIME_BIN" --auto-start=false > /tmp/siro_runtime.log 2>&1 &
    disown
    cd "$REPO_ROOT"
    sleep 2
    if port_in_use 50051; then
        echo "[start_bridge] siro-runtime 啟動成功 (port 50051)"
    else
        echo "[start_bridge] siro-runtime 啟動失敗、看 /tmp/siro_runtime.log"
    fi
else
    echo "[start_bridge] siro-runtime binary 不存在、跳過（bridge 會標 disabled）"
fi

# 啟動 bridge
echo "[start_bridge] 啟動 bridge..."
export SIRO_RUNTIME_ENABLED=true
export SIRO_USE_AGENT_MODE=true
export SIRO_TRUST_MODE=true

# Python 指令：Windows 用 python、Linux/macOS 用 python3（除非 SIRO_PYTHON_BIN 設了）
if [ -n "$SIRO_PYTHON_BIN" ]; then
    PYTHON_BIN="$SIRO_PYTHON_BIN"
elif [ "$PLATFORM" = "linux" ] || [ "$PLATFORM" = "macos" ]; then
    PYTHON_BIN="python3"
else
    PYTHON_BIN="python"
fi

nohup "$PYTHON_BIN" -m bridge.main > /tmp/bridge.log 2>&1 &
disown
sleep 4

if port_in_use 8001; then
    echo "[start_bridge] ✅ bridge 啟動成功 (port 8001)"
    echo "[start_bridge]    /health = $(curl -s http://127.0.0.1:8001/health)"
    echo "[start_bridge]    /siro/tools = $(curl -s http://127.0.0.1:8001/siro/tools | "$PYTHON_BIN" -c 'import json,sys; d=json.load(sys.stdin); print(d["count"], "tools")' 2>/dev/null || echo '? tools')"
else
    echo "[start_bridge] ❌ bridge 啟動失敗、看 /tmp/bridge.log"
    tail -20 /tmp/bridge.log
fi

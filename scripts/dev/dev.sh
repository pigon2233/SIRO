#!/usr/bin/env bash
# dev.sh - SIRO 開發一鍵啟動（Linux / macOS / WSL）
#
# 用法：
#   bash scripts/dev/dev.sh           # 啟動 bridge
#   bash scripts/dev/dev.sh test      # 跑測試
#   bash scripts/dev/dev.sh coverage  # 跑 coverage
#   bash scripts/dev/dev.sh check     # 環境檢查
#   bash scripts/dev/dev.sh rust      # 編 os-runtime

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

cmd="${1:-bridge}"

case "$cmd" in
    bridge)
        echo "→ 啟動 bridge（dev mode, auto-reload）"
        exec python -m bridge.main
        ;;
    test)
        echo "→ 跑 bridge tests"
        exec python -m pytest tests/bridge/ -v
        ;;
    coverage)
        echo "→ 跑 bridge tests + coverage"
        exec python -m pytest tests/bridge/ --cov=bridge --cov-report=term-missing --cov-report=html
        ;;
    check)
        echo "→ 環境檢查"
        exec python scripts/dev/check-env.py
        ;;
    rust)
        echo "→ cargo build os-runtime"
        (cd os-runtime && cargo build)
        ;;
    fmt)
        echo "→ 格式化 Python + Rust"
        python -m black bridge/ tests/
        python -m ruff check --fix bridge/ tests/
        (cd os-runtime && cargo fmt && cargo clippy -- -D warnings)
        ;;
    docs)
        echo "→ 重新生成 HTML docs"
        exec python scripts/build-docs-html.py
        ;;
    *)
        echo "Unknown command: $cmd" >&2
        echo "Available: bridge | test | coverage | check | rust | fmt | docs" >&2
        exit 1
        ;;
esac

"""
bridge/tools/filesystem.py - v1.5+ 檔案系統工具

提供：
- list_dir: 列出 sandbox 內目錄
- read_file: 讀 sandbox 內檔
- write_file: 寫 sandbox 內檔
- search_files: glob 搜尋
- mkdir: 建子目錄

v1.5.3：list_dir / read_file / write_file 改用 gRPC 呼叫 os-runtime
- 之後 Phase 4 Linux 部署只要改 env var 就 work
- search_files / mkdir 暫時仍用 Python 實作（os-runtime 沒對應 RPC、之後再加）
- Sandbox path check 用 bridge/security.py 的 SandboxPath
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any

from ..security import SandboxPath, SecurityError
# v1.5.3：top-level import 讓 monkeypatch 跟 module attribute 都 work
from . import os_runtime_client

logger = logging.getLogger(__name__)

# 讀檔 / 列表的輸出限制
MAX_FILE_BYTES = 200_000        # 200KB
MAX_DIR_ENTRIES = 1000          # 一次最多列 1000 個 entry
MAX_LINES_PER_READ = 500        # 一次最多讀 500 行
MAX_SEARCH_RESULTS = 200        # 一次最多回 200 個 match


# ============================================================
# Tool definitions (Anthropic tool_use 格式)
# ============================================================

LIST_DIR_TOOL: dict[str, Any] = {
    "name": "list_dir",
    "description": (
        "列出 sandbox 目錄內的檔案與子目錄。路徑必須在 ~/siro-sandbox/ 內。"
        "可以用 recursive=true 遞迴列出所有子目錄。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "default": ".",
                "description": "要列出的目錄路徑。預設 '.' （sandbox 根目錄）。",
            },
            "recursive": {
                "type": "boolean",
                "default": False,
                "description": "是否遞迴列出所有子目錄",
            },
        },
        "required": [],
    },
}


READ_FILE_TOOL: dict[str, Any] = {
    "name": "read_file",
    "description": (
        "讀取 sandbox 內的文字檔案。路徑必須在 ~/siro-sandbox/ 內。"
        "大檔會被截斷（最多 500 行 / 200KB）。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要讀的檔案路徑（相對於 sandbox 根目錄）",
            },
            "max_lines": {
                "type": "integer",
                "default": 200,
                "minimum": 1,
                "maximum": MAX_LINES_PER_READ,
                "description": f"最多讀幾行（最大 {MAX_LINES_PER_READ}）",
            },
        },
        "required": ["path"],
    },
}


WRITE_FILE_TOOL: dict[str, Any] = {
    "name": "write_file",
    "description": (
        "寫入或覆蓋 sandbox 內的文字檔案。路徑必須在 ~/siro-sandbox/ 內。"
        "父目錄不存在會自動建。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "檔案路徑（相對於 sandbox 根目錄）"},
            "content": {"type": "string", "description": "要寫入的檔案內容"},
        },
        "required": ["path", "content"],
    },
}


SEARCH_FILES_TOOL: dict[str, Any] = {
    "name": "search_files",
    "description": (
        "用 glob pattern 在 sandbox 內搜尋檔案。"
        "例如 pattern='*.txt' 找所有 .txt 檔、pattern='notes/*.md' 找 notes 下所有 .md。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "glob pattern, e.g. '*.txt' 或 'notes/*.md'",
            },
            "path": {
                "type": "string",
                "default": ".",
                "description": "搜尋的根目錄（預設 sandbox 根）",
            },
        },
        "required": ["pattern"],
    },
}


MKDIR_TOOL: dict[str, Any] = {
    "name": "mkdir",
    "description": "在 sandbox 內建立子目錄（parent 不存在會自動建、已經存在不報錯）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要建的目錄路徑"},
        },
        "required": ["path"],
    },
}


# ============================================================
# Executors
# ============================================================

async def execute(args: dict, ctx: dict) -> dict:
    """list_dir executor（直接叫 list_dir 會撞到 built-in、所以叫 execute）"""
    return await list_dir_impl(args, ctx)


async def list_dir(args: dict, ctx: dict) -> dict:
    """沒用到、_register 時被擠掉了、保留以防 tool 名 alias"""
    return await list_dir_impl(args, ctx)


async def list_dir_impl(args: dict, ctx: dict) -> dict:
    path_str = args.get("path", ".")
    recursive = bool(args.get("recursive", False))

    # v1.5.3：透過 gRPC 呼叫 os-runtime 的 ListDirectory
    from .os_runtime_client import get_os_runtime_client
    user_id = ctx.get("user_id", "bridge")
    result = get_os_runtime_client().list_directory(
        path=path_str,
        recursive=recursive,
        user_id=user_id,
    )
    if "error" in result and "entries" not in result:
        return result

    entries = result.get("entries", [])
    # 補上 truncated 訊息（如果 Rust 端有標 truncated）
    if result.get("truncated") and entries and "truncated" not in entries[-1]:
        entries.append(f"... (truncated, 超過 {result.get('count', 0)} entries)")

    return {
        "ok": True,
        "path": path_str,
        "entries": entries,
        "count": result.get("count", len(entries)),
    }


async def read_file(args: dict, ctx: dict) -> dict:
    path_str = args.get("path", "")
    max_lines = int(args.get("max_lines", 200))

    if not path_str:
        return {"ok": False, "error": "path 必填"}

    # v1.5.3：透過 gRPC 呼叫 os-runtime 的 ReadFile
    from .os_runtime_client import get_os_runtime_client
    user_id = ctx.get("user_id", "bridge")
    result = get_os_runtime_client().read_file(
        path=path_str,
        max_lines=max_lines,
        user_id=user_id,
    )
    if "error" in result and "content" not in result:
        return result

    return {
        "ok": True,
        "path": path_str,
        "content": result.get("content", ""),
        "line_count": result.get("line_count", 0),
        "truncated": result.get("truncated", False),
    }


async def write_file(args: dict, ctx: dict) -> dict:
    path_str = args.get("path", "")
    content = args.get("content", "")

    if not path_str:
        return {"ok": False, "error": "path 必填"}
    if not isinstance(content, str):
        return {"ok": False, "error": "content 必須是字串"}

    # v1.5.3：透過 gRPC 呼叫 os-runtime 的 WriteFile
    from .os_runtime_client import get_os_runtime_client
    user_id = ctx.get("user_id", "bridge")
    result = get_os_runtime_client().write_file(
        path=path_str,
        content=content,
        user_id=user_id,
    )
    if "error" in result and "bytes_written" not in result:
        return result

    return {
        "ok": True,
        "path": path_str,
        "bytes_written": result.get("bytes_written", 0),
    }


async def search_files(args: dict, ctx: dict) -> dict:
    pattern = args.get("pattern", "")
    path_str = args.get("path", ".")

    if not pattern:
        return {"ok": False, "error": "pattern 必填"}

    try:
        target = SandboxPath(path_str).resolve()
    except SecurityError as e:
        return {"ok": False, "error": str(e)}

    if not target.exists():
        return {"ok": False, "error": f"目錄不存在：{path_str}"}

    matches: list[str] = []
    truncated = False
    try:
        for p in target.rglob("*"):
            # rglob 已經會比對 pattern、但 fnmatch.fnmatch 更精準
            rel = p.relative_to(target)
            if fnmatch.fnmatch(str(rel), pattern) or fnmatch.fnmatch(p.name, pattern):
                marker = "/" if p.is_dir() else ""
                matches.append(f"{rel}{marker}")
                if len(matches) >= MAX_SEARCH_RESULTS:
                    truncated = True
                    break
    except OSError as e:
        return {"ok": False, "error": f"搜尋失敗：{e}"}

    return {
        "ok": True,
        "pattern": pattern,
        "path": path_str,
        "matches": matches,
        "count": len(matches),
        "truncated": truncated,
    }


async def mkdir(args: dict, ctx: dict) -> dict:
    path_str = args.get("path", "")
    if not path_str:
        return {"ok": False, "error": "path 必填"}

    try:
        target = SandboxPath(path_str).resolve()
    except SecurityError as e:
        return {"ok": False, "error": str(e)}

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": f"mkdir 失敗：{e}"}

    return {
        "ok": True,
        "path": path_str,
        "created": not target.exists() or True,  # exist_ok=True 一定算成功
    }

"""
bridge/tools/shell.py - v1.5+ Shell 指令執行

提供：
- run_shell_cmd: 跑 shell 指令（白名單直接跑、其他要 confirmation、block 永遠拒絕）

三層安全（詳見 docs/PLANS/agent-computer-control.md §3.2）：
1. Blocklist：rm -rf /、sudo、dd、mkfs、shutdown、reboot 等永遠拒絕
2. Whitelist：ls、cat、pwd 等 read-only 指令直接跑
3. 其他：透過 confirmation broker 問 user

v1.5.3：實際執行透過 gRPC 呼叫 os-runtime 的 ExecuteCommand RPC
- 之前是 Python 直接 subprocess.run()、現在統一走 Rust os-runtime
- 優點：sandbox 邏輯集中在 Rust、未來 Phase 4 Linux 部署只要改 env var
- trust_mode / blocklist / confirmation 仍在 Python（LLM 工具層的 policy）
"""

from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path
from typing import Any

# v1.5.3：top-level import 讓 monkeypatch 跟 module attribute 都 work
from . import os_runtime_client

# v1.5.3：實際執行透過 gRPC 呼叫 os-runtime
# 不再直接用 Python subprocess


logger = logging.getLogger(__name__)


# ============================================================
# Blocklist / Whitelist
# ============================================================

# 永遠 block 的 patterns（regex、會對整個 cmd 字串比對）
# 設計：用 regex 而不是 exact match、因為 SIRO 可能加奇怪參數
BLOCKLIST_PATTERNS: list[str] = [
    r"\brm\s+(-[a-z]*f[a-z]*\s+)*-[a-z]*r",         # rm -rf、rm -fr、rm -Rf ...
    r"\brm\s+-[a-z]*r[a-z]*\s+(-[a-z]*f|--force)",  # rm -r -f
    r"\brm\s+-[a-z]*\s+/",                           # rm -rf /
    r"\brm\s+/\s*$",                                 # rm /
    r"\bdd\s+",                                       # dd if=... of=...
    r"\bmkfs",                                        # mkfs.ext4 etc
    r"\bfdisk",                                       # fdisk
    r"\bshutdown\b",                                  # shutdown
    r"\breboot\b",                                    # reboot
    r"\bpoweroff\b",
    r"\bhalt\b",
    r"\bsudo\b",                                      # v1.5+ 階段不給 root
    r"\bsu\s+",                                       # su - root
    r"\bchmod\s+777\s+/",                             # chmod 777 /
    r"\bchown\s+.*\s+/",                              # chown root / ...
    r":\(\)\s*\{.*:\|:&.*\}\s*;:",                   # fork bomb 經典
    r"\bmkfs\.",                                      # mkfs.vfat
    r">\s*/dev/sd",                                   # > /dev/sda
    r"\bcurl\s+.*\|\s*(ba)?sh\b",                     # curl | sh
    r"\bwget\s+.*\|\s*(ba)?sh\b",                     # wget | sh
    r"\bnc\s+.*-e\b",                                 # nc -e (reverse shell)
    r"\bbash\s+-i\s+>&\s*/dev/tcp",                   # bash reverse shell
    r"`[^`]*rm\s+-rf",                                # 反引號裡 rm -rf
    r"\$\([^)]*rm\s+-rf",                             # $()裡 rm -rf
    r"rm\s+-[a-z]*[rf][a-z]*\s+~",                    # rm -rf ~
    r"\bsystemctl\s+(stop|disable|mask)\s+siro",      # 把自己停掉
    r"\bkill\s+-9\s+1\b",                             # kill init
    # v0.4+ Linux 特有危險指令
    r"\bmount\s+",                                    # mount（v1.5+ 階段不給 mount filesystem）
    r"\bumount\s+",                                   # umount
    r"\binit\s+[06]\b",                               # init 0 (halt) / init 6 (reboot)
    r"\buseradd\b",                                   # 加帳號
    r"\buserdel\b",                                   # 刪帳號
    r"\bpasswd\b",                                    # 改密碼
    r"\bgroupadd\b",                                  # 加群組
    r"\bvisudo\b",                                    # 改 sudoers
    r"\biptables\b",                                  # 改防火牆規則
    r"\bufw\s+",                                      # ufw
    r"\bip\s+route\s+",                               # 改 routing table
    r"\bsysctl\s+-w",                                 # 改 kernel runtime 參數
    r"\binsmod\b|\brmmod\b|\bmodprobe\s+",            # 載入 kernel module
    r"\bmkfs\.btrfs|\bmkfs\.xfs|\bmkfs\.ext[34]",    # 顯式擋常見 mkfs（已含 mkfs）
    r"\bcrontab\s+-r",                                # 砍 cron jobs
    r"\btruncate\s+-s\s+0\s+/",                       # 把系統檔清空
    r"/dev/(sd|nvme|hd|vd|xvd|mmcblk)",               # 直接操磁碟 device
]

# 安全指令（exact match command name、可以含參數）
# 設計：read-only 指令、不消耗資源、不寫入任何地方
SAFE_COMMANDS: set[str] = {
    # 看檔案
    "ls", "cat", "head", "tail", "less", "more", "file", "stat", "wc",
    # 找東西
    "find", "grep", "egrep", "fgrep", "rg", "ag", "tree",
    # 系統資訊
    "pwd", "whoami", "id", "date", "uptime", "uname", "hostname", "which",
    "whereis", "ps", "df", "free", "top", "env", "printenv", "set",
    # 文字處理
    "echo", "printf", "tr", "sort", "uniq", "cut", "awk", "sed",
    "rev", "tac", "nl", "expand", "unexpand", "fmt", "fold", "column",
    "paste", "join", "comm", "diff", "cmp", "md5sum", "sha1sum", "sha256sum",
    "xxd", "od", "base64",
    # 計時 / 等待
    "sleep", "time",
    # 查 help
    "man", "info", "help", "type", "command", "hash", "alias",
    # 簡單計算
    "expr", "bc", "dc", "test", "[", "true", "false", "yes", "seq",
    # 其他 read-only
    "arch", "nproc", "lscpu", "lsusb", "lspci", "lsmem", "lsblk", "lsof",
    "ss", "netstat", "ip", "ifconfig", "route", "arp",
}


# ============================================================
# Tool definition
# ============================================================

RUN_SHELL_CMD_TOOL: dict[str, Any] = {
    "name": "run_shell_cmd",
    "description": (
        "在 sandbox 內跑 shell 指令。\n"
        "- 安全指令（ls, cat, pwd, grep 等 read-only）會直接跑\n"
        "- 寫入或安裝類指令需要先 request_confirmation 問 user\n"
        "- 危險指令（rm -rf, dd, sudo, ...）永遠會被拒絕\n"
        "回傳 {ok, stdout, stderr, exit_code, blocked}。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cmd": {
                "type": "string",
                "description": "要跑的 shell 指令（例如 'ls notes/'）",
            },
            "timeout_sec": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 120,
                "description": "最多跑幾秒（預設 30）",
            },
        },
        "required": ["cmd"],
    },
}


# ============================================================
# Helpers
# ============================================================

def _is_blocked(cmd: str) -> str | None:
    """檢查 cmd 是不是被 blocklist 擋下

    Returns:
        None if OK、else 擋下的原因
    """
    for pattern in BLOCKLIST_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return f"指令被永遠擋下（blocklist match '{pattern}'）：{cmd[:80]}"
    return None


def _classify_cmd(cmd: str) -> str:
    """分類 cmd 屬於 auto / confirm / block

    Returns:
        "auto" - 第一個指令在 SAFE_COMMANDS
        "confirm" - 不在 SAFE_COMMANDS 但沒被 block
        "block" - 被 blocklist 擋下
    """
    if _is_blocked(cmd) is not None:
        return "block"
    # 拿第一個「word」（shlex split）
    try:
        parts = shlex.split(cmd)
    except ValueError:
        # 解析失敗的 cmd 視為需要 confirm
        return "confirm"
    if not parts:
        return "confirm"
    base = parts[0]
    # 拿 basename（避免 /bin/ls、/usr/bin/ls）
    base = base.rsplit("/", 1)[-1]
    if base in SAFE_COMMANDS:
        return "auto"
    return "confirm"


# ============================================================
# Executor
# ============================================================

async def run_shell_cmd(args: dict, ctx: dict) -> dict:
    cmd = args.get("cmd", "").strip()
    timeout_sec = int(args.get("timeout_sec", 30))

    if not cmd:
        return {"ok": False, "error": "cmd 必填"}

    # v1.5+ trust mode：SIRO_TRUST_MODE=true → blocklist 跳過、confirmation 自動 yes
    # 給 SIRO 完全自主權（user 想看 SIRO 養人格、不想一直按按鈕）
    # 保留：sandbox path check、rate limit、audit log
    import os
    trust_mode = os.environ.get("SIRO_TRUST_MODE", "false").lower() == "true"

    if trust_mode:
        # 跳過 blocklist、直接進 confirm
        category = "confirm"  # 走下面的 trust 路徑
        # log warning（給 user 看 SIRO 跑危險指令時有 trace）
        import logging
        logger.warning(
            f"[shell trust_mode] 跳過 blocklist、直接跑：{cmd[:120]}"
        )
    else:
        # Block check（最優先、擋最危險的）
        block_reason = _is_blocked(cmd)
        if block_reason is not None:
            return {
                "ok": False,
                "blocked": True,
                "error": block_reason,
            }

        # Whitelist check
        category = _classify_cmd(cmd)

    if category == "confirm":
        broker = ctx.get("confirmation_broker")
        if broker is None and not trust_mode:
            return {
                "ok": False,
                "needs_confirmation": True,
                "error": (
                    f"指令 {cmd!r} 需要 user 確認、但目前沒有 confirmation broker。"
                    f"（main.py 還沒接好？請回報 bug）"
                ),
            }

        if trust_mode:
            # 全綠燈：直接放行、不問 user
            import logging
            logger.info(
                f"[shell trust_mode] auto-approve：{cmd[:120]}"
            )
            approved = True
        else:
            # 正常路徑：透過 broker 問 user
            description = f"SIRO 想要跑 shell 指令：{cmd[:120]}"
            approved = await broker.request(
                tool="run_shell_cmd",
                args={"cmd": cmd, "timeout_sec": timeout_sec},
                description=description,
            )
        if not approved:
            return {
                "ok": False,
                "denied": True,
                "error": "user 拒絕這個指令",
            }

    # 跑到這裡：auto / confirm-approved / trust_mode auto-approve

    # v1.5.3：透過 gRPC 呼叫 os-runtime 的 ExecuteCommand
    # 之前是 Python 直接 subprocess.run()、現在統一走 os-runtime
    # 優點：sandbox 邏輯集中在 Rust 層、未來 Phase 4 Linux 部署只要改 env var
    from .os_runtime_client import get_os_runtime_client

    # cwd 用 sandbox 根（os-runtime 端會驗證在 sandbox 內）
    user_id = ctx.get("user_id", "bridge")

    # 如果是 "auto" category、但 trust_mode 也開、傳 trust_mode=true 給 os-runtime
    # （Rust 端純 log 用、不擋、保留 audit 路徑）
    rpc_trust = trust_mode

    client = get_os_runtime_client()
    result = client.execute_command(
        cmd=cmd,
        cwd=".",  # sandbox 根
        timeout_sec=timeout_sec,
        trust_mode=rpc_trust,
        user_id=user_id,
    )

    # 統一結果格式（v1.5+ 之前 Python subprocess 回的形狀）
    if "error" in result and "exit_code" not in result:
        # gRPC 呼叫本身就失敗（os-runtime 沒起來、sandbox 拒絕 etc）
        return result

    return {
        "ok": result.get("ok", False),
        "exit_code": result.get("exit_code", -1),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "stdout_truncated": result.get("stdout_truncated", False),
        "stderr_truncated": result.get("stderr_truncated", False),
        "category": category,
    }

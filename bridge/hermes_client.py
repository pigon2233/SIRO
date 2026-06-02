"""
bridge/hermes_client.py - 封裝 Hermes CLI 為 Python client

設計目標：
- 簡單：用 subprocess 跑 `hermes -p <message>`
- 可測：可以注入假的 binary 路徑做 unit test
- 可升級：之後要換成 MCP client 只需要改這個檔
"""

from __future__ import annotations

import logging
import os
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class HermesResult:
    """Hermes 對話結果"""
    success: bool
    output: str
    error: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None


class HermesClient:
    """Hermes CLI 的 Python 封裝"""

    def __init__(
        self,
        binary_path: Optional[str] = None,
        timeout: int = 60,
        extra_args: Optional[list[str]] = None,
    ):
        """
        Args:
            binary_path: hermes 二進位路徑。留空會自動找 PATH 或 ~/.local/bin/hermes
            timeout: 單次對話 timeout（秒）
            extra_args: 額外的 hermes CLI 參數
        """
        self.binary_path = self._resolve_binary(binary_path)
        self.timeout = timeout
        self.extra_args = extra_args or []

    def _resolve_binary(self, override: Optional[str]) -> str:
        """決定實際要跑的 hermes 指令

        注意：這個方法只決定「用哪個路徑」，不驗證存在。
        驗證存在由 is_available() 處理，這樣可以延後到使用時才檢查。
        """
        if override:
            return override

        # 1. 看環境變數
        env_path = os.environ.get("HERMES_BIN_PATH")
        if env_path:
            return str(Path(env_path).expanduser())

        # 2. 看 PATH
        which = shutil.which("hermes")
        if which:
            return which

        # 3. 看 ~/.local/bin/hermes（Hermes 官方 install script 預設位置）
        default = Path.home() / ".local" / "bin" / "hermes"
        if default.exists():
            return str(default)

        # 找不到時回傳 'hermes'，後面執行會失敗並回報
        return "hermes"

    def is_available(self) -> bool:
        """檢查 hermes CLI 是否可用

        任何例外都視為「不可用」，不應該 propagate 出去。
        """
        try:
            result = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"hermes 不可用: {type(e).__name__}: {e}")
            return False

    def get_version(self) -> Optional[str]:
        """取得 hermes 版本字串"""
        try:
            result = subprocess.run(
                [self.binary_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return (result.stdout or result.stderr).strip().split("\n")[0]
        except Exception as e:
            logger.warning(f"取得 hermes 版本失敗: {e}")
        return None

    def chat(self, message: str, system_prompt: Optional[str] = None) -> HermesResult:
        """
        跑一次 hermes 對話，回傳結果。

        Args:
            message: 使用者訊息
            system_prompt: 系統提示詞（會以環境變數或 stdin 注入，待驗證）

        Returns:
            HermesResult: 包含輸出文字、錯誤、執行時間
        """
        import time

        # 組指令：hermes -p "<message>"
        # 注意：hermes -p 的精確介面待驗證（見 agent/notes/hermes_api_surface.md）
        cmd = [self.binary_path, "-p", message] + self.extra_args

        env = os.environ.copy()
        if system_prompt:
            # 嘗試用環境變數帶 system prompt（依 Hermes 實際支援的方式）
            env["HERMES_SYSTEM_PROMPT"] = system_prompt

        logger.debug(f"執行: {' '.join(cmd[:3])}...")

        start = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
            )
            duration_ms = int((time.time() - start) * 1000)

            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"hermes exit code {result.returncode}"
                logger.error(f"hermes 失敗: {error_msg}")
                return HermesResult(
                    success=False,
                    output=result.stdout.strip(),
                    error=error_msg,
                    exit_code=result.returncode,
                    duration_ms=duration_ms,
                )

            return HermesResult(
                success=True,
                output=result.stdout.strip(),
                error=None,
                exit_code=0,
                duration_ms=duration_ms,
            )

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"hermes timeout after {self.timeout}s")
            return HermesResult(
                success=False,
                output="",
                error=f"hermes 對話 timeout（>{self.timeout}s）",
                exit_code=None,
                duration_ms=duration_ms,
            )
        except FileNotFoundError:
            return HermesResult(
                success=False,
                output="",
                error=f"找不到 hermes 指令: {self.binary_path}",
                exit_code=None,
            )
        except Exception as e:
            logger.exception("hermes 執行時未預期錯誤")
            return HermesResult(
                success=False,
                output="",
                error=f"未預期錯誤: {str(e)}",
                exit_code=None,
            )

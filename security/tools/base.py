from __future__ import annotations
# ============================================================
# security/tools/base.py — 工具基类 (pentest app/tools/base.py 原样移植)
# ============================================================

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """扫描工具抽象基类"""

    name: str = "base"
    command_template: str = ""

    @abstractmethod
    def build_command(self, target: str, options: dict | None = None) -> list[str]:
        """构建命令行参数列表（非 shell=True）"""
        ...

    async def run(
        self, target: str, options: dict | None = None, timeout: int = 3600
    ) -> AsyncGenerator[str, None]:
        """执行命令并逐行 yield stdout/stderr"""
        cmd = self.build_command(target, options)
        logger.info(f"[{self.name}] Running: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            async for line in proc.stdout:  # type: ignore
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                yield text
        except asyncio.CancelledError:
            proc.kill()
            raise
        finally:
            await proc.wait()

        if proc.returncode != 0:
            logger.warning(f"[{self.name}] Exit code: {proc.returncode}")

    @abstractmethod
    def parse_output(self, lines: list[str]) -> list[dict]:
        """解析工具输出，返回结构化结果列表"""
        ...

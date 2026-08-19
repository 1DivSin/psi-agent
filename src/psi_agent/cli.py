from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Annotated

import anyio
import tyro
from tyro import conf

from psi_agent._run import Run
from psi_agent.ai import Ai
from psi_agent.channel.cli import ChannelCli
from psi_agent.channel.feishu import ChannelFeishu
from psi_agent.channel.repl import ChannelRepl
from psi_agent.channel.telegram import ChannelTelegram
from psi_agent.gateway import Gateway
from psi_agent.router import Router
from psi_agent.session import Session
from psi_agent.updater.run import run_self_update

ChannelGroup = Annotated[
    Annotated[ChannelRepl, conf.subcommand(name="repl")]
    | Annotated[ChannelCli, conf.subcommand(name="cli")]
    | Annotated[ChannelTelegram, conf.subcommand(name="telegram")]
    | Annotated[ChannelFeishu, conf.subcommand(name="feishu")],
    conf.subcommand(name="channel", description="User interface channels"),
]


@dataclass
class SelfUpdate:
    """Check and apply incremental updates from the Haitun update server."""

    base_url: str | None = None
    """Override the base URL from haitun-update.conf."""

    install_dir: str | None = None
    """Install directory; defaults to the directory of this executable."""

    check_only: bool = False
    """Only report whether an update is available; do not download."""

    yes: bool = False
    """Apply the update without asking (used by haitun.exe)."""

    async def run(self) -> None:
        result = run_self_update(
            base_url=self.base_url or "",
            install_dir=self.install_dir or "",
            check_only=self.check_only,
            yes=self.yes,
        )
        messages = {
            "up-to-date": ("已是最新版本。", 0),
            "too-old": ("当前版本过旧, 请重新安装完整版本。", 3),
            "already-running": ("已有更新正在进行中。", 0),
            "no-base-url": ("未配置更新服务器地址。", 1),
            "would-update": ("发现新版本, 可以更新。", 2),
            "prepared": ("更新已准备好, 等待确认。", 0),
            "applying": ("更新已开始, 正在切换版本。", 0),
        }
        text, code = messages.get(result, ("更新状态未知。", 1))
        if sys.stdout is not None:
            sys.stdout.write(text + "\n")
        raise SystemExit(code)


Command = Run | Ai | Session | ChannelGroup | Gateway | Router | SelfUpdate


def main() -> None:
    cmd = tyro.cli(Command)
    anyio.run(cmd.run)


if __name__ == "__main__":
    main()

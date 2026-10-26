"""多实例游戏启动控制器：每个实例独立进程、独立日志、独立状态。"""

from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable

import flet as ft

from account_manager import Account, AccountStore, AccountStoreError
from game_launcher import (
    LaunchError,
    build_minecraft_command,
    check_version_files,
    ensure_natives,
    with_server_address,
)
from java_runtime import inspect_java
from launch_settings import JavaValidationError, LaunchSettingsStore, validate_java_17
from log_tags import classify_log
from microsoft_auth import MicrosoftAuthError, refresh_microsoft_login
from version_scanner import LocalVersion


@dataclass(slots=True)
class LogEntry:
    time: str
    level: str
    text: str
    tag: str = "normal"


@dataclass(slots=True)
class GameSession:
    id: str
    version: LocalVersion
    account_id: str
    account_name: str
    account_type: str
    server: tuple[str, int] | None = None
    java_path_override: str | None = None
    java_major_override: int | None = None
    status: str = "starting"
    process: asyncio.subprocess.Process | None = None
    exit_code: int | None = None
    error: str = ""
    stopping: bool = False
    started_at: float = field(default_factory=time.time)
    logs: list[LogEntry] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return {
            "starting": "检查中",
            "running": "运行中",
            "stopping": "停止中",
            "stopped": "已停止",
            "exited": "已退出",
            "failed": "失败",
        }.get(self.status, self.status)

    @property
    def title(self) -> str:
        label = f"{self.version.version_id} · {self.account_name}"
        if self.server:
            label += f" → {self.server[0]}:{self.server[1]}"
        return label

    @property
    def is_ended(self) -> bool:
        """进程已经退出，可以安全移除记录。"""

        return (
            self.process is None
            and self.status in {"exited", "failed", "stopped"}
        )


class GameLauncherController:
    """启动多个 Minecraft 实例，不阻塞 Flet，也不锁定界面。"""

    def __init__(
        self,
        page: ft.Page,
        account_store: AccountStore,
        settings_store: LaunchSettingsStore,
        on_account_changed=None,
    ) -> None:
        self.page = page
        self.account_store = account_store
        self.settings_store = settings_store
        self.on_account_changed = on_account_changed
        self.sessions: list[GameSession] = []
        self._listeners: list[Callable[[str], None]] = []
        self._counter = 0
        self._account_lock = asyncio.Lock()

    def add_listener(self, callback: Callable[[str], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def get_session(self, session_id: str) -> GameSession | None:
        return next((item for item in self.sessions if item.id == session_id), None)

    def start_session(
        self,
        version: LocalVersion,
        account: Account,
        server: tuple[str, int] | None = None,
        java_path: str | None = None,
        java_major: int | None = None,
    ) -> str:
        """立即创建一个会话并异步启动；返回会话 ID，可立即再次启动。"""

        self._counter += 1
        session = GameSession(
            id=f"game-{self._counter}",
            version=version,
            account_id=account.id,
            account_name=account.name,
            account_type=account.type_label,
            server=server,
            java_path_override=java_path,
            java_major_override=java_major,
        )
        self.sessions.append(session)
        self._notify(session.id)
        self.page.run_task(self._run_session, session)
        return session.id

    def stop_session(self, session_id: str) -> None:
        session = self.get_session(session_id)
        if session is None or session.process is None:
            return
        session.stopping = True
        session.status = "stopping"
        self._log(session, "正在停止游戏进程…", "warn")
        self._notify(session.id)
        self.page.run_task(self._stop_session_async, session)

    async def _stop_session_async(self, session: GameSession) -> None:
        process = session.process
        if process is None:
            return
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        except Exception as exc:
            self._log(session, f"停止进程失败：{exc}", "error")

    def clear_logs(self, session_id: str) -> None:
        session = self.get_session(session_id)
        if session is None:
            return
        session.logs.clear()
        self._notify(session.id)

    def remove_session(self, session_id: str) -> bool:
        """移除一条已经结束的实例记录；运行中的实例禁止删除。"""

        session = self.get_session(session_id)
        if session is None or not session.is_ended:
            return False
        self.sessions.remove(session)
        self._notify(session.id)
        return True

    def export_text(self, session_id: str) -> str:
        session = self.get_session(session_id)
        if session is None:
            return ""
        return "\n".join(
            f"{entry.time} {entry.text}" for entry in session.logs
        )

    # ---- 内部启动流程 ----------------------------------------------------
    async def _run_session(self, session: GameSession) -> None:
        version = session.version
        self._log(session, "===== 开始启动 =====", "info")
        self._log(session, f"版本：{version.version_id}", "info")
        if session.server:
            self._log(
                session,
                f"直连目标：{session.server[0]}:{session.server[1]}",
                "info",
            )

        try:
            validation = await asyncio.to_thread(
                check_version_files,
                version,
                version.directory.parent.parent,
            )
            for warning in validation.warnings:
                self._log(session, f"警告：{warning}", "warn")
            self._log(session, "版本文件检查通过。", "success")

            settings = self.settings_store.settings
            if session.java_path_override:
                self._log(
                    session,
                    f"使用实例绑定 Java：{session.java_path_override}",
                    "info",
                )
                java_info = await asyncio.to_thread(
                    inspect_java,
                    session.java_path_override,
                )
                self._log(
                    session,
                    f"实例 Java {java_info.version} 校验通过。",
                    "success",
                )
            else:
                if not settings.java_path:
                    raise LaunchError("未配置 Java 17，请先在「Java 与启动」中选择")
                self._log(session, f"校验 Java：{settings.java_path}", "info")
                java_info = await asyncio.to_thread(
                    validate_java_17,
                    settings.java_path,
                )
                self._log(session, f"Java {java_info.version} 校验通过。", "success")

            if (
                validation.required_java_major is not None
                and validation.required_java_major > java_info.major
            ):
                raise LaunchError(
                    f"版本「{version.version_id}」需要 Java "
                    f"{validation.required_java_major}，但当前配置的是 "
                    f"Java {java_info.version}（主版本 {java_info.major}）。\n"
                    "请安装该版本要求的 Java，或选择兼容 Java 17 的版本。"
                )

            self._log(session, "准备 Windows 本地库…", "info")
            natives = await asyncio.to_thread(
                ensure_natives,
                version,
                version.directory.parent.parent,
            )
            if natives.extracted:
                self._log(
                    session,
                    f"已准备 {natives.extracted} 个本地库文件。",
                    "success",
                )
            for warning in natives.warnings:
                self._log(session, f"警告：{warning}", "warn")

            account, token = await self._prepare_account(session)
            self._log(
                session,
                f"账号：{account.name}（{account.type_label}）",
                "info",
            )

            command = await asyncio.to_thread(
                build_minecraft_command,
                version,
                version.directory.parent.parent,
                account,
                settings,
                java_info.path,
                token,
            )
            if session.server:
                command = with_server_address(
                    command,
                    session.server[0],
                    session.server[1],
                )
            self._log(
                session,
                f"内存 {settings.min_memory_mb}-{settings.max_memory_mb} MB，"
                f"自定义参数：{settings.jvm_args or '无'}",
                "cmd",
            )
            self._log(session, "启动命令已生成（访问令牌不输出到日志）。", "info")

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(version.directory.parent.parent),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=creation_flags,
            )
            session.process = process
            session.status = "running"
            self._log(session, f"游戏进程已启动，PID {process.pid}。", "success")
            self._notify(session.id)
            await self._stream_process(session, process)

        except (
            LaunchError,
            JavaValidationError,
            MicrosoftAuthError,
            AccountStoreError,
        ) as exc:
            self._fail(session, str(exc))
        except Exception as exc:
            self._fail(session, f"启动失败：{exc}")

    async def _prepare_account(self, session: GameSession) -> tuple[Account, str]:
        async with self._account_lock:
            account = await asyncio.to_thread(
                self._find_account,
                session.account_id,
            )
            if account is None:
                raise LaunchError("账号不存在，请重新登录")

            if account.is_microsoft:
                if not account.refresh_token:
                    raise LaunchError("微软账号没有 refresh_token，请重新登录")
                self._log(session, "正在刷新微软登录…", "info")
                data = await asyncio.to_thread(
                    refresh_microsoft_login,
                    account.refresh_token,
                )
                updated = Account(
                    id=data.account_id,
                    account_type="microsoft",
                    name=data.name,
                    uuid=data.account_id,
                    access_token=data.access_token,
                    refresh_token=data.refresh_token,
                    skin_url=data.skin_url,
                    client_id=data.client_id,
                )
                state = await asyncio.to_thread(
                    self.account_store.save_account,
                    updated,
                    activate=True,
                )
                if self.on_account_changed is not None:
                    self.on_account_changed(state)
                return updated, data.access_token

            state = await asyncio.to_thread(
                self.account_store.set_active,
                account.id,
            )
            if self.on_account_changed is not None:
                self.on_account_changed(state)
            return account, "0"

    def _find_account(self, account_id: str) -> Account | None:
        for account in self.account_store.accounts:
            if account.id == account_id:
                return account
        return None

    async def _stream_process(
        self,
        session: GameSession,
        process: asyncio.subprocess.Process,
    ) -> None:
        assert process.stdout is not None
        while True:
            raw = await process.stdout.readline()
            if not raw:
                break
            line = _decode_line(raw).rstrip("\r\n")
            if line:
                self._log(session, line, _level_for(line))

        code = await process.wait()
        session.process = None
        session.exit_code = code
        if session.stopping:
            session.status = "stopped"
            self._log(session, "游戏已停止。", "warn")
        elif code == 0:
            session.status = "exited"
            self._log(session, "游戏进程已退出。", "success")
        else:
            session.status = "failed"
            session.error = f"游戏异常退出，退出代码 {code}"
            self._log(session, session.error, "error")
        self._notify(session.id)

    def _fail(self, session: GameSession, message: str) -> None:
        session.status = "failed"
        session.error = message
        for line in message.splitlines():
            if line.strip():
                self._log(session, f"错误：{line.strip()}", "error")
        self._notify(session.id)

    def _log(self, session: GameSession, text: str, level: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        for line in str(text).splitlines() or [""]:
            session.logs.append(
                LogEntry(stamp, level, line, classify_log(line, level))
            )
        if len(session.logs) > 5000:
            del session.logs[: len(session.logs) - 5000]
        self._notify(session.id)

    def _notify(self, session_id: str) -> None:
        for callback in list(self._listeners):
            try:
                callback(session_id)
            except Exception:
                pass


def _decode_line(raw: bytes) -> str:
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _level_for(line: str) -> str:
    upper = line.upper()
    if "ERROR" in upper or "EXCEPTION" in upper or "CAUSED BY" in upper:
        return "error"
    if "WARN" in upper:
        return "warn"
    return "info"

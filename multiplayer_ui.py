"""局域网联机页面：端口识别、本地地址复制和直连加入房间。"""

from __future__ import annotations

import asyncio
import time

import flet as ft

from account_manager import AccountStore
from launch_controller import GameLauncherController
from launch_settings import LaunchSettingsStore
from multiplayer import (
    MultiplayerError,
    discover_lan_port,
    format_lan_address,
    get_local_ipv4,
    is_tcp_port_open,
    parse_join_address,
)
from ui_theme import (
    AMBER,
    AMBER_BG,
    AMBER_BORDER,
    BG,
    BORDER,
    BORDER_COLOR,
    BUTTON_LABEL_FIELD,
    CARD,
    ERROR,
    FAINT,
    MUTED,
    PADDING,
    PRIMARY,
    PRIMARY_SOFT,
    SURFACE,
    TEXT,
)
from version_scanner import LocalVersion

PAGE_WIDTH = 758
SUCCESS = "#2E7D5B"
CONSOLE_BG = "#101E16"
CONSOLE_TEXT = "#C9D8CF"
TYPE_LABELS = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "旧测试版",
    "old_alpha": "旧预览版",
}


class MultiplayerView:
    """非模态局域网联机页面。"""

    def __init__(
        self,
        page: ft.Page,
        versions: list[LocalVersion],
        height: int | float,
        account_store: AccountStore,
        settings_store: LaunchSettingsStore,
        controller: GameLauncherController,
        on_session_started=None,
    ) -> None:
        self.page = page
        self.versions = list(versions)
        self.height = height
        self.version_by_folder = {item.folder_name: item for item in versions}
        self.account_store = account_store
        self.settings_store = settings_store
        self.controller = controller
        self.on_session_started = on_session_started
        self.mode = "create"
        self.busy = False
        self.lan_address = ""
        self._port_log: list[ft.Text] = []

        self.view = self._build()
        self._set_mode("create")
        self.refresh()

    # ---- 构建 ------------------------------------------------------------
    def _build(self) -> ft.Container:
        header = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            "局域网联机",
                            size=9,
                            color=PRIMARY,
                            weight=ft.FontWeight.W_600,
                            style=ft.TextStyle(letter_spacing=1.2),
                        ),
                        ft.Text(
                            "联机房间",
                            size=26,
                            color=TEXT,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Text(
                            "识别局域网端口，分享地址给同一 WiFi 下的好友。",
                            size=11,
                            color=MUTED,
                        ),
                    ],
                    spacing=1,
                ),
            ],
                    )

        notice = ft.Container(
                        bgcolor=AMBER_BG,
            border=BORDER.all(1, AMBER_BORDER),
            border_radius=10,
            padding=PADDING.symmetric(horizontal=12, vertical=9),
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.WIFI, size=17, color=AMBER),
                    ft.Text(
                        "同一 WiFi 局域网可直接使用本地地址联机；"
                        "跨公网联机需要自行准备 FRP 等穿透工具，启动器不再接管穿透。",
                        size=9,
                        color=AMBER,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        self.create_pill = self._mode_pill("创建房间", ft.Icons.WIFI, "create")
        self.join_pill = self._mode_pill("加入房间", ft.Icons.LOGIN, "join")
        self.body = ft.Container(expand=True)
        content = ft.Container(
                        expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(
                controls=[
                    header,
                    notice,
                    ft.Row(controls=[self.create_pill, self.join_pill], spacing=8),
                    self.body,
                ],
                spacing=10,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

        self.create_view = self._build_create_view()
        self.join_view = self._build_join_view()
        return content

    def _mode_pill(self, label: str, icon, mode: str) -> ft.Container:
        return ft.Container(
            padding=PADDING.symmetric(horizontal=12, vertical=6),
            border_radius=20,
            bgcolor=PRIMARY_SOFT if mode == self.mode else CARD,
            ink=True,
            on_click=lambda _event, target=mode: self._set_mode(target),
            content=ft.Row(
                controls=[
                    ft.Icon(icon, size=15, color=PRIMARY),
                    ft.Text(label, size=10, color=PRIMARY),
                ],
                spacing=5,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _set_mode(self, mode: str) -> None:
        if mode not in ("create", "join"):
            return
        self.mode = mode
        self.create_pill.bgcolor = PRIMARY_SOFT if mode == "create" else CARD
        self.join_pill.bgcolor = PRIMARY_SOFT if mode == "join" else CARD
        self.body.content = self.create_view if mode == "create" else self.join_view
        try:
            self.page.update()
        except Exception:
            pass

    # ---- 创建房间 --------------------------------------------------------
    def _build_create_view(self) -> ft.Container:
        self.port_field = ft.TextField(
            label="端口（可选）",
            width=190,
            height=42,
            dense=True,
            filled=True,
            bgcolor=CARD,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            hint_text="留空自动识别",
            text_size=10,
        )
        self.detect_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "识别局域网端口"},
            icon=ft.Icons.SEARCH,
            width=190,
            height=42,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            on_click=self._detect_port,
        )
        self.detect_spinner = ft.ProgressRing(
            width=16,
            height=16,
            stroke_width=2.2,
            color=PRIMARY,
            visible=False,
        )
        self.address_text = ft.Text(
            "尚未识别",
            size=20,
            color=MUTED,
            selectable=True,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            width=620,
        )
        self.copy_button = ft.FilledTonalButton(
            **{BUTTON_LABEL_FIELD: "复制局域网地址"},
            icon=ft.Icons.CONTENT_COPY,
            disabled=True,
            on_click=self._copy_address,
        )
        self.create_status = ft.Text("等待识别端口", size=10, color=MUTED)
        self.log_list = ft.ListView(
            expand=True,
            spacing=0,
            padding=0,
        )
        self.log_box = ft.Container(
            expand=True,
            bgcolor=CONSOLE_BG,
            border_radius=9,
            padding=PADDING.symmetric(horizontal=10, vertical=8),
            content=self.log_list,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        "1. 进入单人存档，按 Esc → “对局域网开放”。\n"
                        "2. 回到这里点击识别端口；识别成功后把地址发给同一 WiFi 下的好友。",
                        size=10,
                        color=MUTED,
                    ),
                    ft.Row(
                        controls=[
                            self.port_field,
                            self.detect_button,
                            self.detect_spinner,
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text("局域网地址", size=9, color=FAINT),
                    ft.Container(
                                                bgcolor=SURFACE,
                        border=BORDER.all(1, BORDER_COLOR),
                        border_radius=9,
                        padding=PADDING.symmetric(horizontal=14, vertical=10),
                        content=self.address_text,
                    ),
                    ft.Row(
                        controls=[self.copy_button, self.create_status],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.log_box,
                ],
                spacing=9,
                expand=True,
            )
        )

    def _append_port_log(self, text: str, level: str = "info") -> None:
        color = {
            "error": "#FF9B8A",
            "warn": "#F2C96D",
            "success": "#8DD8AC",
        }.get(level, CONSOLE_TEXT)
        control = ft.Text(
            f"{time.strftime('%H:%M:%S')}  {text}",
            size=9,
            font_family="Consolas",
            color=color,
            no_wrap=True,
        )
        self._port_log.append(control)
        self.log_list.controls.append(control)
        if len(self.log_list.controls) > 300:
            del self.log_list.controls[0]
        try:
            self.page.update()
        except Exception:
            pass

    def _detect_port(self, _event=None) -> None:
        if self.busy:
            return
        self.busy = True
        self.detect_button.disabled = True
        self.detect_spinner.visible = True
        self.copy_button.disabled = True
        self.address_text.value = "正在识别…"
        self.address_text.color = MUTED
        self.create_status.value = "正在监听 Minecraft 局域网广播…"
        self.create_status.color = MUTED
        self.log_list.controls.clear()
        self._append_port_log("开始识别局域网端口。", "info")
        self.page.update()
        self.page.run_task(self._detect_port_async)

    async def _detect_port_async(self) -> None:
        try:
            manual = (self.port_field.value or "").strip()
            if manual:
                try:
                    port = int(manual)
                except ValueError as exc:
                    raise MultiplayerError("手动端口必须是数字") from exc
                if not 1 <= port <= 65535:
                    raise MultiplayerError("手动端口必须在 1-65535 之间")
                self._append_port_log(f"使用手动端口 {port}。", "info")
                if not await asyncio.to_thread(is_tcp_port_open, port):
                    raise MultiplayerError(
                        f"端口 {port} 没有程序监听，请确认游戏内已开启局域网"
                    )
            else:
                self._append_port_log(
                    "监听 224.0.2.60:4445，请现在在游戏内开启局域网…",
                    "info",
                )
                port = await asyncio.to_thread(discover_lan_port, 25)
                self._append_port_log(f"检测到局域网端口 {port}。", "success")

            host = await asyncio.to_thread(get_local_ipv4)
            if not host:
                host = "127.0.0.1"
                self._append_port_log(
                    "未获取到局域网 IPv4，已回退到 127.0.0.1；请用 ipconfig 查看本机地址。",
                    "warn",
                )
            self.lan_address = format_lan_address(host, port)
            self.address_text.value = self.lan_address
            self.address_text.color = PRIMARY
            self.copy_button.disabled = False
            self.create_status.value = "识别成功，可复制给同一 WiFi 下的好友"
            self.create_status.color = SUCCESS
            self._append_port_log(f"局域网地址：{self.lan_address}", "success")
            self.port_field.disabled = False
        except Exception as exc:
            self.lan_address = ""
            self.address_text.value = "尚未识别"
            self.address_text.color = MUTED
            self.create_status.value = "端口识别失败"
            self.create_status.color = ERROR
            self._append_port_log(str(exc), "error")
        finally:
            self.busy = False
            self.detect_button.disabled = False
            self.detect_spinner.visible = False
            self.page.update()

    def _copy_address(self, _event=None) -> None:
        if not self.lan_address:
            return
        try:
            self.page.set_clipboard(self.lan_address)
            self.create_status.value = "局域网地址已复制"
            self.create_status.color = SUCCESS
        except Exception as exc:
            self.create_status.value = f"复制失败：{exc}"
            self.create_status.color = ERROR
        self.page.update()

    # ---- 加入房间 --------------------------------------------------------
    def _build_join_view(self) -> ft.Container:
        self.join_address_field = ft.TextField(
                        height=42,
            dense=True,
            filled=True,
            bgcolor=CARD,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            hint_text="输入好友的局域网地址，例如 192.168.1.10:54321",
            text_size=10,
        )
        self.version_dropdown = ft.Dropdown(
            label="游戏版本",
            width=260,
            dense=True,
            text_size=10,
            options=[],
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=4),
        )
        self.account_dropdown = ft.Dropdown(
            label="账号",
            width=220,
            dense=True,
            text_size=10,
            options=[],
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=4),
        )
        self.join_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "一键连接"},
            icon=ft.Icons.LOGIN,
            width=130,
            height=42,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            on_click=self._join,
        )
        self.join_status = ft.Text("输入地址后启动游戏并直连", size=10, color=MUTED)
        self.join_detail = ft.Text(
            "使用当前 Java 17、内存和 JVM 参数启动一个新的游戏实例。",
            size=9,
            color=FAINT,
                    )
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        "输入同一 WiFi 好友提供的地址，选择版本和账号后一键启动直连。",
                        size=10,
                        color=MUTED,
                    ),
                    ft.Text("好友局域网地址", size=9, color=FAINT),
                    self.join_address_field,
                    ft.Row(
                        controls=[
                            self.version_dropdown,
                            self.account_dropdown,
                            self.join_button,
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.join_status,
                    self.join_detail,
                    ft.Container(
                        expand=True,
                        bgcolor=CARD,
                        border=BORDER.all(1, BORDER_COLOR),
                        border_radius=10,
                        padding=PADDING.symmetric(horizontal=14, vertical=12),
                        content=ft.Column(
                            controls=[
                                ft.Text("直连前检查", size=11, color=TEXT, weight=ft.FontWeight.W_600),
                                ft.Text(
                                    "• 好友已在单人存档中点击“对局域网开放”\n"
                                    "• 两台电脑处于同一 WiFi 或同一局域网\n"
                                    "• 版本与模组尽量保持一致，避免连接后被踢出\n"
                                    "• 跨公网联机需要自行准备 FRP 等穿透工具",
                                    size=10,
                                    color=MUTED,
                                ),
                            ],
                            spacing=8,
                        ),
                    ),
                ],
                spacing=9,
                expand=True,
            )
        )

    def _join(self, _event=None) -> None:
        try:
            host, port = parse_join_address(self.join_address_field.value or "")
        except MultiplayerError as exc:
            self.join_status.value = str(exc)
            self.join_status.color = ERROR
            self.page.update()
            return

        version = self.version_by_folder.get(self.version_dropdown.value or "")
        account = next(
            (
                item
                for item in self.account_store.accounts
                if item.id == self.account_dropdown.value
            ),
            None,
        )
        if version is None:
            self.join_status.value = "请选择游戏版本"
            self.join_status.color = ERROR
            self.page.update()
            return
        if account is None:
            self.join_status.value = "请先登录账号"
            self.join_status.color = ERROR
            self.page.update()
            return

        session_id = self.controller.start_session(
            version,
            account,
            server=(host, port),
        )
        self.join_status.value = f"已创建实例，正在连接 {host}:{port}"
        self.join_status.color = SUCCESS
        self.join_detail.value = "可以在「启动与日志」页面查看该实例的启动日志。"
        self.page.update()
        if self.on_session_started is not None:
            self.on_session_started(session_id)

    # ---- 刷新 ------------------------------------------------------------
    def refresh(self) -> None:
        version_value = self.version_dropdown.value
        self.version_dropdown.options = [
            ft.dropdown.Option(
                key=version.folder_name,
                text=f"{version.version_id} · {TYPE_LABELS.get(version.version_type, version.version_type)}",
            )
            for version in self.versions
        ]
        if version_value not in self.version_by_folder:
            version_value = self.versions[0].folder_name if self.versions else None
        self.version_dropdown.value = version_value
        self.version_dropdown.disabled = not self.versions

        accounts = self.account_store.accounts
        active = self.account_store.active_account
        account_value = self.account_dropdown.value
        valid_ids = {account.id for account in accounts}
        self.account_dropdown.options = [
            ft.dropdown.Option(
                key=account.id,
                text=f"{account.name} · {account.type_label}",
            )
            for account in accounts
        ]
        if account_value not in valid_ids:
            account_value = active.id if active is not None else (accounts[0].id if accounts else None)
        self.account_dropdown.value = account_value
        self.account_dropdown.disabled = not accounts
        self.join_button.disabled = not self.versions or not accounts
        try:
            self.page.update()
        except Exception:
            pass

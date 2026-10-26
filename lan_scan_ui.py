"""局域网房间扫描页面：发现、收藏、加入和联机二维码。"""

from __future__ import annotations

import asyncio

import flet as ft

from account_manager import AccountStore
from java_bindings import JavaBindingStore
from java_runtime import read_local_version_java
from launch_controller import GameLauncherController
from launch_settings import LaunchSettingsStore
from lan_scan import (
    LanFavorites,
    LanRoom,
    qr_png_base64,
    scan_lan_rooms,
)
from ui_theme import (
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
    TEXT_BUTTON_LABEL_FIELD,
)
from version_scanner import LocalVersion

PAGE_WIDTH = 758
TYPE_LABELS = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "旧测试版",
    "old_alpha": "旧预览版",
}


class LanScanView:
    def __init__(
        self,
        page: ft.Page,
        versions: list[LocalVersion],
        height: int | float,
        account_store: AccountStore,
        settings_store: LaunchSettingsStore,
        controller: GameLauncherController,
        on_session_started=None,
        favorites: LanFavorites | None = None,
    ) -> None:
        self.page = page
        self.versions = list(versions)
        self.height = height
        self.account_store = account_store
        self.settings_store = settings_store
        self.controller = controller
        self.on_session_started = on_session_started
        self.favorites = favorites or LanFavorites()
        self.version_by_folder = {item.folder_name: item for item in versions}
        self.rooms: list[LanRoom] = []
        self.mode = "discover"
        self.scanning = False

        self.view = self._build()
        self.refresh()

    def _build(self) -> ft.Container:
        header = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            "局域网扫描",
                            size=9,
                            color=PRIMARY,
                            weight=ft.FontWeight.W_600,
                            style=ft.TextStyle(letter_spacing=1.2),
                        ),
                        ft.Text(
                            "发现房间",
                            size=26,
                            color=TEXT,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Text(
                            "监听 Minecraft 局域网广播，读取房间名、版本和在线玩家。",
                            size=11,
                            color=MUTED,
                        ),
                    ],
                    spacing=1,
                ),
                ft.FilledButton(
                    **{BUTTON_LABEL_FIELD: "扫描局域网"},
                    icon=ft.Icons.RADAR,
                    width=150,
                    height=40,
                    bgcolor=PRIMARY,
                    color="#FFFFFF",
                    on_click=self._start_scan,
                ),
            ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.scan_status = ft.Text(
            "点击扫描后，在游戏内对局域网开放；广播只发送一次，建议先扫描再开放。",
            size=9,
            color=MUTED,
        )

        self.version_dropdown = ft.Dropdown(
            label="加入使用版本",
            width=250,
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
            width=210,
            dense=True,
            text_size=10,
            options=[],
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=4),
        )
        self.scan_spinner = ft.ProgressRing(
            width=16,
            height=16,
            stroke_width=2.2,
            color=PRIMARY,
            visible=False,
        )
        self.discover_pill = self._mode_pill("发现房间", ft.Icons.WIFI, "discover")
        self.favorite_pill = self._mode_pill("收藏房间", ft.Icons.STAR_OUTLINE, "favorite")
        filters = ft.Row(
            controls=[
                self.version_dropdown,
                self.account_dropdown,
                self.scan_spinner,
                ft.Container(expand=True),
                self.discover_pill,
                self.favorite_pill,
            ],
            spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.room_list = ft.ListView(expand=True, spacing=8, padding=0)
        self.list_card = ft.Container(
                        bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=12,
            padding=PADDING.symmetric(horizontal=12, vertical=10),
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text("房间列表", size=9, color=FAINT),
                    self.room_list,
                ],
                spacing=6,
                expand=True,
            ),
        )
        self.footer_status = ft.Text("", size=9, color=FAINT)
        return ft.Container(
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(
                controls=[
                    header,
                    self.scan_status,
                    filters,
                    self.list_card,
                    self.footer_status,
                ],
                spacing=9,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    def _mode_pill(self, label, icon, mode):
        return ft.Container(
            padding=PADDING.symmetric(horizontal=12, vertical=6),
            border_radius=18,
            bgcolor=PRIMARY_SOFT if mode == self.mode else CARD,
            ink=True,
            on_click=lambda _e, value=mode: self._set_mode(value),
            content=ft.Row(
                controls=[
                    ft.Icon(icon, size=14, color=PRIMARY),
                    ft.Text(label, size=10, color=PRIMARY),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _set_mode(self, mode: str) -> None:
        if self.scanning:
            return
        self.mode = mode
        self.discover_pill.bgcolor = PRIMARY_SOFT if mode == "discover" else CARD
        self.favorite_pill.bgcolor = PRIMARY_SOFT if mode == "favorite" else CARD
        self._render_rooms()
        self.page.update()

    def set_versions(self, versions: list[LocalVersion]) -> None:
        self.versions = list(versions)
        self.version_by_folder = {item.folder_name: item for item in versions}
        self.refresh()

    def refresh(self) -> None:
        value = self.version_dropdown.value
        self.version_dropdown.options = [
            ft.dropdown.Option(
                key=version.folder_name,
                text=f"{version.version_id} · {TYPE_LABELS.get(version.version_type, version.version_type)}",
            )
            for version in self.versions
        ]
        valid = set(self.version_by_folder)
        if value not in valid:
            value = self.versions[0].folder_name if self.versions else None
        self.version_dropdown.value = value
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
        self._render_rooms()
        self.page.update()

    def _start_scan(self, _event=None) -> None:
        if self.scanning:
            return
        self.scanning = True
        self.scan_status.value = "正在监听局域网广播（约 8 秒）…"
        self.scan_status.color = PRIMARY
        self.scan_spinner.visible = True
        self.page.update()
        self.page.run_task(self._scan_async)

    async def _scan_async(self) -> None:
        try:
            rooms = await asyncio.to_thread(scan_lan_rooms, 8.0)
            self.rooms = rooms
            if rooms:
                self.scan_status.value = f"发现 {len(rooms)} 个房间"
                self.scan_status.color = PRIMARY
            else:
                self.scan_status.value = (
                    "没有发现广播。请先在游戏内对局域网开放；广播只发送一次，"
                    "可以先点扫描，再切回游戏开放。"
                )
                self.scan_status.color = MUTED
            self._render_rooms()
        except Exception as exc:
            self.scan_status.value = f"扫描失败：{exc}"
            self.scan_status.color = ERROR
        finally:
            self.scanning = False
            self.scan_spinner.visible = False
            self.page.update()

    def _render_rooms(self) -> None:
        self.room_list.controls.clear()
        rooms = list(self.rooms) if self.mode == "discover" else self.favorites.rooms()
        if not rooms:
            message = (
                "还没有发现房间，点击「扫描局域网」开始。"
                if self.mode == "discover"
                else "还没有收藏房间。发现房间后点击星标收藏。"
            )
            self.room_list.controls.append(
                ft.Container(
                    padding=PADDING.symmetric(vertical=30),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text(message, size=10, color=FAINT),
                )
            )
            return
        for room in rooms:
            self.room_list.controls.append(self._room_card(room))

    def _room_card(self, room: LanRoom) -> ft.Container:
        favorite = self.favorites.contains(room.endpoint)
        return ft.Container(
                        bgcolor=SURFACE,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=10,
            padding=PADDING.symmetric(horizontal=11, vertical=9),
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=34,
                        height=34,
                        border_radius=9,
                        bgcolor=PRIMARY_SOFT,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(ft.Icons.DNS_OUTLINED, size=17, color=PRIMARY),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                room.motd or "Minecraft 房间",
                                size=11,
                                color=TEXT,
                                weight=ft.FontWeight.W_600,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=350,
                            ),
                            ft.Text(
                                f"{room.endpoint} · {room.version} · {room.players_text}",
                                size=9,
                                color=MUTED,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=350,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.STAR if favorite else ft.Icons.STAR_OUTLINE,
                        icon_size=17,
                        icon_color="#D99A2B" if favorite else FAINT,
                        tooltip="取消收藏" if favorite else "收藏房间",
                        on_click=lambda _e, item=room: self._toggle_favorite(item),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.QR_CODE_2,
                        icon_size=17,
                        icon_color=PRIMARY,
                        tooltip="联机二维码",
                        on_click=lambda _e, item=room: self._show_qr(item),
                    ),
                    ft.TextButton(
                        **{TEXT_BUTTON_LABEL_FIELD: "加入"},
                        icon=ft.Icons.LOGIN,
                        on_click=lambda _e, item=room: self._join(item),
                    ),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _toggle_favorite(self, room: LanRoom) -> None:
        added = self.favorites.toggle(room)
        self.footer_status.value = "已收藏该房间" if added else "已取消收藏"
        self.footer_status.color = PRIMARY if added else MUTED
        self._render_rooms()
        self.page.update()

    def _show_qr(self, room: LanRoom) -> None:
        try:
            image = qr_png_base64(room.endpoint, scale=5)
        except Exception as exc:
            self.footer_status.value = f"二维码生成失败：{exc}"
            self.footer_status.color = ERROR
            self.page.update()
            return
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("联机分享二维码", size=16, color=TEXT),
            content=ft.Container(
                width=240,
                height=190,
                content=ft.Column(
                    controls=[
                        ft.Image(src_base64=image, width=120, height=120),
                        ft.Text(room.endpoint, size=11, color=TEXT, selectable=True),
                        ft.Text("扫码即可复制房间地址", size=8, color=MUTED),
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
            actions=[
                ft.TextButton(
                    **{TEXT_BUTTON_LABEL_FIELD: "复制地址"},
                    on_click=lambda _e: self._copy(room.endpoint),
                ),
                ft.TextButton(
                    **{TEXT_BUTTON_LABEL_FIELD: "关闭"},
                    on_click=lambda _e: self.page.close(dialog),
                ),
            ],
            actions_padding=PADDING.symmetric(horizontal=16, vertical=8),
        )
        self.page.open(dialog)
        self.page.update()

    def _copy(self, text: str) -> None:
        self.page.set_clipboard(text)
        self.footer_status.value = "已复制房间地址"
        self.footer_status.color = PRIMARY
        self.page.update()

    def _join(self, room: LanRoom) -> None:
        version = next(
            (
                item
                for item in self.versions
                if item.version_id == room.version
                or item.folder_name == room.version
            ),
            None,
        )
        if version is None:
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
            self.footer_status.value = "请选择加入使用的本地版本"
            self.footer_status.color = ERROR
            self.page.update()
            return
        if account is None:
            self.footer_status.value = "请先登录账号"
            self.footer_status.color = ERROR
            self.page.update()
            return
        binding = JavaBindingStore().get(version.folder_name)
        requirement = read_local_version_java(version)
        global_major = self.settings_store.settings.java_major or 0
        effective_major = binding["major"] if binding else global_major
        if effective_major < requirement.major:
            self.footer_status.value = (
                f"该版本需要 Java {requirement.major}。请先在「启动与日志」"
                "选择此版本并点击一键修复，再回来加入。"
            )
            self.footer_status.color = ERROR
            self.page.update()
            return
        session_id = self.controller.start_session(
            version,
            account,
            server=(room.address, room.port),
            java_path=binding["path"] if binding else None,
            java_major=binding["major"] if binding else None,
        )
        self.footer_status.value = f"已创建实例，直连 {room.endpoint}"
        self.footer_status.color = PRIMARY
        self.page.update()
        if self.on_session_started is not None:
            self.on_session_started(session_id)

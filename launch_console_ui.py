"""非模态启动控制台：多实例选择、独立日志、导出和停止。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import flet as ft

from account_manager import AccountStore
from java_bindings import JavaBindingStore
from java_runtime import (
    JavaRecommendation,
    install_java_runtime,
    inspect_java,
    read_local_version_java,
    runtime_executable,
)
from launch_controller import GameLauncherController, GameSession
from launch_settings import LaunchSettingsStore
from log_tags import TAG_JAVA, TAG_MOD_CONFLICT, TAG_NORMAL, TAG_RESOURCE, tag_color, tag_label
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
    TEXT_BUTTON_LABEL_FIELD,
)
from version_scanner import LocalVersion

PAGE_WIDTH = 758
CONSOLE_BG = "#101E16"
CONSOLE_TEXT = "#C9D8CF"
SUCCESS = "#2E7D5B"
WARN = "#F2C96D"
TYPE_LABELS = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "旧测试版",
    "old_alpha": "旧预览版",
}


class LaunchConsoleView:
    """启动与日志页面。它不是弹窗，游戏运行期间仍可切换侧栏。"""

    def __init__(
        self,
        page: ft.Page,
        versions: list[LocalVersion],
        height: int | float,
        account_store: AccountStore,
        settings_store: LaunchSettingsStore,
        controller: GameLauncherController,
        binding_store: JavaBindingStore | None = None,
        app_settings_store=None,
    ) -> None:
        self.page = page
        self.versions = list(versions)
        self.height = height
        self.account_store = account_store
        self.settings_store = settings_store
        self.controller = controller
        self.binding_store = binding_store or JavaBindingStore()
        self.app_settings_store = app_settings_store
        self.version_by_folder = {item.folder_name: item for item in versions}
        self.selected_session_id: str | None = None
        self._log_cursor = 0
        self._last_update = 0.0
        self.java_requirement: JavaRecommendation | None = None
        self._java_dialog: ft.AlertDialog | None = None
        self._repairing = False

        self.controller.add_listener(self._on_controller_update)
        self.view = self._build()
        self.refresh()

    # ---- 页面构建 --------------------------------------------------------
    def _build(self) -> ft.Container:
        self.summary_text = ft.Text("0 个实例", size=10, color=FAINT)
        header = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            "启动与日志",
                            size=9,
                            color=PRIMARY,
                            weight=ft.FontWeight.W_600,
                            style=ft.TextStyle(letter_spacing=1.2),
                        ),
                        ft.Text(
                            "游戏实例",
                            size=26,
                            color=TEXT,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Text(
                            "多个实例独立运行；运行中仍可切换侧栏和联机页面。",
                            size=11,
                            color=MUTED,
                        ),
                    ],
                    spacing=1,
                ),
                self.summary_text,
            ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.version_dropdown = ft.Dropdown(
            label="游戏版本",
            width=250,
            dense=True,
            text_size=10,
            options=[],
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=4),
            on_change=self._on_version_changed,
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
        self.launch_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "启动新实例"},
            icon=ft.Icons.ADD,
            width=150,
            height=42,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            on_click=self._start_new_instance,
        )
        settings = self.settings_store.settings
        self.settings_summary = ft.Text(
            f"Java {settings.java_version or '未配置'} · "
            f"内存 {settings.min_memory_mb}-{settings.max_memory_mb} MB",
            size=9,
            color=FAINT,
                    )
        self.java_check_text = ft.Text("", size=9, color=AMBER)
        self.java_check_detail = ft.Text("", size=8, color=MUTED)
        self.java_repair_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "一键修复"},
            icon=ft.Icons.BUILD_CIRCLE_OUTLINED,
            icon_color=AMBER,
            style=ft.ButtonStyle(color=AMBER),
            on_click=self._open_java_repair,
        )
        self.java_check_box = ft.Container(
                        bgcolor=AMBER_BG,
            border=BORDER.all(1, AMBER_BORDER),
            border_radius=8,
            padding=PADDING.symmetric(horizontal=10, vertical=7),
            visible=False,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=16, color=AMBER),
                    ft.Column(
                        controls=[self.java_check_text, self.java_check_detail],
                        spacing=1,
                        expand=True,
                    ),
                    self.java_repair_button,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        setup_card = ft.Container(
                        bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=12,
            padding=PADDING.symmetric(horizontal=14, vertical=10),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            self.version_dropdown,
                            self.account_dropdown,
                            self.launch_button,
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.settings_summary,
                    self.java_check_box,
                ],
                spacing=6,
            ),
        )

        self.sessions_row = ft.Row(
            controls=[],
            spacing=8,
            run_spacing=8,
            wrap=True,
        )
        self.sessions_panel = ft.Container(
                        bgcolor=SURFACE,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=12,
            padding=PADDING.symmetric(horizontal=12, vertical=10),
            content=ft.Column(
                controls=[
                    ft.Text("运行实例", size=9, color=FAINT),
                    self.sessions_row,
                ],
                spacing=6,
            ),
        )

        self.session_title = ft.Text("未选择实例", size=11, color=TEXT)
        self.session_status = ft.Text("", size=9, color=MUTED)
        self.log_filter = ft.Dropdown(
            width=118,
            dense=True,
            text_size=9,
            value="all",
            options=[
                ft.dropdown.Option("all", "全部日志"),
                ft.dropdown.Option(TAG_MOD_CONFLICT, "模组冲突"),
                ft.dropdown.Option(TAG_JAVA, "Java不兼容"),
                ft.dropdown.Option(TAG_RESOURCE, "资源失败"),
                ft.dropdown.Option(TAG_NORMAL, "正常信息"),
            ],
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=8, vertical=4),
            on_change=self._on_log_filter_change,
        )
        self.stop_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "停止"},
            icon=ft.Icons.STOP_CIRCLE_OUTLINED,
            icon_color=ERROR,
            style=ft.ButtonStyle(color=ERROR),
            visible=False,
            disabled=True,
            on_click=self._stop_selected,
        )
        self.remove_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "移除记录"},
            icon=ft.Icons.DELETE_OUTLINE,
            icon_color=MUTED,
            style=ft.ButtonStyle(color=MUTED),
            visible=False,
            on_click=self._remove_selected,
        )
        self.export_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "导出日志"},
            icon=ft.Icons.DOWNLOAD_OUTLINED,
            disabled=True,
            on_click=self._export_logs,
        )
        self.clear_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "清空日志"},
            icon=ft.Icons.DELETE_SWEEP_OUTLINED,
            disabled=True,
            on_click=self._clear_logs,
        )
        self.log_list = ft.ListView(
            expand=True,
            spacing=0,
            padding=PADDING.symmetric(horizontal=8, vertical=6),
            auto_scroll=True,
        )
        self.log_box = ft.Container(
                        bgcolor=CONSOLE_BG,
            border_radius=10,
            expand=True,
            content=self.log_list,
        )
        self.footer_status = ft.Text("选择一个实例查看日志", size=9, color=FAINT)
        log_panel = ft.Container(
                        bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=12,
            padding=PADDING.symmetric(horizontal=12, vertical=10),
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Column(
                                controls=[self.session_title, self.session_status],
                                spacing=0,
                            ),
                            ft.Row(
                                controls=[
                                    self.log_filter,
                                    self.stop_button,
                                    self.remove_button,
                                    self.export_button,
                                    self.clear_button,
                                ],
                                spacing=4,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.log_box,
                    self.footer_status,
                ],
                spacing=6,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

        return ft.Container(
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(
                controls=[
                    header,
                    setup_card,
                    self.sessions_panel,
                    log_panel,
                ],
                spacing=10,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    # ---- 刷新/选择 -------------------------------------------------------
    def refresh(self) -> None:
        self._refresh_options()
        self._refresh_sessions()
        if self.selected_session_id is None and self.controller.sessions:
            self.selected_session_id = self.controller.sessions[-1].id
        self._select_session_visual(self.selected_session_id)
        self._refresh_java_check()
        self.page.update()

    def _refresh_options(self) -> None:
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
        account_value = self.account_dropdown.value
        active = self.account_store.active_account
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
        self.launch_button.disabled = not self.versions or not accounts

        settings = self.settings_store.settings
        self.settings_summary.value = (
            f"Java {settings.java_version or '未配置'} · "
            f"内存 {settings.min_memory_mb}-{settings.max_memory_mb} MB"
        )
        self._refresh_java_check()

    def _selected_version(self) -> LocalVersion | None:
        return self.version_by_folder.get(self.version_dropdown.value or "")

    def _current_java(self, folder_name: str) -> tuple[str, int, str]:
        """返回当前实例实际会使用的 Java：绑定优先，其次全局设置。"""

        binding = self.binding_store.get(folder_name)
        if binding is not None:
            return binding["path"], binding["major"], "实例绑定"
        settings = self.settings_store.settings
        return settings.java_path or "", settings.java_major or 0, "全局设置"

    def _refresh_java_check(self) -> None:
        version = self._selected_version()
        if version is None:
            self.java_check_box.visible = False
            return
        requirement = read_local_version_java(version)
        self.java_requirement = requirement
        java_path, major, source = self._current_java(version.folder_name)
        compatible = bool(java_path) and major >= requirement.major
        if compatible:
            self.java_check_box.visible = False
            return

        current = f"Java {major}" if major else "未配置 Java"
        self.java_check_text.value = (
            f"版本「{version.version_id}」需要 Java {requirement.major}，"
            f"当前{source}为 {current}"
        )
        self.java_check_detail.value = (
            f"一键修复会下载 Mojang {requirement.component}，"
            "并只绑定到该版本，不修改全局 Java 设置。"
        )
        self.java_check_box.visible = True
        self.java_repair_button.disabled = self._repairing

    def _on_version_changed(self, _event=None) -> None:
        self._refresh_java_check()
        self.page.update()

    def _open_java_repair(self, _event=None, *, start_after: bool = False) -> None:
        version = self._selected_version()
        if version is None or self.java_requirement is None:
            return
        if self._java_dialog is not None:
            return
        requirement = self.java_requirement
        settings = self.settings_store.settings
        current_major = settings.java_major or 0
        binding = self.binding_store.get(version.folder_name)
        if binding is not None:
            current_major = binding["major"]

        status = ft.Text("", size=9, color=MUTED)
        spinner = ft.ProgressRing(
            width=18,
            height=18,
            stroke_width=2.2,
            color=PRIMARY,
            visible=False,
        )
        repair_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: f"下载并绑定 Java {requirement.major}"},
            icon=ft.Icons.COFFEE,
            bgcolor=PRIMARY,
            color="#FFFFFF",
        )
        cancel_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "取消"},
            on_click=lambda _e: self._close_java_dialog(),
        )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Java 版本不兼容", size=16, color=TEXT),
            content=ft.Container(
                width=440,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            f"版本「{version.version_id}」需要 Java "
                            f"{requirement.major}（{requirement.component}），"
                            f"当前为 Java {current_major or '未配置'}。",
                            size=11,
                            color=TEXT,
                        ),
                        ft.Text(
                            "一键修复会从 Mojang 下载对应 Java 运行时，"
                            "并只绑定到该 Minecraft 版本；其他版本和全局设置不受影响。",
                            size=9,
                            color=MUTED,
                        ),
                        ft.Row(
                            controls=[spinner, status],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    spacing=8,
                    tight=True,
                ),
            ),
            actions=[cancel_button, repair_button],
            actions_padding=PADDING.symmetric(horizontal=18, vertical=10),
        )
        self._java_dialog = dialog
        self._repair_spinner = spinner
        self._repair_status = status
        self._repair_button = repair_button
        self._repair_cancel = cancel_button
        self._repairing = False

        def start_repair(_event=None):
            if self._repairing:
                return
            self._repairing = True
            repair_button.disabled = True
            cancel_button.disabled = True
            spinner.visible = True
            status.value = f"正在下载 {requirement.component}…"
            status.color = MUTED
            self.page.update()
            self.page.run_task(
                self._repair_java_worker,
                version,
                requirement,
                dialog,
                status,
                spinner,
                repair_button,
                cancel_button,
                start_after,
            )

        repair_button.on_click = start_repair
        self.page.open(dialog)
        self.page.update()

    def _close_java_dialog(self) -> None:
        dialog = self._java_dialog
        self._java_dialog = None
        if dialog is not None and dialog.open:
            self.page.close(dialog)
            self.page.update()

    async def _repair_java_worker(
        self,
        version,
        requirement,
        dialog,
        status,
        spinner,
        repair_button,
        cancel_button,
        start_after: bool,
    ) -> None:
        root = version.directory.parent.parent
        try:
            executable = await asyncio.to_thread(
                runtime_executable,
                requirement.component,
                root,
            )
            if not executable:
                status.value = f"正在下载 Java {requirement.major}…"
                self.page.update()
                await asyncio.to_thread(
                    install_java_runtime,
                    requirement.component,
                    root,
                )
                executable = await asyncio.to_thread(
                    runtime_executable,
                    requirement.component,
                    root,
                )
            if not executable:
                raise RuntimeError("Java 下载完成但未找到 java.exe")

            java_info = await asyncio.to_thread(inspect_java, executable)
            if java_info.major < requirement.major:
                raise RuntimeError(
                    f"下载的 Java 主版本为 {java_info.major}，"
                    f"低于版本要求的 {requirement.major}"
                )
            self.binding_store.set(
                version.folder_name,
                java_info.path,
                java_info.major,
                requirement.component,
            )
            status.value = (
                f"已绑定 Java {java_info.major}（{java_info.version}）到该版本"
            )
            status.color = PRIMARY
            self._repairing = False
            self._refresh_java_check()
            self._close_java_dialog()
            self.page.update()
            if start_after:
                self._start_new_instance()
        except Exception as exc:
            status.value = f"修复失败：{exc}"
            status.color = ERROR
            spinner.visible = False
            repair_button.disabled = False
            cancel_button.disabled = False
            self._repairing = False
            self.page.update()

    def _refresh_sessions(self) -> None:
        self.sessions_row.controls.clear()
        if not self.controller.sessions:
            self.sessions_row.controls.append(
                ft.Text("还没有启动实例", size=10, color=FAINT)
            )
        else:
            for session in self.controller.sessions:
                self.sessions_row.controls.append(self._session_chip(session))
        self.summary_text.value = f"{len(self.controller.sessions)} 个实例"

    def _session_chip(self, session: GameSession) -> ft.Container:
        selected = session.id == self.selected_session_id
        color = _status_color(session.status)
        return ft.Container(
            width=230,
            padding=PADDING.symmetric(horizontal=9, vertical=7),
            bgcolor=PRIMARY_SOFT if selected else CARD,
            border=BORDER.all(1, PRIMARY if selected else BORDER_COLOR),
            border_radius=8,
            ink=True,
            on_click=lambda _event, session_id=session.id: self.select_session(session_id),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(width=5, height=5, border_radius=3, bgcolor=color),
                            ft.Text(
                                session.version.version_id,
                                size=10,
                                color=TEXT,
                                weight=ft.FontWeight.W_600,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=150,
                            ),
                            ft.Container(expand=True),
                            *(
                                [
                                    ft.IconButton(
                                        icon=ft.Icons.CLOSE,
                                        icon_size=13,
                                        icon_color=FAINT,
                                        width=22,
                                        height=22,
                                        tooltip="移除这条已结束的实例记录",
                                        on_click=lambda _event, session_id=session.id: self._remove_session(session_id),
                                    )
                                ]
                                if session.is_ended
                                else []
                            ),
                        ],
                        spacing=3,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        f"{session.account_name} · {session.status_label}",
                        size=9,
                        color=color,
                    ),
                ],
                spacing=1,
            ),
        )

    def select_session(self, session_id: str) -> None:
        if self.controller.get_session(session_id) is None:
            return
        self.selected_session_id = session_id
        self._refresh_sessions()
        self._select_session_visual(session_id)
        self.page.update()

    def _select_session_visual(self, session_id: str | None) -> None:
        session = self.controller.get_session(session_id) if session_id else None
        self.log_list.controls.clear()
        self._log_cursor = 0
        if session is None:
            self.session_title.value = "未选择实例"
            self.session_status.value = ""
            self.stop_button.visible = False
            self.stop_button.disabled = True
            self.remove_button.visible = False
            self.export_button.disabled = True
            self.clear_button.disabled = True
            self.footer_status.value = "选择一个实例查看日志"
            return

        self.session_title.value = session.title
        self.session_status.value = (
            f"{session.status_label}"
            + (f" · PID {session.process.pid}" if session.process is not None else "")
        )
        self.session_status.color = _status_color(session.status)
        self.stop_button.visible = session.process is not None
        self.stop_button.disabled = session.process is None
        self.remove_button.visible = session.is_ended
        self.export_button.disabled = not session.logs
        self.clear_button.disabled = not session.logs
        self.footer_status.value = session.error or "日志实时更新"
        self._append_logs(session)

    def _append_logs(self, session: GameSession) -> None:
        if self._log_cursor > len(session.logs):
            self.log_list.controls.clear()
            self._log_cursor = 0
        active_filter = self.log_filter.value or "all"
        for entry in session.logs[self._log_cursor :]:
            if active_filter != "all" and entry.tag != active_filter:
                continue
            prefix = ""
            if entry.tag != TAG_NORMAL:
                prefix = f"[{tag_label(entry.tag)}] "
            color = tag_color(entry.tag) if entry.tag != TAG_NORMAL else _log_color(entry.level)
            self.log_list.controls.append(
                ft.Text(
                    f"{entry.time}  {prefix}{entry.text}",
                    size=9,
                    font_family="Consolas",
                    color=color,
                    no_wrap=True,
                )
            )
        self._log_cursor = len(session.logs)
        max_lines = 2000
        auto_scroll = True
        if self.app_settings_store is not None:
            prefs = self.app_settings_store.settings
            max_lines = prefs.log_max_lines
            auto_scroll = prefs.log_auto_scroll
        if len(self.log_list.controls) > max_lines:
            del self.log_list.controls[: len(self.log_list.controls) - max_lines]
        self.log_list.auto_scroll = auto_scroll
        if auto_scroll:
            try:
                # Flet 的 ListView 在追加控件后需要显式滚到底部。
                self.log_list.scroll_to(offset=-1)
            except Exception:
                pass

    def apply_preferences(self) -> None:
        if self.app_settings_store is not None:
            self.log_list.auto_scroll = self.app_settings_store.settings.log_auto_scroll
        session = self._selected()
        self.log_list.controls.clear()
        self._log_cursor = 0
        if session is not None:
            self._append_logs(session)
        self.page.update()

    def _on_log_filter_change(self, _event=None) -> None:
        session = self._selected()
        self.log_list.controls.clear()
        self._log_cursor = 0
        if session is not None:
            self._append_logs(session)
        self.page.update()

    # ---- 操作 ------------------------------------------------------------
    def _start_new_instance(self, _event=None) -> None:
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
            self.footer_status.value = "请选择游戏版本"
            self.page.update()
            return
        if account is None:
            self.footer_status.value = "请先登录账号"
            self.page.update()
            return

        requirement = read_local_version_java(version)
        java_path, major, _source = self._current_java(version.folder_name)
        if not java_path or major < requirement.major:
            self.java_requirement = requirement
            self._open_java_repair(start_after=True)
            return

        binding = self.binding_store.get(version.folder_name)
        session_id = self.controller.start_session(
            version,
            account,
            java_path=binding["path"] if binding else None,
            java_major=binding["major"] if binding else None,
        )
        self.selected_session_id = session_id
        self._refresh_sessions()
        self._select_session_visual(session_id)
        self.footer_status.value = "实例已创建，正在检查启动条件…"
        self.page.update()

    def _selected(self) -> GameSession | None:
        return (
            self.controller.get_session(self.selected_session_id)
            if self.selected_session_id
            else None
        )

    def _stop_selected(self, _event=None) -> None:
        session = self._selected()
        if session is None:
            return
        self.controller.stop_session(session.id)
        self.footer_status.value = "正在停止实例…"
        self.page.update()

    def _remove_selected(self, _event=None) -> None:
        session = self._selected()
        if session is not None:
            self._remove_session(session.id)

    def _remove_session(self, session_id: str) -> None:
        """删除已结束实例记录，保留运行中的实例。"""

        if not self.controller.remove_session(session_id):
            self.footer_status.value = "运行中的实例不能移除，请先停止"
            self.page.update()
            return
        if self.selected_session_id == session_id:
            self.selected_session_id = (
                self.controller.sessions[-1].id
                if self.controller.sessions
                else None
            )
        self._refresh_sessions()
        self._select_session_visual(self.selected_session_id)
        self.footer_status.value = "已移除实例记录"
        self.page.update()

    def _clear_logs(self, _event=None) -> None:
        session = self._selected()
        if session is None:
            return
        self.controller.clear_logs(session.id)
        self.log_list.controls.clear()
        self._log_cursor = 0
        self.export_button.disabled = True
        self.clear_button.disabled = True
        self.footer_status.value = "日志已清空"
        self.page.update()

    def _export_logs(self, _event=None) -> None:
        session = self._selected()
        if session is None:
            return
        text = self.controller.export_text(session.id)
        if not text:
            self.footer_status.value = "当前实例没有日志"
            self.page.update()
            return

        log_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "NLCL" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            safe_version = "".join(
                char if char.isalnum() or char in "-_." else "_"
                for char in session.version.version_id
            )
            path = log_dir / (
                f"NLCL-{safe_version}-{time.strftime('%Y%m%d-%H%M%S')}.log"
            )
            path.write_text(text, encoding="utf-8")
            self.footer_status.value = f"日志已导出：{path}"
        except OSError as exc:
            self.footer_status.value = f"导出失败：{exc}"
        self.page.update()

    # ---- 控制器回调 ------------------------------------------------------
    def _on_controller_update(self, session_id: str) -> None:
        now = time.monotonic()
        updated_session = self.controller.get_session(session_id)
        if (
            self.selected_session_id is not None
            and self.controller.get_session(self.selected_session_id) is None
        ):
            # 当前实例记录被移除后，自动切到最后一个实例或空状态。
            self.selected_session_id = (
                self.controller.sessions[-1].id
                if self.controller.sessions
                else None
            )
            self._refresh_sessions()
            self._select_session_visual(self.selected_session_id)
        if self.selected_session_id is None and self.controller.sessions:
            self.selected_session_id = self.controller.sessions[-1].id
            self._refresh_sessions()
            self._select_session_visual(self.selected_session_id)
        selected = self._selected()
        if selected is not None and selected.id == session_id:
            self._append_logs(selected)
            self.session_status.value = (
                f"{selected.status_label}"
                + (
                    f" · PID {selected.process.pid}"
                    if selected.process is not None
                    else ""
                )
            )
            self.session_status.color = _status_color(selected.status)
            self.stop_button.visible = selected.process is not None
            self.stop_button.disabled = selected.process is None
            self.remove_button.visible = selected.is_ended
            self.export_button.disabled = not selected.logs
            self.clear_button.disabled = not selected.logs
            self.footer_status.value = selected.error or "日志实时更新"

        # 日志行可以节流刷新；但实例结束必须立即刷新，否则界面会停留在
        # “运行中”，停止按钮/移除按钮也不会及时切换。
        force_update = updated_session is not None and updated_session.is_ended
        if force_update or now - self._last_update > 0.1:
            self._last_update = now
            self._refresh_sessions()
            try:
                self.page.update()
            except Exception:
                pass


def _status_color(status: str) -> str:
    return {
        "starting": WARN,
        "running": SUCCESS,
        "stopping": WARN,
        "stopped": MUTED,
        "exited": MUTED,
        "failed": ERROR,
    }.get(status, MUTED)


def _log_color(level: str) -> str:
    return {
        "error": "#FF9B8A",
        "warn": WARN,
        "success": "#8DD8AC",
        "cmd": "#9CC7FF",
    }.get(level, CONSOLE_TEXT)

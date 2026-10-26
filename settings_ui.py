"""独立设置页面：外观、Java、下载、日志和账号入口。"""

from __future__ import annotations

import asyncio

import flet as ft

from account_manager import AccountStore
from app_settings import AppSettings, AppSettingsStore
from download_throttle import set_download_limit
from launch_settings import (
    LaunchSettings,
    LaunchSettingsStore,
    validate_java_17,
)
from skin_ui import SkinManagerDialog
from theme_manager import THEME_LABELS, ThemeStore
from version_scanner import default_minecraft_dir
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


class SettingsView:
    def __init__(
        self,
        page: ft.Page,
        height: int | float | None,
        launch_settings_store: LaunchSettingsStore,
        app_settings_store: AppSettingsStore,
        theme_store: ThemeStore,
        account_store: AccountStore,
        on_theme_changed,
        on_download_directory_changed=None,
        on_account_manager=None,
        on_refresh=None,
    ) -> None:
        self.page = page
        self.launch_settings_store = launch_settings_store
        self.app_settings_store = app_settings_store
        self.theme_store = theme_store
        self.account_store = account_store
        self.on_theme_changed = on_theme_changed
        self.on_download_directory_changed = on_download_directory_changed
        self.on_account_manager = on_account_manager
        self.on_refresh = on_refresh
        self._skin_dialog: SkinManagerDialog | None = None
        self._java_picker = ft.FilePicker(on_result=self._on_java_picked)
        self._dir_picker = ft.FilePicker(on_result=self._on_dir_picked)

        self.view = self._build()
        self._load_values()

    # ---- 页面 ------------------------------------------------------------
    def _build(self) -> ft.Container:
        header = ft.Column(
            controls=[
                ft.Text(
                    "设置",
                    size=9,
                    color=PRIMARY,
                    weight=ft.FontWeight.W_600,
                    style=ft.TextStyle(letter_spacing=1.2),
                ),
                ft.Text("偏好设置", size=26, color=TEXT, weight=ft.FontWeight.W_700),
                ft.Text("外观、Java、下载、日志和账号皮肤。", size=11, color=MUTED),
            ],
            spacing=1,
        )

        self.theme_dropdown = ft.Dropdown(
            label="全局主题",
            width=260,
            dense=True,
            text_size=10,
            options=[
                ft.dropdown.Option(key=name, text=label)
                for name, label in THEME_LABELS.items()
            ],
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=4),
            on_change=self._on_theme_dropdown,
        )
        appearance = self._card(
            "外观",
            "切换后立即重建界面颜色；选择会保存到本地。",
            [
                ft.Row(
                    controls=[
                        self.theme_dropdown,
                        ft.Text("深色原版 / 浅色 / 柔和灰绿", size=9, color=FAINT),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            ],
        )

        self.java_path_field = ft.TextField(
            expand=True,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            text_size=10,
            hint_text=r"例如 E:\JDK\bin\java.exe",
        )
        self.java_validate_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "校验并保存"},
            icon=ft.Icons.VERIFIED_OUTLINED,
            on_click=self._validate_java,
        )
        self.java_status = ft.Text("", size=9, color=MUTED)
        self.min_memory_field = ft.TextField(
            label="最小内存 MB",
            width=150,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            text_size=10,
        )
        self.max_memory_field = ft.TextField(
            label="最大内存 MB",
            width=150,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            text_size=10,
        )
        self.jvm_args_field = ft.TextField(
            label="自定义 JVM 参数",
            expand=True,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            text_size=10,
            hint_text="-XX:+UseG1GC",
        )
        java_card = self._card(
            "Java 默认路径与内存",
            "全局 Java 设置；单个版本仍可在启动页通过实例绑定覆盖。",
            [
                ft.Row(
                    controls=[
                        self.java_path_field,
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            icon_size=16,
                            icon_color=PRIMARY,
                            tooltip="选择 java.exe",
                            on_click=self._pick_java,
                        ),
                        self.java_validate_button,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[
                        self.min_memory_field,
                        self.max_memory_field,
                        self.jvm_args_field,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.java_status,
            ],
        )

        self.download_dir_field = ft.TextField(
            expand=True,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            text_size=10,
        )
        self.download_limit_field = ft.TextField(
            label="下载限速 KB/s（0=不限）",
            width=180,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            text_size=10,
        )
        download_card = self._card(
            "下载",
            "下载目录用于版本下载；限速配置会保存到本地。",
            [
                ft.Row(
                    controls=[
                        self.download_dir_field,
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            icon_size=16,
                            icon_color=PRIMARY,
                            tooltip="选择下载目录",
                            on_click=self._pick_download_dir,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.download_limit_field,
            ],
        )

        self.log_max_field = ft.TextField(
            label="日志最大保留行数",
            width=180,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            text_size=10,
        )
        self.log_auto_scroll = ft.Switch(
            label="日志自动滚动到底部",
            value=True,
            active_color=PRIMARY,
        )
        log_card = self._card(
            "日志",
            "日志标签和筛选逻辑保持不变；这里保存显示偏好。",
            [
                ft.Row(
                    controls=[self.log_max_field, self.log_auto_scroll],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            ],
        )

        account_card = self._card(
            "账号与皮肤",
            "账号入口已移动到主内容顶部；可在此打开账号管理或皮肤管理。",
            [
                ft.Row(
                    controls=[
                        ft.OutlinedButton(
                            **{BUTTON_LABEL_FIELD: "账号管理"},
                            icon=ft.Icons.MANAGE_ACCOUNTS_OUTLINED,
                            on_click=self._open_account_manager,
                        ),
                        ft.OutlinedButton(
                            **{BUTTON_LABEL_FIELD: "皮肤管理"},
                            icon=ft.Icons.PALETTE_OUTLINED,
                            on_click=self._open_skin_manager,
                        ),
                    ],
                    spacing=8,
                )
            ],
        )

        self.save_status = ft.Text("", size=9, color=MUTED)
        save_row = ft.Row(
            controls=[
                ft.FilledButton(
                    **{BUTTON_LABEL_FIELD: "保存全部设置"},
                    icon=ft.Icons.SAVE_OUTLINED,
                    bgcolor=PRIMARY,
                    color="#FFFFFF",
                    on_click=self._save,
                ),
                self.save_status,
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(
                controls=[
                    header,
                    ft.Column(
                        controls=[
                            appearance,
                            java_card,
                            download_card,
                            log_card,
                            account_card,
                            save_row,
                        ],
                        spacing=10,
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                ],
                spacing=10,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    def _card(self, title: str, subtitle: str, controls) -> ft.Container:
        return ft.Container(
            bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=12,
            padding=PADDING.symmetric(horizontal=14, vertical=11),
            content=ft.Column(
                controls=[
                    ft.Text(title, size=12, color=TEXT, weight=ft.FontWeight.W_600),
                    ft.Text(subtitle, size=9, color=MUTED),
                    ft.Column(controls=controls, spacing=7),
                ],
                spacing=5,
            ),
        )

    # ---- 数据 ------------------------------------------------------------
    def _load_values(self) -> None:
        launch = self.launch_settings_store.settings
        app_settings = self.app_settings_store.settings
        self.java_path_field.value = launch.java_path
        self.download_dir_field.value = (
            app_settings.download_directory or str(default_minecraft_dir())
        )
        self.download_limit_field.value = str(app_settings.download_limit_kbps)
        self.log_max_field.value = str(app_settings.log_max_lines)
        self.log_auto_scroll.value = app_settings.log_auto_scroll
        self.min_memory_field.value = str(launch.min_memory_mb)
        self.max_memory_field.value = str(launch.max_memory_mb)
        self.jvm_args_field.value = launch.jvm_args
        self.theme_dropdown.value = self.theme_store.name
        if launch.java_path:
            self.java_status.value = (
                f"当前：Java {launch.java_version or '未知'}"
                f"（主版本 {launch.java_major or '?'}）"
            )

    def _on_theme_dropdown(self, _event=None) -> None:
        name = self.theme_dropdown.value or ""
        if name:
            self.on_theme_changed(name)

    def _pick_java(self, _event=None) -> None:
        self.page.overlay.append(self._java_picker)
        self._java_picker.pick_files(
            dialog_title="选择 Java 可执行文件",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["exe"],
        )

    def _on_java_picked(self, event) -> None:
        files = event.files or []
        if files and files[0].path:
            self.java_path_field.value = files[0].path
            self.page.update()

    def _validate_java(self, _event=None) -> None:
        path = (self.java_path_field.value or "").strip()
        if not path:
            self.java_status.value = "请选择 Java 路径"
            self.java_status.color = ERROR
            self.page.update()
            return
        self.java_validate_button.disabled = True
        self.java_status.value = "正在校验 Java…"
        self.java_status.color = MUTED
        self.page.update()
        self.page.run_task(self._validate_java_async, path)

    async def _validate_java_async(self, path: str) -> None:
        try:
            info = await asyncio.to_thread(validate_java_17, path)
            current = self.launch_settings_store.settings
            min_memory = int(self.min_memory_field.value or current.min_memory_mb)
            max_memory = int(self.max_memory_field.value or current.max_memory_mb)
            self.launch_settings_store.save(
                LaunchSettings(
                    java_path=info.path,
                    java_version=info.version,
                    java_major=info.major,
                    min_memory_mb=min_memory,
                    max_memory_mb=max_memory,
                    jvm_args=(self.jvm_args_field.value or "").strip(),
                )
            )
            self.java_path_field.value = info.path
            self.java_status.value = f"校验通过：Java {info.version}"
            self.java_status.color = PRIMARY
            if self.on_refresh is not None:
                self.on_refresh()
        except Exception as exc:
            self.java_status.value = f"校验失败：{exc}"
            self.java_status.color = ERROR
        finally:
            self.java_validate_button.disabled = False
            self.page.update()

    def _pick_download_dir(self, _event=None) -> None:
        self.page.overlay.append(self._dir_picker)
        self._dir_picker.get_directory_path(
            dialog_title="选择版本下载目录（.minecraft）",
        )

    def _on_dir_picked(self, event) -> None:
        if event.path:
            self.download_dir_field.value = event.path
            self.page.update()

    def _save(self, _event=None) -> None:
        try:
            app_settings = AppSettings(
                download_directory=(self.download_dir_field.value or "").strip(),
                download_limit_kbps=int(self.download_limit_field.value or 0),
                log_max_lines=int(self.log_max_field.value or 5000),
                log_auto_scroll=bool(self.log_auto_scroll.value),
            )
            self.app_settings_store.save(app_settings)
            set_download_limit(app_settings.download_limit_kbps)
            if self.on_download_directory_changed is not None:
                self.on_download_directory_changed(app_settings.download_directory)
            if self.on_refresh is not None:
                self.on_refresh()
            self.save_status.value = "设置已保存"
            self.save_status.color = PRIMARY
        except Exception as exc:
            self.save_status.value = f"保存失败：{exc}"
            self.save_status.color = ERROR
        self.page.update()

    def _open_account_manager(self, _event=None) -> None:
        if self.on_account_manager is not None:
            self.on_account_manager()

    def _open_skin_manager(self, _event=None) -> None:
        if self._skin_dialog is not None and self._skin_dialog.is_open:
            return
        self._skin_dialog = SkinManagerDialog(
            self.page,
            self.account_store,
            on_changed=self._skin_changed,
        )
        self._skin_dialog.open()

    def _skin_changed(self) -> None:
        if self.on_refresh is not None:
            self.on_refresh()

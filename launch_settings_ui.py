"""Java 与启动参数设置弹窗。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import flet as ft

from launch_settings import (
    LaunchSettings,
    LaunchSettingsError,
    LaunchSettingsStore,
    JavaInfo,
    JavaValidationError,
    validate_java_17,
)
from ui_theme import (
    BG,
    BORDER_COLOR,
    BUTTON_LABEL_FIELD,
    CARD,
    ERROR,
    FAINT,
    MUTED,
    PADDING,
    PRIMARY,
    PRIMARY_SOFT,
    TEXT,
)

OUTLINED_BUTTON_LABEL_FIELD = (
    "text" if hasattr(ft.OutlinedButton, "text") else "content"
)
CONTENT_HEIGHT = 330


class LaunchSettingsDialog:
    """Java 路径、内存和自定义 JVM 参数设置。"""

    def __init__(
        self,
        page: ft.Page,
        store: LaunchSettingsStore | None = None,
        on_saved=None,
    ) -> None:
        self.page = page
        self.store = store or LaunchSettingsStore()
        self.settings = self.store.settings
        self.on_saved = on_saved
        self._closed = False
        self._validation_generation = 0
        self.java_info: JavaInfo | None = None
        self._java_valid = False
        self._build()
        self._sync_java_state()

    @property
    def is_open(self) -> bool:
        return bool(self.dialog.open) and not self._closed

    # ---- 基础控件 --------------------------------------------------------
    def _build(self) -> None:
        self.close_button = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            icon_color=MUTED,
            tooltip="关闭",
            on_click=self._close,
        )
        title = ft.Row(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(
                            width=38,
                            height=38,
                            border_radius=10,
                            bgcolor=PRIMARY_SOFT,
                            alignment=ft.Alignment(0, 0),
                            content=ft.Icon(ft.Icons.COFFEE, color=PRIMARY, size=20),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "Java 与启动设置",
                                    size=18,
                                    color=TEXT,
                                    weight=ft.FontWeight.W_700,
                                ),
                                ft.Text(
                                    "Java 17、内存分配与自定义 JVM 参数",
                                    size=10,
                                    color=MUTED,
                                ),
                            ],
                            spacing=1,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.close_button,
            ],
            width=680,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.java_path_field = ft.TextField(
            value=self.settings.java_path,
            read_only=True,
            width=520,
            height=38,
            dense=True,
            filled=True,
            bgcolor=CARD,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            hint_text="请选择 JDK/JRE 17 的 bin\\java.exe",
            text_size=10,
        )
        self.browse_button = ft.OutlinedButton(
            **{OUTLINED_BUTTON_LABEL_FIELD: "浏览"},
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._pick_java_file,
        )
        self.clear_java_button = ft.IconButton(
            icon=ft.Icons.CLEAR,
            icon_size=16,
            icon_color=MUTED,
            tooltip="清除 Java 路径",
            on_click=self._clear_java_path,
        )
        self.java_spinner = ft.ProgressRing(
            width=16,
            height=16,
            stroke_width=2.2,
            color=PRIMARY,
            visible=False,
        )
        self.java_status = ft.Text("尚未选择 Java 17", size=10, color=MUTED)

        min_value = _snap(self.settings.min_memory_mb, 512, 256)
        max_value = _snap(self.settings.max_memory_mb, 1024, 256)
        if max_value < min_value:
            max_value = min_value

        self.min_slider = ft.Slider(
            min=512,
            max=16384,
            divisions=(16384 - 512) // 256,
            value=min_value,
            width=480,
            height=28,
            active_color=PRIMARY,
            inactive_color="#DCE9E1",
            on_change=self._on_min_memory_changed,
        )
        self.max_slider = ft.Slider(
            min=1024,
            max=32768,
            divisions=(32768 - 1024) // 256,
            value=max_value,
            width=480,
            height=28,
            active_color=PRIMARY,
            inactive_color="#DCE9E1",
            on_change=self._on_max_memory_changed,
        )
        self.min_value_text = ft.Text(
            _memory_label(min_value),
            size=10,
            color=TEXT,
            width=110,
        )
        self.max_value_text = ft.Text(
            _memory_label(max_value),
            size=10,
            color=TEXT,
            width=110,
        )

        self.jvm_args_field = ft.TextField(
            value=self.settings.jvm_args,
            multiline=True,
            min_lines=2,
            max_lines=3,
            width=688,
            height=58,
            dense=True,
            filled=True,
            bgcolor=CARD,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            hint_text="-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions ...",
            text_size=10,
        )
        self.save_status = ft.Text("", size=10, color=MUTED, width=430)
        self.save_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "保存设置"},
            icon=ft.Icons.SAVE_OUTLINED,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            on_click=self._save_settings,
        )

        content = ft.Container(
            width=720,
            height=CONTENT_HEIGHT,
            bgcolor=BG,
            padding=PADDING.symmetric(horizontal=16, vertical=14),
            content=ft.Column(
                controls=[
                    ft.Text("Java 路径", size=9, color=FAINT),
                    ft.Row(
                        controls=[
                            self.java_path_field,
                            self.browse_button,
                            self.clear_java_button,
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        controls=[self.java_spinner, self.java_status],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text("内存分配", size=9, color=FAINT),
                    ft.Row(
                        controls=[
                            ft.Text("最小内存", size=10, color=TEXT, width=62),
                            self.min_slider,
                            self.min_value_text,
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        controls=[
                            ft.Text("最大内存", size=10, color=TEXT, width=62),
                            self.max_slider,
                            self.max_value_text,
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        "建议最大内存不超过物理内存的 50%。",
                        size=9,
                        color=FAINT,
                    ),
                    ft.Text("自定义 JVM 参数", size=9, color=FAINT),
                    self.jvm_args_field,
                    ft.Container(expand=True),
                    ft.Row(
                        controls=[
                            self.save_status,
                            self.save_button,
                        ],
                        width=688,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=4,
                expand=True,
            ),
        )

        self.dialog = ft.AlertDialog(
            modal=True,
            title=title,
            content=content,
            content_padding=0,
            title_padding=PADDING.only(left=20, right=20, top=12),
            bgcolor=CARD,
            shape=ft.RoundedRectangleBorder(radius=18),
            inset_padding=24,
            on_dismiss=self._on_dismiss,
        )

        self.java_picker = ft.FilePicker(on_result=self._on_java_picked)
        if self.java_picker not in self.page.overlay:
            self.page.overlay.append(self.java_picker)

    # ---- Java 路径 -------------------------------------------------------
    def _sync_java_state(self) -> None:
        if self.settings.java_path and self.settings.java_major == 17:
            self._java_valid = True
            self.java_status.value = (
                f"已保存 Java {self.settings.java_version or '17'}"
            )
            self.java_status.color = PRIMARY
            self.java_path_field.value = self.settings.java_path
        elif self.settings.java_path:
            self.java_path_field.value = self.settings.java_path
            self.java_status.value = "已保存的 Java 路径需要重新校验"
            self.java_status.color = MUTED
        else:
            self.java_status.value = "尚未选择 Java 17"
            self.java_status.color = MUTED

    def _pick_java_file(self, _event=None) -> None:
        current = (self.java_path_field.value or "").strip()
        initial = str(Path(current).parent) if current else None
        self.java_picker.pick_files(
            dialog_title="选择 Java 17 的 java.exe",
            initial_directory=initial,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["exe"],
            allow_multiple=False,
        )

    def _on_java_picked(self, event) -> None:
        files = getattr(event, "files", None) or []
        if not files:
            return
        path = getattr(files[0], "path", "")
        if path:
            self._start_java_validation(path)

    def _start_java_validation(self, path: str) -> None:
        self._validation_generation += 1
        generation = self._validation_generation
        self._java_valid = False
        self.java_info = None
        self.java_path_field.value = path
        self.java_spinner.visible = True
        self.java_status.value = "正在校验 Java 版本…"
        self.java_status.color = MUTED
        self.save_status.value = ""
        self.page.update()
        self.page.run_task(self._validate_java_async, path, generation)

    async def _validate_java_async(self, path: str, generation: int) -> None:
        try:
            info = await asyncio.to_thread(validate_java_17, path)
        except JavaValidationError as exc:
            self._finish_java_validation_error(str(exc), generation)
            return
        except Exception as exc:
            self._finish_java_validation_error(f"校验失败：{exc}", generation)
            return

        if not self._validation_active(generation):
            return

        self.java_info = info
        self._java_valid = True
        self.settings.java_path = info.path
        self.settings.java_version = info.version
        self.settings.java_major = info.major
        self.java_path_field.value = info.path
        self.java_spinner.visible = False
        self.java_status.value = f"Java {info.version} 已验证（主版本 17）"
        self.java_status.color = PRIMARY
        self.save_status.value = ""
        self.page.update()

    def _finish_java_validation_error(self, message: str, generation: int) -> None:
        if not self._validation_active(generation):
            return
        self._java_valid = False
        self.java_info = None
        self.java_spinner.visible = False
        self.java_status.value = message
        self.java_status.color = ERROR
        self.page.update()

    def _validation_active(self, generation: int) -> bool:
        return (
            not self._closed
            and generation == self._validation_generation
            and bool(self.dialog.open)
        )

    def _clear_java_path(self, _event=None) -> None:
        self._validation_generation += 1
        self._java_valid = False
        self.java_info = None
        self.settings.java_path = ""
        self.settings.java_version = ""
        self.settings.java_major = 0
        self.java_path_field.value = ""
        self.java_spinner.visible = False
        self.java_status.value = "尚未选择 Java 17"
        self.java_status.color = MUTED
        self.save_status.value = ""
        self.page.update()

    # ---- 内存滑块 --------------------------------------------------------
    def _on_min_memory_changed(self, event) -> None:
        value = _snap(int(event.control.value or 512), 512, 256)
        self.min_slider.value = value
        if value > int(self.max_slider.value or 1024):
            self.max_slider.value = value
            self.max_value_text.value = _memory_label(value)
        self.min_value_text.value = _memory_label(value)
        self.page.update()

    def _on_max_memory_changed(self, event) -> None:
        value = _snap(int(event.control.value or 1024), 1024, 256)
        self.max_slider.value = value
        if value < int(self.min_slider.value or 512):
            self.min_slider.value = value
            self.min_value_text.value = _memory_label(value)
        self.max_value_text.value = _memory_label(value)
        self.page.update()

    # ---- 保存 ------------------------------------------------------------
    def _save_settings(self, _event=None) -> None:
        path_text = (self.java_path_field.value or "").strip()
        if path_text and not self._java_valid:
            self._set_save_status("请先完成 Java 17 校验，或清除无效路径", ERROR)
            return

        min_memory = _snap(int(self.min_slider.value or 512), 512, 256)
        max_memory = _snap(int(self.max_slider.value or 1024), 1024, 256)
        if max_memory < min_memory:
            max_memory = min_memory

        settings = LaunchSettings(
            java_path=self.settings.java_path if self._java_valid else "",
            java_version=self.settings.java_version if self._java_valid else "",
            java_major=self.settings.java_major if self._java_valid else 0,
            min_memory_mb=min_memory,
            max_memory_mb=max_memory,
            jvm_args=self.jvm_args_field.value or "",
        )
        try:
            self.settings = self.store.save(settings)
        except LaunchSettingsError as exc:
            self._set_save_status(str(exc), ERROR)
            return

        self._set_save_status("设置已保存", PRIMARY)
        if self.on_saved is not None:
            self.on_saved(self.settings)

    def _set_save_status(self, message: str, color: str) -> None:
        self.save_status.value = message
        self.save_status.color = color
        self.page.update()

    # ---- 打开/关闭 -------------------------------------------------------
    def open(self) -> None:
        self.page.open(self.dialog)
        self.page.update()
        if self.settings.java_path:
            self._start_java_validation(self.settings.java_path)

    def _on_dismiss(self, _event=None) -> None:
        self._closed = True
        self._remove_picker()

    def _close(self, _event=None) -> None:
        self._closed = True
        self.page.close(self.dialog)
        self._remove_picker()
        self.page.update()

    def _remove_picker(self) -> None:
        try:
            if self.java_picker in self.page.overlay:
                self.page.overlay.remove(self.java_picker)
        except (ValueError, AttributeError):
            pass


def _snap(value: int, minimum: int, step: int) -> int:
    if value <= minimum:
        return minimum
    return minimum + round((value - minimum) / step) * step


def _memory_label(mb: int) -> str:
    if mb >= 1024:
        return f"{mb} MB · {mb / 1024:.1f} GB"
    return f"{mb} MB"

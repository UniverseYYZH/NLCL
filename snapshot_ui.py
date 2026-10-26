"""实例轻量快照页面：saves / config / options.txt。"""

from __future__ import annotations

import asyncio

import flet as ft

from snapshot_manager import Snapshot, SnapshotManager
from ui_helpers import format_bytes
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


class SnapshotView:
    def __init__(
        self,
        page: ft.Page,
        versions: list[LocalVersion],
        height: int | float,
        manager: SnapshotManager | None = None,
    ) -> None:
        self.page = page
        self.versions = list(versions)
        self.height = height
        self.manager = manager or SnapshotManager()
        self.version_by_folder = {item.folder_name: item for item in versions}
        self._dialog: ft.AlertDialog | None = None

        self.view = self._build()
        self.refresh()

    def _build(self) -> ft.Container:
        header = ft.Column(
            controls=[
                ft.Text(
                    "实例快照",
                    size=9,
                    color=PRIMARY,
                    weight=ft.FontWeight.W_600,
                    style=ft.TextStyle(letter_spacing=1.2),
                ),
                ft.Text("轻量备份", size=26, color=TEXT, weight=ft.FontWeight.W_700),
                ft.Text(
                    "只备份 saves 存档、config 配置和 options.txt，不包含 mods 或完整整合包。",
                    size=11,
                    color=MUTED,
                ),
            ],
            spacing=1,
        )

        self.version_dropdown = ft.Dropdown(
            label="目标实例",
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
        self.note_field = ft.TextField(
            label="快照备注",
            width=280,
            height=42,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            hint_text="例如：加模组前、建筑完成",
            text_size=10,
        )
        self.create_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "创建快照"},
            icon=ft.Icons.CAMERA_ALT_OUTLINED,
            width=130,
            height=42,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            on_click=self._create_snapshot,
        )
        create_card = ft.Container(
                        bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=12,
            padding=PADDING.symmetric(horizontal=14, vertical=10),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            self.version_dropdown,
                            self.note_field,
                            self.create_button,
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        f"快照目录：{self.manager.root}",
                        size=8,
                        color=FAINT,
                                            ),
                ],
                spacing=5,
            ),
        )

        self.list_view = ft.ListView(expand=True, spacing=8, padding=0)
        self.list_card = ft.Container(
                        bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=12,
            padding=PADDING.symmetric(horizontal=12, vertical=10),
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text("快照列表", size=9, color=FAINT),
                    self.list_view,
                ],
                spacing=6,
                expand=True,
            ),
        )
        self.status_text = ft.Text("", size=9, color=FAINT)
        return ft.Container(
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(
                controls=[
                    header,
                    create_card,
                    self.list_card,
                    self.status_text,
                ],
                spacing=10,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

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
        self.create_button.disabled = not self.versions
        self._render_list()
        self.page.update()

    def _selected_version(self) -> LocalVersion | None:
        return self.version_by_folder.get(self.version_dropdown.value or "")

    def _on_version_changed(self, _event=None) -> None:
        self._render_list()
        self.page.update()

    def _minecraft_dir(self, version: LocalVersion):
        return version.directory.parent.parent

    def _render_list(self) -> None:
        self.list_view.controls.clear()
        selected = self._selected_version()
        snapshots = self.manager.list_snapshots()
        if selected is not None:
            snapshots = [
                item
                for item in snapshots
                if item.folder_name in ("", selected.folder_name)
            ]
        if not snapshots:
            self.list_view.controls.append(
                ft.Container(
                    padding=PADDING.symmetric(vertical=30),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text(
                        "该实例还没有快照。创建快照只会复制 saves、config 和 options.txt。",
                        size=10,
                        color=FAINT,
                    ),
                )
            )
            return
        for snapshot in snapshots:
            self.list_view.controls.append(self._snapshot_card(snapshot))

    def _snapshot_card(self, snapshot: Snapshot) -> ft.Container:
        return ft.Container(
                        bgcolor=SURFACE,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=10,
            padding=PADDING.symmetric(horizontal=11, vertical=9),
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=36,
                        height=36,
                        border_radius=9,
                        bgcolor=PRIMARY_SOFT,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(
                            ft.Icons.CAMERA_ALT_OUTLINED,
                            size=18,
                            color=PRIMARY,
                        ),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(
                                snapshot.title,
                                size=11,
                                color=TEXT,
                                weight=ft.FontWeight.W_600,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=410,
                            ),
                            ft.Text(
                                f"{snapshot.version_id} · {snapshot.created_at} · "
                                f"{snapshot.files} 个文件 · {format_bytes(snapshot.size)}",
                                size=9,
                                color=MUTED,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=410,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.TextButton(
                        **{TEXT_BUTTON_LABEL_FIELD: "回滚"},
                        icon=ft.Icons.RESTORE,
                        on_click=lambda _e, item=snapshot: self._confirm_rollback(item),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_size=16,
                        icon_color=FAINT,
                        tooltip="删除快照",
                        on_click=lambda _e, item=snapshot: self._confirm_delete(item),
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _create_snapshot(self, _event=None) -> None:
        version = self._selected_version()
        if version is None:
            return
        self.create_button.disabled = True
        self.status_text.value = "正在创建快照…"
        self.status_text.color = MUTED
        self.page.update()
        self.page.run_task(self._create_snapshot_async, version)

    async def _create_snapshot_async(self, version: LocalVersion) -> None:
        try:
            snapshot = await asyncio.to_thread(
                self.manager.create_snapshot,
                self._minecraft_dir(version),
                version.version_id,
                version.folder_name,
                (self.note_field.value or "").strip(),
            )
            self.note_field.value = ""
            self.status_text.value = f"快照已创建：{snapshot.title}"
            self.status_text.color = PRIMARY
            self._render_list()
        except Exception as exc:
            self.status_text.value = f"创建快照失败：{exc}"
            self.status_text.color = ERROR
        finally:
            self.create_button.disabled = not self.versions
            self.page.update()

    def _confirm_rollback(self, snapshot: Snapshot) -> None:
        version = self._selected_version()
        if version is None:
            return
        self._show_dialog(
            title="回滚快照",
            message=(
                f"将用快照「{snapshot.title}」覆盖当前的 saves、config 和 "
                "options.txt。\n\n回滚前会自动创建一份保护快照。"
            ),
            confirm_text="确认回滚",
            on_confirm=lambda _e: self._start_rollback(snapshot, version),
        )

    def _start_rollback(self, snapshot: Snapshot, version: LocalVersion) -> None:
        self._close_dialog()
        self.status_text.value = "正在回滚…"
        self.status_text.color = MUTED
        self.page.update()
        self.page.run_task(self._rollback_async, snapshot, version)

    async def _rollback_async(
        self,
        snapshot: Snapshot,
        version: LocalVersion,
    ) -> None:
        try:
            safety = await asyncio.to_thread(
                self.manager.rollback,
                snapshot,
                self._minecraft_dir(version),
            )
            if safety is None:
                self.status_text.value = "回滚完成（当前目录为空，未创建保护快照）"
            else:
                self.status_text.value = f"回滚完成，保护快照：{safety.title}"
            self.status_text.color = PRIMARY
            self._render_list()
        except Exception as exc:
            self.status_text.value = f"回滚失败：{exc}"
            self.status_text.color = ERROR
        self.page.update()

    def _confirm_delete(self, snapshot: Snapshot) -> None:
        self._show_dialog(
            title="删除快照",
            message=f"确定删除快照「{snapshot.title}」？此操作不可恢复。",
            confirm_text="删除",
            on_confirm=lambda _e: self._delete_snapshot(snapshot),
        )

    def _delete_snapshot(self, snapshot: Snapshot) -> None:
        self._close_dialog()
        try:
            self.manager.delete(snapshot)
            self.status_text.value = "快照已删除"
            self.status_text.color = MUTED
            self._render_list()
        except Exception as exc:
            self.status_text.value = f"删除失败：{exc}"
            self.status_text.color = ERROR
        self.page.update()

    def _show_dialog(self, title, message, confirm_text, on_confirm) -> None:
        self._dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, size=16, color=TEXT),
            content=ft.Text(message, size=10, color=MUTED, width=380),
            actions=[
                ft.TextButton(
                    **{TEXT_BUTTON_LABEL_FIELD: "取消"},
                    on_click=lambda _e: self._close_dialog(),
                ),
                ft.FilledButton(
                    **{BUTTON_LABEL_FIELD: confirm_text},
                    bgcolor=PRIMARY,
                    color="#FFFFFF",
                    on_click=on_confirm,
                ),
            ],
        )
        self.page.open(self._dialog)
        self.page.update()

    def _close_dialog(self) -> None:
        if self._dialog is not None and self._dialog.open:
            self.page.close(self._dialog)
        self._dialog = None
        self.page.update()

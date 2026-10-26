"""本地版本详情弹窗，以及带两次确认的版本删除流程。"""

from __future__ import annotations

import asyncio
import os

import flet as ft

from ui_helpers import format_bytes, format_release_date
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
    TYPE_STYLES,
)
from version_details import (
    ContentItem,
    VersionDetails,
    delete_version_folder,
    scan_version_details,
)
from version_scanner import LocalVersion, version_type_label


class VersionDetailsDialog:
    """展示版本信息、mods/资源包/整合包，并提供删除入口。"""

    def __init__(
        self,
        page: ft.Page,
        version: LocalVersion,
        minecraft_directory: str,
        on_deleted,
    ) -> None:
        self.page = page
        self.version = version
        self.minecraft_directory = str(minecraft_directory)
        self.on_deleted = on_deleted
        self.details: VersionDetails = scan_version_details(version, minecraft_directory)

        self.deleting = False
        self._closed = False
        self._build()

    @property
    def is_open(self) -> bool:
        return bool(self.dialog.open) and not self._closed

    # ---- 构建界面 --------------------------------------------------------
    def _build(self) -> None:
        color, soft_color, icon = _type_style(self.version.version_type)
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
                            content=ft.Icon(
                                ft.Icons.ARCHIVE_OUTLINED,
                                color=PRIMARY,
                                size=20,
                            ),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(
                                    "版本详情",
                                    size=18,
                                    color=TEXT,
                                    weight=ft.FontWeight.W_700,
                                ),
                                ft.Text(
                                    self.version.version_id,
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

        meta_parts = [f"{_type_label(self.version.version_type)} · {format_release_date(self.version.release_time)}"]
        if self.version.inherits_from:
            meta_parts.append(f"基于 {self.version.inherits_from}")

        jar_text = "JAR 已安装" if self.details.client_jar else "缺少 JAR"
        jar_bg = PRIMARY_SOFT if self.details.client_jar else AMBER_BG
        jar_fg = PRIMARY if self.details.client_jar else AMBER

        info_card = ft.Container(
            width=688,
            bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=10,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                width=42,
                                height=42,
                                border_radius=11,
                                bgcolor=soft_color,
                                alignment=ft.Alignment(0, 0),
                                content=ft.Icon(icon, size=21, color=color),
                            ),
                            ft.Column(
                                controls=[
                                    ft.Row(
                                        controls=[
                                            ft.Text(
                                                self.version.version_id,
                                                size=17,
                                                color=TEXT,
                                                weight=ft.FontWeight.W_600,
                                                max_lines=1,
                                                overflow=ft.TextOverflow.ELLIPSIS,
                                                width=430,
                                            ),
                                            _type_badge(self.version.version_type),
                                        ],
                                        spacing=8,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                    ft.Text(
                                        " · ".join(meta_parts),
                                        size=10,
                                        color=MUTED,
                                    ),
                                ],
                                spacing=3,
                                width=510,
                            ),
                            ft.Container(
                                padding=PADDING.symmetric(horizontal=7, vertical=3),
                                border_radius=6,
                                bgcolor=jar_bg,
                                content=ft.Text(jar_text, size=9, color=jar_fg),
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        str(self.version.directory),
                        size=9,
                        color=FAINT,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        width=660,
                    ),
                ],
                spacing=7,
                tight=True,
            ),
        )

        self.count_row = ft.Row(
            controls=[
                _count_chip("Mods", len(self.details.mods), PRIMARY, PRIMARY_SOFT),
                _count_chip("资源包", len(self.details.resourcepacks), "#5A6D9B", "#ECF0FA"),
                _count_chip("光影", len(self.details.shaderpacks), "#7A5A9B", "#F3ECFA"),
                _count_chip(
                    "整合包",
                    1 if self.details.modpack else 0,
                    AMBER,
                    AMBER_BG,
                ),
            ],
            spacing=6,
            width=688,
        )

        self.content_list = ft.ListView(
            width=688,
            height=135,
            spacing=2,
            padding=0,
            auto_scroll=False,
        )
        self._fill_content_list()

        self.open_folder_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "打开版本目录"},
            icon=ft.Icons.FOLDER_OPEN,
            icon_color=PRIMARY,
            on_click=self._open_folder,
        )
        self.delete_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "删除此版本"},
            icon=ft.Icons.DELETE_OUTLINE,
            icon_color=ERROR,
            style=ft.ButtonStyle(color=ERROR),
            on_click=self._ask_delete,
        )
        actions = ft.Row(
            controls=[self.open_folder_button, self.delete_button],
            width=688,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        content_box = ft.Container(
            width=720,
            height=350,
            bgcolor=BG,
            padding=PADDING.symmetric(horizontal=16, vertical=10),
            content=ft.Column(
                controls=[info_card, self.count_row, self.content_list, actions],
                spacing=8,
                expand=True,
            ),
        )

        self.dialog = ft.AlertDialog(
            modal=True,
            title=title,
            content=content_box,
            content_padding=0,
            title_padding=PADDING.only(left=20, right=20, top=12),
            bgcolor=CARD,
            shape=ft.RoundedRectangleBorder(radius=18),
            inset_padding=24,
            on_dismiss=self._on_dismiss,
        )
        self.original_title = title
        self.details_content = content_box
        self.delete_step_1 = self._build_delete_step_1()
        self.delete_step_2 = self._build_delete_step_2()

    def _fill_content_list(self) -> None:
        self.content_list.controls.clear()
        self._add_section("MODS", len(self.details.mods))
        if self.details.mods:
            for item in self.details.mods:
                self._add_item(item, ft.Icons.EXTENSION_OUTLINED)
        else:
            self._add_empty("未在游戏目录或版本目录中找到 mods")

        self._add_section("资源包", len(self.details.resourcepacks))
        if self.details.resourcepacks:
            for item in self.details.resourcepacks:
                self._add_item(item, ft.Icons.PALETTE_OUTLINED)
        else:
            self._add_empty("未找到资源包")

        self._add_section("光影", len(self.details.shaderpacks))
        if self.details.shaderpacks:
            for item in self.details.shaderpacks:
                self._add_item(item, ft.Icons.VIDEO_SETTINGS)
        else:
            self._add_empty("未找到光影包")

        self._add_section("整合包")
        if self.details.modpack:
            pack = self.details.modpack
            suffix = f" · {pack.version}" if pack.version else ""
            self.content_list.controls.append(
                _content_row(
                    icon=ft.Icons.INVENTORY_2_OUTLINED,
                    name=pack.name,
                    meta=f"{pack.kind}{suffix} · {pack.source}",
                )
            )
        else:
            self._add_empty("未检测到 Modrinth / CurseForge / MultiMC 整合包清单")

        if self.details.issues:
            self._add_section("读取问题", len(self.details.issues))
            for issue in self.details.issues:
                self.content_list.controls.append(
                    ft.Text(issue, size=9, color=AMBER)
                )

    def _add_section(self, label: str, count: int | None = None) -> None:
        texts = [
            ft.Text(
                label,
                size=9,
                color=PRIMARY,
                weight=ft.FontWeight.W_600,
                style=ft.TextStyle(letter_spacing=0.8),
            )
        ]
        if count is not None:
            texts.append(ft.Text(str(count), size=9, color=FAINT))
        self.content_list.controls.append(
            ft.Container(
                padding=PADDING.only(left=4, top=6, bottom=2),
                content=ft.Row(controls=texts, spacing=5),
            )
        )

    def _add_empty(self, text: str) -> None:
        self.content_list.controls.append(
            ft.Container(
                padding=PADDING.only(left=22, top=3, bottom=3),
                content=ft.Text(text, size=10, color=FAINT),
            )
        )

    def _add_item(self, item: ContentItem, icon) -> None:
        if item.is_dir:
            meta = f"{item.source} · 文件夹"
        else:
            meta = f"{item.source} · {format_bytes(item.size)}"
        self.content_list.controls.append(
            _content_row(
                icon=icon,
                name=item.name,
                meta=meta,
                disabled=item.enabled is False,
            )
        )

    # ---- 打开/关闭 -------------------------------------------------------
    def open(self) -> None:
        self.page.open(self.dialog)
        self.page.update()

    def _on_dismiss(self, _event=None) -> None:
        if not self.deleting:
            self._closed = True

    def _close(self, _event=None) -> None:
        if self.deleting:
            return
        self._closed = True
        self.page.close(self.dialog)
        self.page.update()

    # ---- 打开目录 --------------------------------------------------------
    def _open_folder(self, _event=None) -> None:
        try:
            os.startfile(str(self.version.directory))
        except OSError as exc:
            self.page.open(
                ft.SnackBar(
                    content=ft.Text(f"无法打开版本目录：{exc}", color="#FFFFFF"),
                    duration=3000,
                )
            )

    # ---- 两次确认删除 ----------------------------------------------------
    def _build_delete_step_1(self) -> ft.Container:
        return ft.Container(
            width=720,
            height=350,
            bgcolor=BG,
            padding=24,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.DELETE_OUTLINE, size=30, color=AMBER),
                            ft.Text(
                                f"删除版本「{self.version.version_id}」？",
                                size=18,
                                color=TEXT,
                                weight=ft.FontWeight.W_700,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        "这一步不会立即删除。请确认你不再需要这个版本。",
                        size=11,
                        color=MUTED,
                    ),
                    ft.Container(
                        padding=12,
                        border_radius=9,
                        bgcolor=AMBER_BG,
                        border=BORDER.all(1, AMBER_BORDER),
                        content=ft.Text(
                            "只会删除 versions 下的这个版本目录，不会删除 mods、resourcepacks 或其他版本。",
                            size=10,
                            color=AMBER,
                        ),
                    ),
                    ft.Container(expand=True),
                    ft.Row(
                        controls=[
                            ft.TextButton(
                                **{TEXT_BUTTON_LABEL_FIELD: "取消"},
                                on_click=self._cancel_delete,
                            ),
                            ft.FilledButton(
                                **{BUTTON_LABEL_FIELD: "继续"},
                                bgcolor=ERROR,
                                color="#FFFFFF",
                                on_click=self._continue_delete,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.END,
                        spacing=8,
                    ),
                ],
                spacing=14,
                expand=True,
            ),
        )

    def _build_delete_step_2(self) -> ft.Container:
        self.delete_step2_status = ft.Text("", size=10, color=MUTED)
        self.delete_step2_error = ft.Text(
            "",
            size=10,
            color=ERROR,
            selectable=True,
            visible=False,
        )
        self.confirm_delete_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "确认删除"},
            bgcolor=ERROR,
            color="#FFFFFF",
            on_click=self._confirm_delete,
        )
        self.cancel_delete_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "取消"},
            on_click=self._cancel_delete,
        )

        return ft.Container(
            width=720,
            height=350,
            bgcolor=BG,
            padding=24,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=24, color=ERROR),
                            ft.Text(
                                "此操作不可恢复。请再次确认删除该版本。",
                                size=12,
                                color=ERROR,
                                weight=ft.FontWeight.W_600,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        f"版本：{self.version.version_id}",
                        size=11,
                        color=TEXT,
                    ),
                    ft.Text(
                        f"目录：{self.version.directory}",
                        size=9,
                        color=MUTED,
                        selectable=True,
                    ),
                    self.delete_step2_status,
                    self.delete_step2_error,
                    ft.Container(expand=True),
                    ft.Row(
                        controls=[
                            self.cancel_delete_button,
                            self.confirm_delete_button,
                        ],
                        alignment=ft.MainAxisAlignment.END,
                        spacing=8,
                    ),
                ],
                spacing=10,
                expand=True,
            ),
        )

    def _ask_delete(self, _event=None) -> None:
        if self.deleting:
            return
        self.dialog.title = ft.Text(
            "删除版本？",
            size=18,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.dialog.content = self.delete_step_1
        self.page.update()

    def _continue_delete(self, _event=None) -> None:
        self.delete_step2_status.value = ""
        self.delete_step2_status.color = MUTED
        self.delete_step2_error.visible = False
        self.confirm_delete_button.disabled = False
        self.cancel_delete_button.disabled = False
        self.dialog.title = ft.Text(
            "再次确认删除",
            size=18,
            color=ERROR,
            weight=ft.FontWeight.W_700,
        )
        self.dialog.content = self.delete_step_2
        self.page.update()

    def _cancel_delete(self, _event=None) -> None:
        if self.deleting:
            return
        self.dialog.title = self.original_title
        self.dialog.content = self.details_content
        self.page.update()

    def _confirm_delete(self, _event=None) -> None:
        if self.deleting:
            return
        self.deleting = True
        self.confirm_delete_button.disabled = True
        self.cancel_delete_button.disabled = True
        self.delete_step2_status.value = "正在删除版本目录…"
        self.delete_step2_status.color = MUTED
        self.delete_step2_error.visible = False
        self.page.update()
        self.page.run_task(self._delete_async)

    async def _delete_async(self) -> None:
        try:
            await asyncio.to_thread(
                delete_version_folder,
                self.minecraft_directory,
                self.version.folder_name,
            )
        except Exception as exc:
            self.deleting = False
            self.confirm_delete_button.disabled = False
            self.cancel_delete_button.disabled = False
            self.delete_step2_status.value = "删除失败"
            self.delete_step2_status.color = ERROR
            self.delete_step2_error.value = str(exc)
            self.delete_step2_error.visible = True
            self.page.update()
            return

        self.deleting = False
        self._closed = True
        self.page.close(self.dialog)
        self.page.update()
        self.on_deleted()


def _content_row(
    *,
    icon,
    name: str,
    meta: str,
    disabled: bool = False,
) -> ft.Container:
    controls = [
        ft.Icon(icon, size=16, color=MUTED),
        ft.Column(
            controls=[
                ft.Text(
                    name,
                    size=11,
                    color=TEXT,
                    weight=ft.FontWeight.W_600,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    width=480,
                ),
                ft.Text(meta, size=9, color=MUTED, max_lines=1),
            ],
            spacing=1,
            width=540,
        ),
    ]
    if disabled:
        controls.append(
            ft.Container(
                padding=PADDING.symmetric(horizontal=6, vertical=2),
                border_radius=5,
                bgcolor=AMBER_BG,
                content=ft.Text("已禁用", size=9, color=AMBER),
            )
        )

    return ft.Container(
        width=688,
        padding=PADDING.symmetric(horizontal=6, vertical=5),
        border_radius=7,
        bgcolor=SURFACE,
        content=ft.Row(
            controls=controls,
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def _count_chip(label: str, count: int, color: str, bgcolor: str) -> ft.Container:
    return ft.Container(
        padding=PADDING.symmetric(horizontal=8, vertical=3),
        border_radius=7,
        bgcolor=bgcolor,
        content=ft.Row(
            controls=[
                ft.Container(width=4, height=4, border_radius=2, bgcolor=color),
                ft.Text(f"{label} {count}", size=10, color=color),
            ],
            spacing=5,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def _type_badge(version_type: str) -> ft.Container:
    color, bgcolor, _icon = _type_style(version_type)
    return ft.Container(
        padding=PADDING.symmetric(horizontal=7, vertical=2),
        border_radius=6,
        bgcolor=bgcolor,
        content=ft.Text(
            version_type_label(version_type),
            size=9,
            color=color,
            weight=ft.FontWeight.W_600,
        ),
    )


def _type_style(version_type: str):
    return TYPE_STYLES.get(version_type, (MUTED, SURFACE, ft.Icons.INVENTORY_2_OUTLINED))


def _type_label(version_type: str) -> str:
    return version_type_label(version_type)

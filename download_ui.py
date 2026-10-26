"""版本下载弹窗（原版 / Fabric / Forge + Java 运行时）。

交互流程：
1. 打开弹窗后，在后台线程/协程中获取 Mojang 版本列表；
2. 选择原版 / Fabric / Forge，搜索并选择 Minecraft 版本；
3. 自动读取版本 JSON 的 Java 要求，展示推荐 Java 和下载入口；
4. 点击下载后，后台线程调用 minecraft-launcher-lib；
5. UI 每 0.4 秒读取一次进度快照，更新进度条、速度和状态；
6. 成功后回调 VersionBrowser.refresh_versions() 刷新版本页；
7. 完成提示可点击关闭弹窗。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import flet as ft

from java_runtime import (
    JavaRecommendation,
    component_for_major,
    fetch_java_recommendation,
    install_java_runtime,
    recommend_java_major,
    runtime_executable,
)
from minecraft_launcher_lib.install import install_minecraft_version
from minecraft_launcher_lib.mod_loader import get_mod_loader
from minecraft_launcher_lib.utils import is_version_valid
from ui_helpers import format_bytes, format_release_date, format_speed, same_directory
from ui_theme import (
    BG,
    BORDER,
    BORDER_COLOR,
    BUTTON_LABEL_FIELD,
    CARD,
    ERROR,
    FAINT,
    MUTED,
    OLD,
    OLD_BG,
    PADDING,
    PRIMARY,
    PRIMARY_SOFT,
    SURFACE,
    TEXT,
    TEXT_BUTTON_LABEL_FIELD,
    TYPE_STYLES,
)
from version_downloader import VanillaVersion, VersionDownloadTask, fetch_vanilla_versions
from version_scanner import version_type_label

MAX_VISIBLE_VERSIONS = 80
POLL_INTERVAL = 0.4


class DownloadDialog:
    """可搜索的原版版本选择 + 下载进度弹窗。"""

    def __init__(
        self,
        page: ft.Page,
        minecraft_directory: str,
        on_downloaded,
        on_switch_directory=None,
    ) -> None:
        self.page = page
        self.minecraft_directory = str(minecraft_directory)
        self.initial_minecraft_directory = str(minecraft_directory)
        self.on_downloaded = on_downloaded
        self.on_switch_directory = on_switch_directory

        self.versions: list[VanillaVersion] = []
        self.selected: VanillaVersion | None = None
        self.downloading = False
        self.task: VersionDownloadTask | None = None
        self.install_kind = "version"
        self.install_label = ""
        self.mode = "vanilla"
        self.mode_buttons: dict[str, ft.Container] = {}
        self.recommendation: JavaRecommendation | None = None
        self._recommendation_token = 0
        self._loader_token = 0
        self._meta_version_id = ""
        self.loader_error = ""
        self._closed = False
        self._row_by_id: dict[str, ft.Container] = {}
        self.dir_picker = ft.FilePicker(on_result=self._on_target_dir_picked)

        self._build()

    @property
    def is_open(self) -> bool:
        return bool(self.dialog.open) and not self._closed

    # ---- 构建界面 --------------------------------------------------------
    def _build(self) -> None:
        self.close_button = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            icon_color=MUTED,
            tooltip="关闭",
            on_click=self._close,
        )

        brand = ft.Row(
            controls=[
                ft.Container(
                    width=38,
                    height=38,
                    border_radius=10,
                    bgcolor=PRIMARY_SOFT,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(
                        ft.Icons.CLOUD_DOWNLOAD_OUTLINED,
                        color=PRIMARY,
                        size=20,
                    ),
                ),
                ft.Column(
                    controls=[
                        ft.Text(
                            "下载游戏版本",
                            size=18,
                            color=TEXT,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Text(
                            "原版 / Fabric / Forge，可下载配套 Java 运行时",
                            size=10,
                            color=MUTED,
                        ),
                    ],
                    spacing=1,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        title = ft.Row(
            controls=[brand, self.close_button],
            width=720,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.loading = ft.Column(
            controls=[
                ft.ProgressRing(width=24, height=24, stroke_width=3, color=PRIMARY),
                ft.Text("正在获取版本列表…", size=11, color=MUTED),
            ],
            spacing=10,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.load_error_text = ft.Text(
            "",
            size=11,
            color=ERROR,
            text_align=ft.TextAlign.CENTER,
        )
        self.load_error = ft.Column(
            controls=[
                ft.Icon(ft.Icons.ERROR_OUTLINE, size=28, color=ERROR),
                self.load_error_text,
                ft.TextButton(
                    **{TEXT_BUTTON_LABEL_FIELD: "重新获取"},
                    on_click=self._on_retry_load,
                ),
            ],
            visible=False,
            spacing=8,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.search_field = ft.TextField(
            width=210,
            height=36,
            dense=True,
            filled=True,
            bgcolor=CARD,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=8),
            prefix_icon=ft.Icons.SEARCH,
            hint_text="搜索版本号",
            text_size=11,
            on_change=self._apply_filter,
        )
        self.type_dropdown = ft.Dropdown(
            width=108,
            dense=True,
            filled=True,
            bgcolor=CARD,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=8, vertical=6),
            text_size=11,
            value="release",
            options=[
                ft.dropdown.Option("release", "正式版"),
                ft.dropdown.Option("snapshot", "快照"),
                ft.dropdown.Option("all", "全部"),
            ],
            on_change=self._apply_filter,
        )

        self.version_count_text = ft.Text("", size=10, color=FAINT)
        self.version_list = ft.ListView(
            width=324,
            height=220,
            spacing=4,
            padding=0,
            auto_scroll=False,
            build_controls_on_demand=True,
        )

        left_panel = ft.Container(
            width=360,
            height=310,
            bgcolor=SURFACE,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=10,
            padding=10,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[self.search_field, self.type_dropdown],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.version_count_text,
                    self.version_list,
                ],
                spacing=6,
                tight=True,
            ),
        )

        self.selected_title = ft.Text(
            "尚未选择",
            size=16,
            color=TEXT,
            weight=ft.FontWeight.W_600,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            width=280,
        )
        self.selected_meta = ft.Row(controls=[], spacing=6)
        self.target_path = ft.Text(
            self.minecraft_directory,
            size=9,
            color=MUTED,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
            width=234,
        )
        self.target_pick_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            icon_size=16,
            icon_color=PRIMARY,
            tooltip="选择下载目录",
            width=28,
            height=28,
            on_click=self._pick_target_directory,
        )

        self.percent_text = ft.Text(
            "0%",
            size=20,
            color=PRIMARY,
            weight=ft.FontWeight.W_700,
        )
        self.speed_text = ft.Text("", size=9, color=PRIMARY)
        self.progress_bar = ft.ProgressBar(
            value=0,
            height=6,
            color=PRIMARY,
            bgcolor=PRIMARY_SOFT,
            border_radius=3,
        )
        self.status_text = ft.Text(
            "选择版本后开始下载",
            size=10,
            color=MUTED,
            max_lines=2,
            width=280,
        )
        self.size_text = ft.Text("", size=9, color=FAINT)
        self.error_text = ft.Text(
            "",
            size=9,
            color=ERROR,
            max_lines=2,
            visible=False,
            width=280,
        )
        self.progress_section = ft.Column(
            controls=[
                ft.Row(
                    controls=[self.percent_text, self.speed_text],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                self.progress_bar,
                self.status_text,
                self.size_text,
                self.error_text,
            ],
            visible=False,
            spacing=3,
            tight=True,
        )

        self.download_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "开始下载"},
            icon=ft.Icons.DOWNLOAD_OUTLINED,
            width=280,
            height=40,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            disabled=True,
            on_click=self._start_download,
        )

        self.loader_label = ft.Text("Fabric 版本", size=9, color=FAINT)
        self.loader_dropdown = ft.Dropdown(
            width=280,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=8, vertical=5),
            text_size=10,
            disabled=True,
            options=[],
        )
        self.loader_status = ft.Text("选择版本后加载加载器版本", size=9, color=FAINT)
        self.loader_box = ft.Container(
            visible=False,
            content=ft.Column(
                controls=[
                    self.loader_label,
                    self.loader_dropdown,
                    self.loader_status,
                ],
                spacing=3,
                tight=True,
            ),
        )

        self.java_title = ft.Text("推荐 Java：等待选择", size=10, color=TEXT)
        self.java_detail = ft.Text(
            "选择版本后自动读取 Mojang 版本信息",
            size=8,
            color=FAINT,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
            width=180,
        )
        self.java_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "下载 Java"},
            icon=ft.Icons.COFFEE,
            disabled=True,
            on_click=self._start_java_download,
        )
        self.java_box = ft.Container(
            width=280,
            bgcolor=SURFACE,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=8,
            padding=PADDING.symmetric(horizontal=8, vertical=6),
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.COFFEE, size=16, color=PRIMARY),
                    ft.Column(
                        controls=[self.java_title, self.java_detail],
                        spacing=1,
                        expand=True,
                    ),
                    self.java_button,
                ],
                spacing=5,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        self.completion_text = ft.Text(
            "下载完成，点击关闭",
            size=10,
            color=PRIMARY,
            weight=ft.FontWeight.W_600,
        )
        self.completion_hint = ft.Container(
            width=280,
            bgcolor=PRIMARY_SOFT,
            border=BORDER.all(1, PRIMARY),
            border_radius=8,
            padding=PADDING.symmetric(horizontal=9, vertical=7),
            ink=True,
            visible=False,
            on_click=self._close,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=16, color=PRIMARY),
                    self.completion_text,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        right_panel = ft.Container(
            width=330,
            height=310,
            bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=10,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text(
                                "已选择",
                                size=9,
                                color=FAINT,
                                style=ft.TextStyle(letter_spacing=0.8),
                            ),
                            self.selected_title,
                            self.selected_meta,
                            self.java_box,
                            ft.Divider(height=1, color=BORDER_COLOR),
                            ft.Text("安装到 .minecraft 目录", size=9, color=FAINT),
                            ft.Row(
                                controls=[self.target_path, self.target_pick_button],
                                spacing=4,
                                width=280,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Divider(height=1, color=BORDER_COLOR),
                            self.loader_box,
                        ],
                        spacing=5,
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                    ),
                    self.progress_section,
                    self.completion_hint,
                    self.download_button,
                ],
                spacing=6,
                expand=True,
            ),
        )

        self.body = ft.Row(
            controls=[left_panel, right_panel],
            spacing=14,
            visible=False,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        for mode, label, icon in (
            ("vanilla", "原版", ft.Icons.INVENTORY_2_OUTLINED),
            ("fabric", "Fabric", ft.Icons.EXTENSION_OUTLINED),
            ("forge", "Forge", ft.Icons.HANDYMAN_OUTLINED),
        ):
            self.mode_buttons[mode] = ft.Container(
                padding=PADDING.symmetric(horizontal=12, vertical=6),
                border_radius=18,
                bgcolor=PRIMARY_SOFT if mode == self.mode else CARD,
                ink=True,
                on_click=lambda _event, value=mode: self._set_mode(value),
                content=ft.Row(
                    controls=[
                        ft.Icon(icon, size=14, color=PRIMARY),
                        ft.Text(label, size=10, color=PRIMARY),
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )
        self.mode_row = ft.Row(
            controls=list(self.mode_buttons.values()),
            spacing=8,
            visible=False,
        )

        content_box = ft.Container(
            width=760,
            height=380,
            bgcolor=BG,
            padding=PADDING.symmetric(horizontal=16, vertical=10),
            content=ft.Column(
                controls=[self.loading, self.load_error, self.mode_row, self.body],
                expand=True,
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
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

    # ---- 下载类型（原版 / Fabric / Forge） -------------------------------
    def _mode_name(self, mode: str | None = None) -> str:
        return {
            "vanilla": "原版",
            "fabric": "Fabric",
            "forge": "Forge",
        }.get(mode or self.mode, "原版")

    def _set_mode(self, mode: str) -> None:
        if self.downloading or mode not in ("vanilla", "fabric", "forge"):
            return
        self.mode = mode
        for key, button in self.mode_buttons.items():
            button.bgcolor = PRIMARY_SOFT if key == mode else CARD
        self.loader_box.visible = mode != "vanilla"
        self.loader_label.value = f"{self._mode_name()} 版本"
        self.loader_error = ""
        self.loader_dropdown.options = []
        self.loader_dropdown.value = None
        self.loader_dropdown.disabled = True
        self.loader_status.value = "选择游戏版本后加载加载器版本"
        self.loader_status.color = FAINT
        self._meta_version_id = ""
        self.progress_section.visible = False
        self.error_text.visible = False
        self.completion_hint.visible = False
        self.status_text.value = "选择版本后开始下载"
        self.status_text.color = MUTED
        self._render_selected()
        self._on_selection_changed(force=True)
        self.page.update()

    def _on_selection_changed(self, force: bool = False) -> None:
        """选择版本/切换下载类型后，刷新 Java 推荐和加载器版本。"""

        if self.selected is None:
            return
        if not force and self._meta_version_id == self.selected.version_id:
            return
        self._meta_version_id = self.selected.version_id
        self.recommendation = None
        self.java_title.value = "推荐 Java：识别中…"
        self.java_detail.value = "正在读取 Mojang 版本信息"
        self.java_button.disabled = True
        self.java_button.text = "识别中…"
        self._recommendation_token += 1
        self.page.run_task(
            self._load_java_recommendation,
            self.selected,
            self._recommendation_token,
        )
        self._refresh_loader_versions()

    async def _load_java_recommendation(
        self,
        version: VanillaVersion,
        token: int,
    ) -> None:
        try:
            recommendation = await asyncio.to_thread(
                fetch_java_recommendation,
                version.version_id,
                version.url,
            )
        except Exception:
            return
        if self._closed or token != self._recommendation_token:
            return
        self.recommendation = recommendation
        self.java_title.value = f"推荐 {recommendation.title}"
        source = "官方版本 JSON" if recommendation.is_exact else "版本号兜底"
        self.java_detail.value = f"{recommendation.component} · {source}"
        await self._refresh_java_installed()

    async def _refresh_java_installed(self) -> None:
        if self.recommendation is None:
            return
        executable = await asyncio.to_thread(
            runtime_executable,
            self.recommendation.component,
            self.minecraft_directory,
        )
        if executable:
            self.java_title.value = f"{self.recommendation.title} · 已安装"
            self.java_detail.value = executable
            self.java_button.text = "已安装"
            self.java_button.disabled = True
        else:
            self.java_button.text = f"下载 {self.recommendation.title}"
            self.java_button.disabled = self.downloading
        self.page.update()

    def _refresh_loader_versions(self) -> None:
        if self.selected is None:
            return
        self._loader_token += 1
        token = self._loader_token
        if self.mode == "vanilla":
            return
        self.loader_box.visible = True
        self.loader_dropdown.options = []
        self.loader_dropdown.value = None
        self.loader_dropdown.disabled = True
        self.loader_status.value = f"正在获取 {self._mode_name()} 版本列表…"
        self.loader_status.color = MUTED
        self.page.run_task(
            self._load_loader_versions,
            self.mode,
            self.selected.version_id,
            token,
        )

    async def _load_loader_versions(
        self,
        mode: str,
        minecraft_version: str,
        token: int,
    ) -> None:
        try:
            loader = get_mod_loader(mode)
            supported = await asyncio.to_thread(
                loader.is_minecraft_version_supported,
                minecraft_version,
            )
            if not supported:
                raise ValueError(
                    f"该版本不支持 {self._mode_name(mode)}"
                )
            versions = await asyncio.to_thread(
                loader.get_loader_versions,
                minecraft_version,
                True,
            )
        except Exception as exc:
            if self._closed or token != self._loader_token:
                return
            self.loader_error = str(exc)
            self.loader_status.value = f"加载器版本获取失败：{exc}"
            self.loader_status.color = ERROR
            self._render_selected()
            self.page.update()
            return

        if self._closed or token != self._loader_token:
            return
        self.loader_error = ""
        options = []
        if versions:
            options.append(
                ft.dropdown.Option("latest", f"最新版本（{versions[0]}）")
            )
            options.extend(
                ft.dropdown.Option(version, version)
                for version in versions[:30]
            )
        else:
            options.append(ft.dropdown.Option("latest", "最新版本"))
        self.loader_dropdown.options = options
        self.loader_dropdown.value = "latest"
        self.loader_dropdown.disabled = False
        self.loader_status.value = f"共 {len(versions)} 个可用版本"
        self.loader_status.color = FAINT
        self._render_selected()
        self.page.update()

    # ---- 打开与版本加载 --------------------------------------------------
    def open(self) -> None:
        self.page.overlay.append(self.dir_picker)
        self.page.open(self.dialog)
        self.page.update()
        self.page.run_task(self._load_versions)

    async def _load_versions(self) -> None:
        if self._closed:
            return

        self.loading.visible = True
        self.load_error.visible = False
        self.body.visible = False
        self.page.update()

        try:
            versions = await asyncio.to_thread(fetch_vanilla_versions)
        except Exception as exc:
            if self._closed:
                return
            self.loading.visible = False
            self.load_error.visible = True
            self.load_error_text.value = f"获取版本列表失败：{exc}"
            self.page.update()
            return

        if self._closed:
            return

        self.versions = versions
        self.loading.visible = False
        self.mode_row.visible = True
        self.body.visible = True
        self._apply_filter(select_first=True)
        self.page.update()

    def _on_retry_load(self, _event=None) -> None:
        if self._closed:
            return
        self.page.run_task(self._load_versions)

    # ---- 筛选与选择 ------------------------------------------------------
    def _apply_filter(self, _event=None, *, select_first: bool = False) -> None:
        if self._closed:
            return

        query = (self.search_field.value or "").strip().lower()
        version_type = self.type_dropdown.value or "all"

        filtered = [
            version
            for version in self.versions
            if (not query or query in version.version_id.lower())
            and (version_type == "all" or version.version_type == version_type)
        ]

        # 当前选择被筛掉时，自动选择结果中的第一个版本，减少空状态。
        if self.selected not in filtered:
            self.selected = filtered[0] if filtered else None
        elif select_first and filtered:
            self.selected = filtered[0]

        self.version_list.controls.clear()
        self._row_by_id.clear()

        for version in filtered[:MAX_VISIBLE_VERSIONS]:
            row = self._build_version_row(version)
            self._row_by_id[version.version_id] = row
            self.version_list.controls.append(row)

        if not filtered:
            self.version_list.controls.append(
                ft.Container(
                    padding=PADDING.symmetric(vertical=24),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text("没有匹配的版本", size=11, color=FAINT),
                )
            )

        if len(filtered) > MAX_VISIBLE_VERSIONS:
            self.version_count_text.value = (
                f"共 {len(filtered)} 个，显示前 {MAX_VISIBLE_VERSIONS} 个"
            )
        else:
            self.version_count_text.value = f"共 {len(filtered)} 个版本"

        # 搜索/切换类型后，收起上一次下载的进度和提示。
        if not self.downloading:
            self.progress_section.visible = False
            self.error_text.visible = False
            self.completion_hint.visible = False
            self.status_text.value = "选择版本后开始下载"
            self.status_text.color = MUTED
            self.download_button.on_click = self._start_download
            self._set_download_button(
                "开始下载",
                disabled=self.selected is None,
            )

        self._render_selected()
        self._on_selection_changed()
        self.page.update()
        self.version_list.scroll_to(offset=0)

    def _build_version_row(self, version: VanillaVersion) -> ft.Container:
        selected = self.selected is not None and version.version_id == self.selected.version_id
        color, bgcolor, _icon = _type_style(version.version_type)

        return ft.Container(
            key=version.version_id,
            width=324,
            padding=PADDING.symmetric(horizontal=10, vertical=8),
            border=BORDER.all(1, PRIMARY if selected else BORDER_COLOR),
            border_radius=8,
            bgcolor=PRIMARY_SOFT if selected else CARD,
            ink=True,
            on_click=lambda _event, current=version: self._select_version(current),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                version.version_id,
                                size=12,
                                color=TEXT,
                                weight=ft.FontWeight.W_600,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=202,
                            ),
                            _type_badge(version.version_type, compact=True),
                        ],
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(
                        format_release_date(version.release_time),
                        size=9,
                        color=MUTED,
                    ),
                ],
                spacing=2,
                tight=True,
            ),
        )

    def _select_version(self, version: VanillaVersion) -> None:
        if self.downloading:
            return

        self.selected = version
        for version_id, row in self._row_by_id.items():
            is_selected = version_id == version.version_id
            row.bgcolor = PRIMARY_SOFT if is_selected else CARD
            row.border = BORDER.all(1, PRIMARY if is_selected else BORDER_COLOR)

        # 选择新版本时，把上一次下载的进度/错误收起。
        self.progress_section.visible = False
        self.error_text.visible = False
        self.completion_hint.visible = False
        self.status_text.value = "选择版本后开始下载"
        self.status_text.color = MUTED
        self.download_button.on_click = self._start_download
        self._set_download_button(
            "开始下载" if self.mode == "vanilla" else f"安装 {self._mode_name()}",
            disabled=False,
        )
        self._render_selected()
        self._on_selection_changed(force=True)
        self.page.update()
        try:
            self.version_list.scroll_to(key=version.version_id, duration=180)
        except Exception:
            pass

    def _render_selected(self) -> None:
        if self.selected is None:
            self.selected_title.value = "尚未选择"
            self.selected_meta.controls = []
            self.download_button.disabled = True
            self.page.update()
            return

        self.selected_title.value = self.selected.version_id
        self.selected_meta.controls = [
            _type_badge(self.selected.version_type),
            ft.Text(self._mode_name(), size=10, color=PRIMARY),
            ft.Text(
                format_release_date(self.selected.release_time),
                size=10,
                color=MUTED,
            ),
        ]
        if self.downloading:
            self.download_button.disabled = True
            return
        if self.mode == "vanilla":
            self.download_button.disabled = False
            self.download_button.on_click = self._start_download
            self._set_download_button("开始下载", disabled=False)
        else:
            self.download_button.disabled = bool(self.loader_error) or self.loader_dropdown.disabled
            self.download_button.on_click = self._start_download
            self._set_download_button(
                f"安装 {self._mode_name()}",
                disabled=self.download_button.disabled,
            )

    # ---- 下载目录选择 ----------------------------------------------------
    def _pick_target_directory(self, _event=None) -> None:
        if self.downloading:
            return

        current = Path(self.minecraft_directory).expanduser()
        initial = current.parent if current.parent.exists() else Path.home()
        self.dir_picker.get_directory_path(
            dialog_title="选择下载目录（.minecraft）",
            initial_directory=str(initial),
        )

    def _on_target_dir_picked(self, event) -> None:
        path = (event.path or "").strip()
        if not path or self.downloading:
            return

        self.minecraft_directory = path
        self.target_path.value = path
        self.progress_section.visible = False
        self.error_text.visible = False
        self.completion_hint.visible = False
        self.status_text.value = "下载目录已更新，选择版本后开始下载"
        self.status_text.color = MUTED
        self.download_button.on_click = self._start_download
        self._set_download_button(
            "开始下载" if self.mode == "vanilla" else f"安装 {self._mode_name()}",
            disabled=self.selected is None,
        )
        if self.recommendation is not None:
            self.page.run_task(self._refresh_java_installed)
        self.page.update()

    def _switch_to_target(self, _event=None) -> None:
        """下载完成后，把主版本页切换到自定义下载目录。"""

        if self.on_switch_directory is None or self.downloading:
            return
        self.on_switch_directory(self.minecraft_directory)
        self._close()

    # ---- 下载与进度 ------------------------------------------------------
    def _begin_task(
        self,
        task: VersionDownloadTask,
        kind: str,
        label: str,
    ) -> None:
        self.downloading = True
        self.install_kind = kind
        self.install_label = label
        self.error_text.visible = False
        self.progress_section.visible = True
        self.completion_hint.visible = False
        self.progress_bar.value = 0
        self.progress_bar.color = PRIMARY
        self.percent_text.value = "0%"
        self.percent_text.color = PRIMARY
        self.speed_text.value = ""
        self.status_text.value = "准备下载…"
        self.status_text.color = MUTED
        self.size_text.value = ""
        self.close_button.disabled = True
        self.search_field.disabled = True
        self.type_dropdown.disabled = True
        self.target_pick_button.disabled = True
        self.loader_dropdown.disabled = True
        self.java_button.disabled = True
        self._set_download_button("下载中…", disabled=True)

        self.task = task
        self.task.start()
        self.page.update()
        self.page.run_task(self._poll_download)

    def _start_java_download(self, _event=None) -> None:
        if self.downloading:
            return
        recommendation = self.recommendation
        if recommendation is None:
            return
        component = recommendation.component
        task = VersionDownloadTask(
            component,
            self.minecraft_directory,
            installer=lambda _version, directory, callback: install_java_runtime(
                component,
                directory,
                callback=callback,
            ),
            progress_span=(0.0, 100.0),
        )
        self._begin_task(task, "java", f"Java {recommendation.major}")

    def _start_download(self, _event=None) -> None:
        if self.downloading or self.selected is None:
            return

        if self.mode == "vanilla":
            task = VersionDownloadTask(
                self.selected.version_id,
                self.minecraft_directory,
            )
            self._begin_task(task, "version", self.selected.version_id)
            return

        if self.loader_error or self.loader_dropdown.disabled:
            self.error_text.value = self.loader_error or "加载器版本尚未准备好"
            self.error_text.visible = True
            self.status_text.value = "无法安装加载器"
            self.status_text.color = ERROR
            self.page.update()
            return

        mode = self.mode
        mode_name = self._mode_name()
        minecraft_version = self.selected.version_id
        recommendation = self.recommendation
        if recommendation is None:
            major = recommend_java_major(minecraft_version)
            recommendation = JavaRecommendation(
                major=major,
                component=component_for_major(major),
                source="fallback",
            )
        component = recommendation.component
        java_major = recommendation.major
        loader_version = (self.loader_dropdown.value or "").strip() or None
        if loader_version == "latest":
            loader_version = None
        loader = get_mod_loader(mode)

        def loader_installer(_version, directory, callback):
            # 先确保 Mojang 运行时存在；Fabric/Forge 安装器本身也需要 Java。
            executable = runtime_executable(component, directory)
            if not executable:
                callback["setStatus"](f"安装 Java {java_major}")
                install_java_runtime(
                    component,
                    directory,
                    callback=callback,
                )
                executable = runtime_executable(component, directory)
            # ModLoader.install 要求原版版本已经存在；空目录先补装原版。
            if not is_version_valid(minecraft_version, directory):
                callback["setStatus"](f"下载 {minecraft_version} 原版文件")
                install_minecraft_version(
                    minecraft_version,
                    directory,
                    callback=callback,
                )
            callback["setStatus"](f"安装 {mode_name}")
            return loader.install(
                minecraft_version,
                directory,
                loader_version=loader_version,
                callback=callback,
                java=executable,
            )

        task = VersionDownloadTask(
            minecraft_version,
            self.minecraft_directory,
            installer=loader_installer,
        )
        self._begin_task(task, "loader", f"{mode_name} · {minecraft_version}")

    async def _poll_download(self) -> None:
        if self.task is None:
            return

        last_time = time.monotonic()
        last_bytes = 0
        smoothed_speed = 0.0

        while True:
            snapshot = self.task.snapshot()
            now = time.monotonic()
            elapsed = now - last_time

            if elapsed >= POLL_INTERVAL:
                instant_speed = max(
                    (snapshot.bytes_received - last_bytes) / max(elapsed, 0.001),
                    0.0,
                )
                smoothed_speed = (
                    instant_speed
                    if smoothed_speed <= 0
                    else smoothed_speed * 0.65 + instant_speed * 0.35
                )
                self._render_progress(snapshot, smoothed_speed)
                self.page.update()
                last_time = now
                last_bytes = snapshot.bytes_received

            if snapshot.done:
                break
            await asyncio.sleep(0.12)

        final = self.task.snapshot()
        self._finish_download(final)

    def _render_progress(self, snapshot, speed: float) -> None:
        percent = min(max(snapshot.percent, 0.0), 100.0)
        self.percent_text.value = f"{percent:.0f}%"
        self.progress_bar.value = percent / 100
        self.status_text.value = snapshot.status
        self.speed_text.value = (
            f"速度 {format_speed(speed)}" if speed > 0 else "速度计算中…"
        )
        self.size_text.value = (
            f"已接收 {format_bytes(snapshot.bytes_received)}"
            if snapshot.bytes_received > 0
            else ""
        )

    def _finish_download(self, snapshot) -> None:
        self.downloading = False
        self.close_button.disabled = False
        self.search_field.disabled = False
        self.type_dropdown.disabled = False
        self.target_pick_button.disabled = False
        self.completion_hint.visible = False

        if snapshot.success:
            self.percent_text.value = "100%"
            self.percent_text.color = PRIMARY
            self.progress_bar.value = 1
            self.progress_bar.color = PRIMARY
            self.speed_text.value = f"耗时 {int(snapshot.elapsed)} 秒"
            self.size_text.value = f"共接收 {format_bytes(snapshot.bytes_received)}"
            self.error_text.visible = False

            if self.install_kind == "java":
                self.status_text.value = "Java 运行时下载完成，可以继续下载游戏版本"
                self.status_text.color = PRIMARY
                self.completion_text.value = "Java 下载完成，点击关闭窗口"
                self.completion_hint.visible = True
                self.download_button.on_click = self._close
                self._set_download_button("完成并关闭", disabled=False)
                if self.mode != "vanilla" and self.loader_dropdown.options:
                    self.loader_dropdown.disabled = False
                self.page.run_task(self._refresh_java_installed)
                self.page.update()
                return

            try:
                self.on_downloaded(self.minecraft_directory)
            except Exception:
                pass

            if self.install_kind == "loader":
                action = f"{self._mode_name()} 安装完成"
            else:
                action = "下载完成"
            self.status_text.value = f"{action}，本地版本列表已刷新"
            self.status_text.color = PRIMARY
            self.completion_text.value = f"{action}，点击关闭窗口"
            self.completion_hint.visible = True
            self.page.run_task(self._refresh_java_installed)

            if same_directory(
                self.minecraft_directory,
                self.initial_minecraft_directory,
            ):
                self.download_button.on_click = self._close
                self._set_download_button("完成并关闭", disabled=False)
            else:
                self.status_text.value = f"{action}，已保存到自定义目录"
                if self.on_switch_directory is not None:
                    self.download_button.on_click = self._switch_to_target
                    self._set_download_button("切换并查看", disabled=False)
                else:
                    self.download_button.on_click = self._close
                    self._set_download_button("完成并关闭", disabled=False)
        else:
            self.status_text.value = "下载失败"
            self.status_text.color = ERROR
            self.progress_bar.color = ERROR
            self.percent_text.color = ERROR
            self.error_text.value = snapshot.error or "未知错误"
            self.error_text.visible = True
            self.speed_text.value = ""
            if self.install_kind == "java":
                self.download_button.on_click = self._start_java_download
            else:
                self.download_button.on_click = self._start_download
            self._set_download_button("重试", disabled=False)
            if self.recommendation is not None:
                self.page.run_task(self._refresh_java_installed)

        if self.mode != "vanilla" and self.loader_dropdown.options:
            self.loader_dropdown.disabled = False
        self.page.update()

    # ---- 关闭 ------------------------------------------------------------
    def _on_dismiss(self, _event=None) -> None:
        """点击遮罩或按 Esc 时，不在下载过程中把弹窗标记为已关闭。"""

        if not self.downloading:
            self._closed = True
        self._remove_dir_picker()

    def _close(self, _event=None) -> None:
        if self.downloading:
            return
        self._closed = True
        self._remove_dir_picker()
        self.page.close(self.dialog)
        self.page.update()

    def _remove_dir_picker(self) -> None:
        try:
            self.page.overlay.remove(self.dir_picker)
        except ValueError:
            pass

    def _set_download_button(self, text: str, *, disabled: bool) -> None:
        setattr(self.download_button, BUTTON_LABEL_FIELD, text)
        self.download_button.disabled = disabled


def _type_style(version_type: str):
    return TYPE_STYLES.get(version_type, (OLD, OLD_BG, ft.Icons.INVENTORY_2_OUTLINED))


def _type_badge(version_type: str, *, compact: bool = False) -> ft.Container:
    color, bgcolor, _icon = _type_style(version_type)
    return ft.Container(
        padding=PADDING.symmetric(horizontal=6 if compact else 8, vertical=2 if compact else 3),
        border_radius=6,
        bgcolor=bgcolor,
        content=ft.Row(
            controls=[
                ft.Container(width=4, height=4, border_radius=2, bgcolor=color),
                ft.Text(
                    version_type_label(version_type),
                    size=9 if compact else 10,
                    color=color,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

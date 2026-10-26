"""NLCL 入口：本地 Minecraft 版本扫描与展示（第一阶段模块 1）。

运行：
    .venv\\Scripts\\python.exe main.py

本文件只负责界面和展示。版本扫描逻辑在 version_scanner.py 中，
本次 UI 优化没有修改扫描核心。
"""

from __future__ import annotations

import asyncio
import ctypes
from pathlib import Path

import flet as ft

from app_settings import AppSettingsStore
from download_throttle import set_download_limit
from download_ui import DownloadDialog
from drop_support import WindowsFileDrop
from import_ui import ImportDialog
from account_manager import AccountStore
from account_ui import AccountDialog, account_avatar
from launch_settings import LaunchSettingsStore
from launch_controller import GameLauncherController
from launch_console_ui import LaunchConsoleView
from lan_scan_ui import LanScanView
from multiplayer_ui import MultiplayerView
from settings_ui import SettingsView
from skin_manager import get_skin_manager
from skin_ui import SkinManagerDialog
from snapshot_ui import SnapshotView
from theme_manager import ThemeStore, apply_theme, theme_mode
from ui_helpers import format_release_date, same_directory
from version_details_ui import VersionDetailsDialog
from ui_theme import (
    AMBER,
    AMBER_BG,
    AMBER_BORDER,
    BG,
    BORDER,
    BORDER_COLOR,
    BUTTON_LABEL_FIELD,
    CARD,
    FAINT,
    MUTED,
    OLD,
    OLD_BG,
    PADDING,
    PRIMARY,
    PRIMARY_SOFT,
    SIDEBAR_ACTIVE,
    SIDEBAR_BG,
    SIDEBAR_MUTED,
    SIDEBAR_TEXT,
    SURFACE,
    TEXT,
    TEXT_BUTTON_LABEL_FIELD,
    TYPE_STYLES,
)
from version_scanner import (
    LocalVersion,
    ScanIssue,
    ScanResult,
    default_minecraft_dir,
    scan_local_versions,
    version_type_label,
)

# Flet 0.28 在部分窗口/DPI 环境下会把 expand 的宽度算到窗口外。
# 主内容使用固定宽度：左侧 204 侧栏 + 18 间距 + 758 内容区。
SIDEBAR_WIDTH = 204
# 基准设计尺寸（逻辑像素）：所有页面都按这个尺寸布局，再整体缩放。
BASE_UI_WIDTH = 950
BASE_UI_HEIGHT = 500
MAX_UI_SCALE = 3.0
MIN_UI_SCALE = 0.35
# 用户指定的最小窗口尺寸（Flet window.min_width / min_height）。
MIN_WINDOW_WIDTH = 950
MIN_WINDOW_HEIGHT = 500
# Flet 窗口外框与客户区之间的近似差值。
WINDOW_CHROME_X = 15
WINDOW_CHROME_Y = 38
MAIN_WIDTH = 758
ROOT_WIDTH = SIDEBAR_WIDTH + 18 + MAIN_WIDTH
CONTENT_WIDTH = MAIN_WIDTH


class VersionBrowser:
    """负责页面布局、扫描按钮和版本列表刷新。"""

    def __init__(self, page: ft.Page) -> None:
        self.page = page

        self.path_field: ft.TextField
        self.scan_button: ft.FilledButton
        self.summary_row: ft.Row
        self.issues_panel: ft.Container
        self.issues_column: ft.Column
        self.version_list: ft.ListView
        self._download_dialog: DownloadDialog | None = None
        self._import_dialog: ImportDialog | None = None
        self._details_dialog: VersionDetailsDialog | None = None
        self.account_store = AccountStore()
        self._account_dialog: AccountDialog | None = None
        self._skin_dialog: SkinManagerDialog | None = None
        self.launch_settings_store = LaunchSettingsStore()
        self.app_settings_store = AppSettingsStore()
        set_download_limit(self.app_settings_store.settings.download_limit_kbps)
        self.theme_store = ThemeStore()
        apply_theme(self.theme_store.name)
        self._game_dir = (
            self.app_settings_store.settings.download_directory
            or str(default_minecraft_dir())
        )
        self.launch_controller = GameLauncherController(
            self.page,
            self.account_store,
            self.launch_settings_store,
            on_account_changed=self._on_account_changed,
        )
        self.launch_view: LaunchConsoleView | None = None
        self.multiplayer_view: MultiplayerView | None = None
        self.lan_scan_view: LanScanView | None = None
        self.snapshot_view: SnapshotView | None = None
        self.settings_view: SettingsView | None = None
        self.version_page: ft.Container
        self.main_slot: ft.Container
        self.account_card: ft.Container
        self.current_scan_result: ScanResult | None = None
        self.current_view = "versions"
        self.root_height: float = 680
        self._skin_prefetching = False

    # ---- 页面骨架 --------------------------------------------------------
    def mount(self) -> None:
        """构建页面，并执行第一次扫描。"""

        self._configure_page()

        self.dir_picker = ft.FilePicker(on_result=self._on_main_dir_picked)
        self.page.overlay.append(self.dir_picker)
        self.import_picker = ft.FilePicker(on_result=self._on_import_files_picked)
        self.page.overlay.append(self.import_picker)

        self.path_field = ft.TextField(
            value=self._game_dir,
            hint_text=r"例如 C:\Users\你的用户名\AppData\Roaming\.minecraft",
            expand=True,
            height=46,
            dense=True,
            filled=True,
            bgcolor=SURFACE,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=10,
            content_padding=PADDING.symmetric(horizontal=12, vertical=10),
            text_size=13,
            suffix=ft.IconButton(
                icon=ft.Icons.FOLDER_OPEN,
                icon_size=18,
                icon_color=MUTED,
                tooltip="选择游戏目录",
                width=32,
                height=32,
                on_click=self._pick_main_directory,
            ),
            on_submit=self.refresh_versions,
        )
        self.scan_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "扫描版本"},
            icon=ft.Icons.REFRESH,
            width=120,
            height=46,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            on_click=self.refresh_versions,
        )

        self.summary_row = ft.Row(
            controls=[],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.issues_column = ft.Column(spacing=3, tight=True, expand=True)
        self.issues_panel = ft.Container(
            visible=False,
            bgcolor=AMBER_BG,
            border=BORDER.all(1, AMBER_BORDER),
            padding=PADDING.symmetric(horizontal=12, vertical=10),
            border_radius=10,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=AMBER, size=18),
                    self.issues_column,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )
        self.version_list = ft.ListView(
            expand=True,
            spacing=8,
            padding=0,
        )

        # 页面本身不再随窗口拉伸，而是在固定的基准画布上布局；
        # 窗口尺寸变化只改变 root_container 的整体 scale。
        self.root_height = BASE_UI_HEIGHT
        sidebar = self._build_sidebar(BASE_UI_HEIGHT)
        self.version_page = self._build_main_area(None)
        self.main_slot = ft.Container(
            expand=True,
            content=self.version_page,
        )
        main_column = ft.Column(
            controls=[self.main_slot],
            spacing=0,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        initial_scale = self._calculate_ui_scale(
            self.page.width or 1280,
            self.page.height or 760,
        )
        self._ui_scale_value = initial_scale
        self._scale_factors: dict[int, float] = {}
        self._view_roots: dict[int, ft.Control] = {}
        initial_w, initial_h = self._logical_size(
            self.page.width or 1280,
            self.page.height or 760,
        )

        # 基准画布上的组件全部按初始 scale 重新计算尺寸；不再使用视觉 transform，
        # 因此点击命中区域与放大后的界面完全一致。
        self._attach_view(self.version_page)

        root_row = ft.Row(
            controls=[sidebar, main_column],
            spacing=16,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.root_container = ft.Container(
            width=initial_w,
            height=initial_h,
            padding=PADDING.symmetric(
                horizontal=12 * initial_scale,
                vertical=10 * initial_scale,
            ),
            bgcolor=BG,
            clip_behavior=ft.ClipBehavior.NONE,
            content=root_row,
        )
        self.page.add(self.root_container)
        self._install_dialog_scaler()
        self._scale_control_tree(
            root_row,
            initial_scale,
            skip_ids=set(self._view_roots),
        )
        self.page.on_resized = self._on_page_resized
        # 启动时窗口可能先以系统恢复尺寸出现，延迟校准整体缩放比例。
        self.page.run_task(self._sync_ui_scale_async)
        self._set_active_nav("versions")
        self._start_file_drop()
        self._schedule_skin_prefetch()
        self.refresh_versions()

    def _logical_size(self, width: float, height: float) -> tuple[float, float]:
        """把 Flet 物理像素客户区换算成逻辑尺寸。"""

        scale = _ui_scale()
        return width / scale, height / scale

    def _calculate_ui_scale(self, width: float, height: float) -> float:
        """根据客户区逻辑尺寸计算统一缩放比例。"""

        if width <= 0 or height <= 0:
            return 1.0
        scale_factor = _ui_scale()
        logical_width = width / scale_factor
        logical_height = height / scale_factor
        scale = min(
            logical_width / BASE_UI_WIDTH,
            logical_height / BASE_UI_HEIGHT,
        )
        # 窗口可以被缩到 950×500，因此允许低于 1.0 的缩放；
        # 下限用于防止极端 DPI 下无限缩小，上限用于限制超大缩放。
        return max(MIN_UI_SCALE, min(scale, MAX_UI_SCALE))

    def _install_dialog_scaler(self) -> None:
        """让账号/皮肤/下载等弹窗也继承当前全局比例。"""

        if getattr(self, "_dialog_scaler_installed", False):
            return
        try:
            original_open = self.page.open

            def open_scaled(control):
                try:
                    self._scale_control_tree(
                        control,
                        getattr(self, "_ui_scale_value", 1.0),
                    )
                except Exception:
                    pass
                return original_open(control)

            self.page.open = open_scaled
            self._dialog_scaler_installed = True
        except Exception:
            # 不同 Flet 版本对 Page.open 的可写性不一致；失败时不影响主界面。
            pass

    def _register_view(self, view) -> None:
        if view is not None:
            self._view_roots[id(view)] = view

    def _attach_view(self, view) -> None:
        """把新页面挂到主区域，并按当前全局比例缩放。"""

        if view is None:
            return
        self._register_view(view)
        self._scale_control_tree(view, self._ui_scale_value)
        self.main_slot.content = view

    def _apply_ui_scale(self, width: float, height: float) -> None:
        scale = self._calculate_ui_scale(width, height)
        root = getattr(self, "root_container", None)
        if root is None:
            return
        current = getattr(self, "_ui_scale_value", 1.0)
        logical_w, logical_h = self._logical_size(width, height)
        if (
            abs(current - scale) < 0.001
            and abs(float(root.width or 0) - logical_w) < 0.5
            and abs(float(root.height or 0) - logical_h) < 0.5
        ):
            return
        self._ui_scale_value = scale
        # 根容器本身固定为实际客户区，保证鼠标命中和窗口覆盖；
        # 只缩放根内容（侧栏/间距）以及各个页面。
        root.width = logical_w
        root.height = logical_h
        root.padding = PADDING.symmetric(
            horizontal=12 * scale,
            vertical=10 * scale,
        )
        if getattr(root, "content", None) is not None:
            self._scale_control_tree(
                root.content,
                scale,
                skip_ids=set(self._view_roots),
            )
        for view in list(self._view_roots.values()):
            self._scale_control_tree(view, scale)
        try:
            self.page.update()
        except Exception:
            pass

    # ---- 全局尺寸缩放 ----------------------------------------------------
    _SCALE_ATTRS = (
        "width",
        "height",
        "left",
        "top",
        "right",
        "bottom",
        "min_width",
        "max_width",
        "min_height",
        "max_height",
        "size",
        "text_size",
        "icon_size",
        "spacing",
        "run_spacing",
        "content_padding",
        "padding",
        "margin",
        "border_radius",
        "stroke_width",
        "thickness",
    )

    def _scale_control_tree(
        self,
        root,
        target_scale: float,
        skip_ids: set[int] | None = None,
    ) -> None:
        """按目标比例缩放控件树的实际布局尺寸，而不是视觉 transform。

        这样鼠标命中区域、文字、输入框和按钮全部与放大后的界面一致。
        """

        if root is None:
            return
        old = self._scale_factors.get(id(root), 1.0)
        ratio = target_scale / old if old > 0 else target_scale
        if abs(ratio - 1.0) < 0.0001:
            self._scale_factors[id(root)] = target_scale
            return
        self._scale_control_tree_inner(
            root,
            ratio,
            skip_ids or set(),
        )
        self._scale_factors[id(root)] = target_scale

    def _scale_control_tree_inner(
        self,
        start,
        ratio: float,
        skip_ids: set[int],
    ) -> None:
        stack = [start]
        seen: set[int] = set()
        while stack:
            control = stack.pop()
            if control is None or id(control) in seen:
                continue
            seen.add(id(control))
            if id(control) in skip_ids:
                continue
            self._scale_one_control(control, ratio)
            for child in self._control_children(control):
                if id(child) not in seen:
                    stack.append(child)

    def _control_children(self, control) -> list:
        children: list = []
        for name, value in vars(control).items():
            if name in ("parent", "_Control__page"):
                continue
            if isinstance(value, ft.Control):
                children.append(value)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, ft.Control):
                        children.append(item)
        return children

    def _scale_one_control(self, control, ratio: float) -> None:
        for attr in self._SCALE_ATTRS:
            try:
                value = getattr(control, attr, None)
            except Exception:
                continue
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                try:
                    setattr(control, attr, value * ratio)
                except Exception:
                    pass
            elif hasattr(value, "left") and hasattr(value, "top"):
                # Padding / Margin：替换成新对象，避免共享对象被重复缩放。
                try:
                    setattr(
                        control,
                        attr,
                        type(value)(
                            left=float(value.left) * ratio,
                            top=float(value.top) * ratio,
                            right=float(value.right) * ratio,
                            bottom=float(value.bottom) * ratio,
                        ),
                    )
                except Exception:
                    pass
            elif hasattr(value, "top_left") and hasattr(value, "bottom_right"):
                # BorderRadius
                try:
                    setattr(
                        control,
                        attr,
                        type(value)(
                            top_left=float(value.top_left) * ratio,
                            top_right=float(value.top_right) * ratio,
                            bottom_left=float(value.bottom_left) * ratio,
                            bottom_right=float(value.bottom_right) * ratio,
                        ),
                    )
                except Exception:
                    pass

        # 文本样式与按钮文字是独立对象，单独缩放字号。
        if isinstance(control, ft.Text):
            style = getattr(control, "style", None)
            self._scale_text_style(style, ratio)
        if isinstance(control, ft.Button):
            style = getattr(control, "style", None)
            if style is None:
                style = ft.ButtonStyle(
                    text_style=ft.TextStyle(size=14 * ratio),
                    icon_size=18 * ratio,
                )
                try:
                    control.style = style
                except Exception:
                    pass
            else:
                if getattr(style, "text_style", None) is None:
                    style.text_style = ft.TextStyle(size=14 * ratio)
                else:
                    self._scale_text_style(style.text_style, ratio)
                if getattr(style, "icon_size", None):
                    try:
                        style.icon_size = float(style.icon_size) * ratio
                    except Exception:
                        pass

    @staticmethod
    def _scale_text_style(style, ratio: float) -> None:
        if style is None:
            return
        try:
            if getattr(style, "size", None):
                style.size = float(style.size) * ratio
            if getattr(style, "letter_spacing", None):
                style.letter_spacing = float(style.letter_spacing) * ratio
        except Exception:
            pass

    def _on_page_resized(self, event) -> None:
        """窗口尺寸变化时只更新整体缩放，不改变页面内部布局。"""

        try:
            width = float(getattr(event, "width", 0) or 0)
            height = float(getattr(event, "height", 0) or 0)
            if width <= 0 or height <= 0:
                width = float(self.page.width or self.page.window.width or 1280)
                height = float(self.page.height or self.page.window.height or 760)
            self._apply_ui_scale(width, height)
        except Exception:
            pass

    async def _sync_ui_scale_async(self) -> None:
        """启动后多次校准缩放，避免恢复大窗口时仍按基准尺寸绘制。"""

        for delay in (0.05, 0.2, 0.5, 1.0, 2.0):
            await asyncio.sleep(delay)
            try:
                width = float(
                    self.page.width or self.page.window.width or 0
                )
                height = float(
                    self.page.height or self.page.window.height or 0
                )
                self._apply_ui_scale(width, height)
            except Exception:
                pass

    def _configure_page(self) -> None:
        self.page.title = "NLCL · 本地版本"
        self.page.padding = 0
        self.page.bgcolor = BG
        self.page.theme_mode = theme_mode(self.theme_store.name)
        self.page.theme = ft.Theme(
            color_scheme_seed=PRIMARY,
            font_family="Microsoft YaHei UI",
        )
        self.page.horizontal_alignment = ft.CrossAxisAlignment.START
        self.page.vertical_alignment = ft.MainAxisAlignment.START
        self.page.window.resizable = True
        # 最小尺寸固定为 950×500；基准画布更大时通过全局缩放适配。
        self.page.window.min_width = MIN_WINDOW_WIDTH
        self.page.window.min_height = MIN_WINDOW_HEIGHT
        dpi = _ui_scale()
        self.page.window.max_width = round(BASE_UI_WIDTH * dpi * MAX_UI_SCALE) + WINDOW_CHROME_X
        self.page.window.max_height = round(BASE_UI_HEIGHT * dpi * MAX_UI_SCALE) + WINDOW_CHROME_Y
        # 只在首次启动时设置基准窗口，避免切换主题时把用户放大后的窗口重置。
        if not getattr(self, "_window_initialized", False):
            self.page.window.width = 1280
            self.page.window.height = 720
            self._window_initialized = True

    def _build_sidebar(self, height: int | float) -> ft.Container:
        """左侧导航骨架。后续模块直接在这里增加入口。"""

        section_workspace = self._sidebar_label("工作区")
        self.nav_versions = self._nav_item(
            "本地版本",
            ft.Icons.GRID_VIEW_OUTLINED,
            active=True,
            enabled=True,
            on_click=self.show_versions,
        )
        self.nav_launch = self._nav_item(
            "启动与日志",
            ft.Icons.PLAY_CIRCLE_OUTLINE,
            enabled=True,
            on_click=self.show_launch_console,
        )
        self.nav_multiplayer = self._nav_item(
            "联机房间",
            ft.Icons.LINK,
            enabled=True,
            on_click=self.show_multiplayer,
        )
        self.nav_snapshot = self._nav_item(
            "实例快照",
            ft.Icons.CAMERA_ALT_OUTLINED,
            enabled=True,
            on_click=self.show_snapshot,
        )
        self.nav_lan_scan = self._nav_item(
            "局域网扫描",
            ft.Icons.RADAR,
            enabled=True,
            on_click=self.show_lan_scan,
        )
        self.nav_settings = self._nav_item(
            "设置",
            ft.Icons.SETTINGS_OUTLINED,
            enabled=True,
            on_click=self.show_settings,
        )

        section_tools = self._sidebar_label("工具")
        download_item = self._nav_item(
            "版本下载",
            ft.Icons.CLOUD_DOWNLOAD_OUTLINED,
            enabled=True,
            on_click=self.open_download_dialog,
        )
        import_item = self._nav_item(
            "导入资源",
            ft.Icons.UPLOAD_FILE,
            enabled=True,
            on_click=self.pick_import_files,
        )

        brand = ft.Row(
            controls=[
                ft.Container(
                    width=36,
                    height=36,
                    border_radius=10,
                    bgcolor=SIDEBAR_ACTIVE,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(
                        ft.Icons.INVENTORY_2,
                        color="#CFE9D9",
                        size=20,
                    ),
                ),
                ft.Column(
                    controls=[
                        ft.Text(
                            "NLCL",
                            size=20,
                            weight=ft.FontWeight.W_700,
                            color=SIDEBAR_TEXT,
                        ),
                        ft.Text(
                            "Minecraft Launcher",
                            size=8,
                            color=SIDEBAR_MUTED,
                        ),
                    ],
                    spacing=0,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        self.account_card = ft.Container(
            width=172,
            padding=PADDING.symmetric(horizontal=9, vertical=7),
            border_radius=10,
            bgcolor=SIDEBAR_ACTIVE,
            ink=True,
            on_click=self.open_account_dialog,
            tooltip="管理账号与皮肤",
            content=self._build_sidebar_account_content(),
        )

        footer = ft.Column(
            controls=[
                ft.Text("v1.0 · 全功能", size=9, color=SIDEBAR_MUTED),
                ft.Text("版本 · 下载 · 启动 · 联机 · 快照 · 导入", size=9, color=SIDEBAR_MUTED),
            ],
            spacing=2,
        )

        return ft.Container(
            width=SIDEBAR_WIDTH,
            bgcolor=SIDEBAR_BG,
            border_radius=18,
            padding=PADDING.symmetric(horizontal=16, vertical=14),
            content=ft.Column(
                controls=[
                    brand,
                    ft.Container(height=8),
                    self.account_card,
                    ft.Container(height=10),
                    section_workspace,
                    self.nav_versions,
                    self.nav_launch,
                    self.nav_multiplayer,
                    self.nav_snapshot,
                    self.nav_lan_scan,
                    self.nav_settings,
                    ft.Container(height=8),
                    section_tools,
                    download_item,
                    import_item,
                    ft.Container(expand=True),
                    footer,
                ],
                spacing=3,
                expand=True,
            ),
        )

    def _build_sidebar_account_content(self) -> ft.Row:
        """侧栏顶部账号卡：头像 + 名称 + 账号类型。"""

        account = self.account_store.active_account
        name = account.name if account else "未登录"
        subtitle = (
            account.type_label if account is not None else "点击登录账号"
        )
        return ft.Row(
            controls=[
                account_avatar(account, size=28),
                ft.Column(
                    controls=[
                        ft.Text(
                            name,
                            size=10,
                            color=SIDEBAR_TEXT,
                            weight=ft.FontWeight.W_600,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Text(
                            subtitle,
                            size=8,
                            color=SIDEBAR_MUTED,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=0,
                    expand=True,
                ),
                ft.Icon(
                    ft.Icons.CHEVRON_RIGHT,
                    size=14,
                    color=SIDEBAR_MUTED,
                ),
            ],
            spacing=7,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def open_account_dialog(self, _event=None) -> None:
        if self._account_dialog is not None and self._account_dialog.is_open:
            return
        self._account_dialog = AccountDialog(
            self.page,
            self.account_store,
            on_changed=self._on_account_changed,
        )
        self._account_dialog.open()

    def _refresh_sidebar_account(self) -> None:
        if hasattr(self, "account_card"):
            self.account_card.content = self._build_sidebar_account_content()

    def _on_account_changed(self, _state=None) -> None:
        self._refresh_sidebar_account()
        if self.launch_view is not None:
            self.launch_view.refresh()
        self._schedule_skin_prefetch()
        self.page.update()

    def _schedule_skin_prefetch(self) -> None:
        account = self.account_store.active_account
        if account is None or not account.is_microsoft or not account.skin_url:
            return
        if self._skin_prefetching:
            return
        self._skin_prefetching = True
        self.page.run_task(self._prefetch_skin_async, account)

    async def _prefetch_skin_async(self, account) -> None:
        try:
            await asyncio.to_thread(get_skin_manager().prefetch, account)
        finally:
            self._skin_prefetching = False
        if self.account_store.active_account and self.account_store.active_account.id == account.id:
            self._refresh_sidebar_account()
            self.page.update()

    def open_skin_dialog(self, _event=None) -> None:
        if self._skin_dialog is not None and self._skin_dialog.is_open:
            return
        self._skin_dialog = SkinManagerDialog(
            self.page,
            self.account_store,
            on_changed=self._on_account_changed,
        )
        self._skin_dialog.open()

    def show_settings(self, _event=None) -> None:
        if self.settings_view is None:
            self.settings_view = SettingsView(
                self.page,
                self.root_height,
                self.launch_settings_store,
                self.app_settings_store,
                self.theme_store,
                self.account_store,
                on_theme_changed=self._change_theme,
                on_download_directory_changed=self._set_download_directory,
                on_account_manager=self.open_account_dialog,
                on_refresh=self._on_settings_refresh,
            )
        self._attach_view(self.settings_view.view)
        self.current_view = "settings"
        self._set_active_nav("settings")
        self.page.update()

    def _open_settings(self) -> None:
        self.show_settings()

    def _on_settings_refresh(self) -> None:
        if self.launch_view is not None:
            self.launch_view.apply_preferences()
        self._refresh_sidebar_account()
        self.page.update()

    def _set_download_directory(self, directory: str) -> None:
        if not directory:
            return
        self._game_dir = directory
        if hasattr(self, "path_field"):
            self.path_field.value = directory
        self.app_settings_store.settings.download_directory = directory
        self.app_settings_store.save(self.app_settings_store.settings)
        self.refresh_versions()

    def _change_theme(self, name: str) -> None:
        self.theme_store.save(name)
        apply_theme(name)
        self._configure_page()
        self._rebuild_ui("settings")

    def _rebuild_ui(self, view: str | None = None) -> None:
        """主题切换后重建控件；保留账号、实例和扫描结果等状态。"""

        current = view or self.current_view
        saved_path = getattr(self, "path_field", None)
        if saved_path is not None and saved_path.value:
            self._game_dir = saved_path.value
        if self.launch_view is not None:
            self.launch_controller.remove_listener(
                self.launch_view._on_controller_update
            )
        self.launch_view = None
        self.multiplayer_view = None
        self.lan_scan_view = None
        self.snapshot_view = None
        self.settings_view = None
        self.version_page = None
        self.main_slot = None
        self._account_dialog = None
        self._skin_dialog = None
        self._download_dialog = None
        self._import_dialog = None
        self._details_dialog = None
        self.page.overlay.clear()
        self.page.clean()
        self.mount()
        if current == "launch":
            self.show_launch_console()
        elif current == "multiplayer":
            self.show_multiplayer()
        elif current == "snapshot":
            self.show_snapshot()
        elif current == "lan_scan":
            self.show_lan_scan()
        elif current == "settings":
            self.show_settings()
        else:
            self.show_versions()

    # ---- 主视图路由 ------------------------------------------------------
    def _set_active_nav(self, active: str) -> None:
        for key, item in (
            ("versions", self.nav_versions),
            ("launch", self.nav_launch),
            ("multiplayer", self.nav_multiplayer),
            ("snapshot", self.nav_snapshot),
            ("lan_scan", self.nav_lan_scan),
            ("settings", self.nav_settings),
        ):
            item.bgcolor = SIDEBAR_ACTIVE if key == active else None

    def _current_versions(self):
        if self.current_scan_result is None:
            self.refresh_versions()
        result = self.current_scan_result
        versions = list(result.versions) if result is not None else []

        # 独立的 Modrinth 实例位于各自的 .minecraft 根目录；只把注册的
        # 目标版本加入启动列表，避免把该实例里的原版基础版本重复列出。
        try:
            from instance_registry import InstanceRegistry

            for entry in InstanceRegistry().items:
                root = Path(str(entry.get("root") or ""))
                folder = str(entry.get("version_folder") or "")
                if not root.is_dir() or not folder:
                    continue
                try:
                    imported = scan_local_versions(root)
                except Exception:
                    continue
                for version in imported.versions:
                    if version.folder_name == folder:
                        if all(
                            item.folder_name != version.folder_name
                            for item in versions
                        ):
                            versions.append(version)
                        break
        except Exception:
            pass
        return versions

    def show_versions(self, _event=None) -> None:
        self._attach_view(self.version_page)
        self.current_view = "versions"
        self._set_active_nav("versions")
        self.page.update()

    def show_launch_console(self, _event=None) -> None:
        versions = self._current_versions()
        if self.launch_view is None:
            self.launch_view = LaunchConsoleView(
                self.page,
                versions,
                self.root_height,
                self.account_store,
                self.launch_settings_store,
                self.launch_controller,
                app_settings_store=self.app_settings_store,
            )
        else:
            self.launch_view.versions = list(versions)
            self.launch_view.version_by_folder = {
                version.folder_name: version for version in versions
            }
            self.launch_view.refresh()
        self._attach_view(self.launch_view.view)
        self.current_view = "launch"
        self._set_active_nav("launch")
        self.page.update()

    def show_multiplayer(self, _event=None) -> None:
        versions = self._current_versions()
        if self.multiplayer_view is None:
            self.multiplayer_view = MultiplayerView(
                self.page,
                versions,
                self.root_height,
                self.account_store,
                self.launch_settings_store,
                self.launch_controller,
                on_session_started=self._on_multiplayer_session_started,
            )
        else:
            self.multiplayer_view.versions = list(versions)
            self.multiplayer_view.version_by_folder = {
                version.folder_name: version for version in versions
            }
            self.multiplayer_view.refresh()
        self._attach_view(self.multiplayer_view.view)
        self.current_view = "multiplayer"
        self._set_active_nav("multiplayer")
        self.page.update()

    def _on_multiplayer_session_started(self, session_id: str) -> None:
        self.show_launch_console()
        if self.launch_view is not None:
            self.launch_view.select_session(session_id)

    def show_snapshot(self, _event=None) -> None:
        versions = self._current_versions()
        if self.snapshot_view is None:
            self.snapshot_view = SnapshotView(
                self.page,
                versions,
                self.root_height,
            )
        else:
            self.snapshot_view.set_versions(versions)
        self._attach_view(self.snapshot_view.view)
        self.current_view = "snapshot"
        self._set_active_nav("snapshot")
        self.page.update()

    def show_lan_scan(self, _event=None) -> None:
        versions = self._current_versions()
        if self.lan_scan_view is None:
            self.lan_scan_view = LanScanView(
                self.page,
                versions,
                self.root_height,
                self.account_store,
                self.launch_settings_store,
                self.launch_controller,
                on_session_started=self._on_multiplayer_session_started,
            )
        else:
            self.lan_scan_view.set_versions(versions)
        self._attach_view(self.lan_scan_view.view)
        self.current_view = "lan_scan"
        self._set_active_nav("lan_scan")
        self.page.update()

    def _sidebar_label(self, text: str) -> ft.Container:
        return ft.Container(
            padding=PADDING.only(left=8, top=5, bottom=2),
            content=ft.Text(
                text,
                size=9,
                color="#89A796",
                weight=ft.FontWeight.W_600,
                style=ft.TextStyle(letter_spacing=1.0),
            ),
        )

    def _nav_item(
        self,
        text: str,
        icon,
        *,
        active: bool = False,
        enabled: bool = False,
        on_click=None,
    ) -> ft.Container:
        """一个导航项。enabled=False 的项只是占位，不绑定点击事件。"""

        clickable = active or enabled
        fg = SIDEBAR_TEXT if clickable else SIDEBAR_MUTED
        return ft.Container(
            padding=PADDING.symmetric(horizontal=9, vertical=5),
            border_radius=9,
            bgcolor=SIDEBAR_ACTIVE if active else None,
            opacity=1.0 if clickable else 0.48,
            ink=bool(on_click),
            on_click=on_click,
            content=ft.Row(
                controls=[
                    ft.Icon(icon, size=17, color=fg),
                    ft.Text(text, size=12, color=fg),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def open_download_dialog(self, _event=None) -> None:
        """打开原版下载弹窗。"""

        if self._download_dialog is not None and (
            self._download_dialog.is_open or self._download_dialog.downloading
        ):
            return

        game_dir = (self.path_field.value or "").strip()
        if not game_dir:
            game_dir = str(default_minecraft_dir())

        self._download_dialog = DownloadDialog(
            self.page,
            game_dir,
            on_downloaded=self._on_download_completed,
            on_switch_directory=self._switch_game_directory,
        )
        self._download_dialog.open()

    # ---- 拖拽导入 --------------------------------------------------------
    def _start_file_drop(self) -> None:
        try:
            self.page.run_task(self._start_file_drop_async)
        except Exception:
            self._file_drop = None

    async def _start_file_drop_async(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            self._file_drop = WindowsFileDrop(loop, self._on_native_drop)
            self._file_drop.start()
        except Exception:
            self._file_drop = None

    async def _on_native_drop(self, paths: list[str]) -> None:
        files = [path for path in paths if Path(path).is_file()]
        if files:
            self._handle_import_paths(files)

    def pick_import_files(self, _event=None) -> None:
        self.import_picker.pick_files(
            dialog_title="导入 JAR / Modrinth 整合包",
            allow_multiple=False,
        )

    def _on_import_files_picked(self, event) -> None:
        files = [item.path for item in (event.files or []) if item.path]
        if files:
            self._handle_import_paths(files)

    def _handle_import_paths(self, paths: list[str]) -> None:
        self._import_dialog = ImportDialog(
            self.page,
            self._current_versions(),
            on_finished=self._on_import_finished,
        )
        self._import_dialog.open(paths)

    def _on_import_finished(self, entry) -> None:
        self._import_dialog = None
        if entry is None:
            return
        self.refresh_versions()
        self.show_launch_console()
        if (
            isinstance(entry, dict)
            and entry.get("version_folder")
            and self.launch_view is not None
        ):
            self.launch_view.version_dropdown.value = str(entry["version_folder"])
            self.launch_view._on_version_changed()
            self.page.update()

    # ---- 目录选择 --------------------------------------------------------
    def _pick_main_directory(self, _event=None) -> None:
        """打开系统文件夹选择器，用作本地版本扫描目录。"""

        current = Path(self.path_field.value or str(default_minecraft_dir())).expanduser()
        initial = current.parent if current.parent.exists() else Path.home()
        self.dir_picker.get_directory_path(
            dialog_title="选择 Minecraft 游戏目录（.minecraft）",
            initial_directory=str(initial),
        )

    def _on_main_dir_picked(self, event) -> None:
        path = (event.path or "").strip()
        if not path:
            return
        self.path_field.value = path
        self.refresh_versions()

    def _on_download_completed(self, target_directory: str) -> None:
        """只有下载目标就是当前版本目录时，才自动刷新版本页。"""

        current = (self.path_field.value or "").strip() or str(default_minecraft_dir())
        if same_directory(target_directory, current):
            self.refresh_versions()

    def _switch_game_directory(self, directory: str) -> None:
        """下载到自定义目录后，允许一键把版本页切换到该目录。"""

        if not directory:
            return
        self.path_field.value = directory
        self.refresh_versions()

    def _open_version_details(self, version: LocalVersion) -> None:
        if self._details_dialog is not None and self._details_dialog.is_open:
            return

        # 从版本目录反推 .minecraft 根目录，避免用户改了输入框但还没重新扫描时
        # 详情页读取到错误的 mods/resourcepacks 目录。
        game_dir = str(version.directory.parent.parent)

        self._details_dialog = VersionDetailsDialog(
            self.page,
            version,
            game_dir,
            on_deleted=self.refresh_versions,
        )
        self._details_dialog.open()

    def _build_main_area(self, height: int | float) -> ft.Container:
        self.launch_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "启动游戏"},
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            on_click=self.show_launch_console,
        )
        header = ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            "本地版本库",
                            size=9,
                            color=PRIMARY,
                            weight=ft.FontWeight.W_600,
                            style=ft.TextStyle(letter_spacing=1.2),
                        ),
                        ft.Text(
                            "游戏版本",
                            size=26,
                            color=TEXT,
                            weight=ft.FontWeight.W_700,
                        ),
                        ft.Text(
                            "扫描本地 .minecraft，选择版本并启动游戏",
                            size=11,
                            color=MUTED,
                        ),
                    ],
                    spacing=1,
                ),
                ft.Row(
                    controls=[
                        ft.Container(
                            padding=PADDING.symmetric(horizontal=9, vertical=4),
                            border_radius=20,
                            bgcolor=PRIMARY_SOFT,
                            content=ft.Row(
                                controls=[
                                    ft.Container(
                                        width=5,
                                        height=5,
                                        border_radius=3,
                                        bgcolor=PRIMARY,
                                    ),
                                    ft.Text("扫描只读", size=10, color=PRIMARY),
                                ],
                                spacing=5,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ),
                        self.launch_button,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        directory_card = ft.Container(
            bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=14,
            padding=PADDING.symmetric(horizontal=16, vertical=14),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(
                                "游戏目录",
                                size=12,
                                color=TEXT,
                                weight=ft.FontWeight.W_600,
                            ),
                            ft.Text(
                                "可选择目录 · 只读扫描",
                                size=10,
                                color=FAINT,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        controls=[self.path_field, self.scan_button],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=10,
                tight=True,
            ),
        )

        summary_bar = ft.Row(
            controls=[
                self.summary_row,
                ft.Text("时间倒序", size=10, color=FAINT),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Column(
                controls=[
                    header,
                    directory_card,
                    summary_bar,
                    self.issues_panel,
                    ft.Container(
                        content=self.version_list,
                        expand=True,
                    ),
                ],
                spacing=14,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    # ---- 数据刷新 --------------------------------------------------------
    def refresh_versions(self, _event=None) -> None:
        """读取目录并刷新列表。扫描逻辑完全复用 version_scanner。"""

        raw_path = (self.path_field.value or "").strip()
        if not raw_path:
            raw_path = str(default_minecraft_dir())

        self.scan_button.disabled = True
        self._show_loading()
        self.page.update()

        try:
            result = scan_local_versions(raw_path)
        except Exception as exc:
            # 扫描函数内部已经处理常见错误，这里兜底，避免 UI 线程直接崩掉。
            fallback_path = Path(raw_path).expanduser()
            result = ScanResult(
                minecraft_dir=fallback_path,
                issues=[ScanIssue(path=fallback_path, message=f"扫描失败：{exc}")],
            )
        finally:
            self.scan_button.disabled = False

        self.path_field.value = str(result.minecraft_dir)
        self.current_scan_result = result
        self._render_result(result)
        # 首次扫描结束时窗口通常已完成布局，再校准一次，避免启动时遗留右侧/底部空白。
        try:
            self._apply_ui_scale(
                float(self.page.width or self.page.window.width or 0),
                float(self.page.height or self.page.window.height or 0),
            )
        except Exception:
            pass
        self.page.update()

    def _show_loading(self) -> None:
        self.summary_row.controls.clear()
        self.summary_row.controls.append(
            ft.Text("正在读取本地版本…", size=12, color=MUTED)
        )

    def _render_result(self, result: ScanResult) -> None:
        """把扫描结果渲染到列表中。"""

        self.version_list.controls.clear()

        type_counts: dict[str, int] = {}
        for version in result.versions:
            type_counts[version.version_type] = type_counts.get(version.version_type, 0) + 1
            self.version_list.controls.append(self._build_version_card(version))

        if not result.versions:
            self.version_list.controls.append(self._build_empty_state())

        self._render_summary(result, type_counts)
        self._render_issues(result.issues)

    def _render_summary(self, result: ScanResult, type_counts: dict[str, int]) -> None:
        self.summary_row.controls.clear()
        self.summary_row.controls.append(
            ft.Text(
                f"{result.version_count} 个版本",
                size=13,
                color=TEXT,
                weight=ft.FontWeight.W_600,
            )
        )

        # 已知类型按固定顺序展示，其他自定义类型追加在后面。
        ordered_types = ["release", "snapshot", "old_beta", "old_alpha"]
        ordered_types.extend(
            key for key in type_counts if key not in ordered_types
        )
        for version_type in ordered_types:
            count = type_counts.get(version_type, 0)
            if not count:
                continue
            color, bgcolor, _icon = self._type_style(version_type)
            self.summary_row.controls.append(
                self._count_chip(
                    f"{version_type_label(version_type)} {count}",
                    color,
                    bgcolor,
                )
            )

    def _count_chip(self, text: str, color: str, bgcolor: str) -> ft.Container:
        return ft.Container(
            padding=PADDING.symmetric(horizontal=8, vertical=3),
            border_radius=7,
            bgcolor=bgcolor,
            content=ft.Row(
                controls=[
                    ft.Container(width=4, height=4, border_radius=2, bgcolor=color),
                    ft.Text(text, size=10, color=color),
                ],
                spacing=5,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _render_issues(self, issues: list[ScanIssue]) -> None:
        """展示扫描问题；没有问题时隐藏提示框。"""

        self.issues_column.controls.clear()
        if not issues:
            self.issues_panel.visible = False
            return

        self.issues_panel.visible = True
        self.issues_column.controls.append(
            ft.Text(
                f"发现 {len(issues)} 个问题（其余版本仍会正常显示）",
                size=11,
                color=AMBER,
                weight=ft.FontWeight.W_600,
            )
        )
        for issue in issues:
            self.issues_column.controls.append(
                ft.Text(
                    f"{issue.path}：{issue.message}",
                    size=10,
                    color=AMBER,
                    selectable=True,
                )
            )

    # ---- 版本卡片 --------------------------------------------------------
    def _build_version_card(self, version: LocalVersion) -> ft.Control:
        color, soft_color, icon = self._type_style(version.version_type)

        meta_parts = [f"{format_release_date(version.release_time)} 发布"]
        if version.inherits_from:
            meta_parts.append(f"基于 {version.inherits_from}")
        if version.folder_name != version.version_id:
            meta_parts.append(f"目录 {version.folder_name}")

        title_row = ft.Row(
            controls=[
                ft.Text(
                    version.version_id,
                    size=15,
                    color=TEXT,
                    weight=ft.FontWeight.W_600,
                    selectable=False,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    expand=True,
                ),
                self._type_badge(version.version_type, color, soft_color),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        info_controls: list[ft.Control] = [
            title_row,
            ft.Text(
                "  ·  ".join(meta_parts),
                size=11,
                color=MUTED,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            ),
        ]

        # 原版缺少客户端 JAR 通常无法启动；继承版本可能复用父版本文件，不提示。
        if not version.has_client_jar and not version.inherits_from:
            info_controls.append(
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.ERROR_OUTLINE, size=13, color=AMBER),
                        ft.Text(
                            "未找到客户端 JAR，可能无法启动",
                            size=10,
                            color=AMBER,
                        ),
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )

        return ft.Container(
            padding=PADDING.symmetric(horizontal=16, vertical=13),
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=12,
            bgcolor=CARD,
            ink=True,
            tooltip="点击查看版本详情",
            on_click=lambda _event, current=version: self._open_version_details(current),
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=38,
                        height=38,
                        border_radius=10,
                        bgcolor=soft_color,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(icon, size=19, color=color),
                    ),
                    ft.Column(
                        controls=info_controls,
                        spacing=4,
                        tight=True,
                        expand=True,
                    ),
                    ft.Container(
                        width=16,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(
                            ft.Icons.CHEVRON_RIGHT,
                            size=18,
                            color=FAINT,
                        ),
                    ),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )

    def _type_badge(self, version_type: str, color: str, bgcolor: str) -> ft.Container:
        return ft.Container(
            padding=PADDING.symmetric(horizontal=8, vertical=3),
            border_radius=7,
            bgcolor=bgcolor,
            content=ft.Row(
                controls=[
                    ft.Container(width=4, height=4, border_radius=2, bgcolor=color),
                    ft.Text(
                        version_type_label(version_type),
                        size=10,
                        color=color,
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                spacing=5,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _type_style(self, version_type: str):
        return TYPE_STYLES.get(
            version_type,
            (OLD, OLD_BG, ft.Icons.INVENTORY_2_OUTLINED),
        )

    def _build_empty_state(self) -> ft.Control:
        """没有版本时展示的空状态。"""

        return ft.Container(
            height=250,
            bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=14,
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                controls=[
                    ft.Container(
                        width=54,
                        height=54,
                        border_radius=16,
                        bgcolor=PRIMARY_SOFT,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(
                            ft.Icons.INVENTORY_2_OUTLINED,
                            size=26,
                            color=PRIMARY,
                        ),
                    ),
                    ft.Text(
                        "没有找到可用的游戏版本",
                        size=14,
                        color=TEXT,
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(
                        "请确认 .minecraft 路径正确，或先在游戏目录中安装一个版本。",
                        size=11,
                        color=MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                spacing=8,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )


def _ui_scale() -> float:
    """读取 Windows 实际 DPI 缩放（125% 时为 1.25）。

    直接调用 GetDpiForSystem() 时，Python 进程如果未声明 DPI 感知会返回 96，
    因此优先读取桌面设置中的 AppliedDPI。
    """

    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop\WindowMetrics",
        )
        try:
            dpi, _kind = winreg.QueryValueEx(key, "AppliedDPI")
        finally:
            winreg.CloseKey(key)
        if isinstance(dpi, int) and dpi > 0:
            return max(dpi / 96.0, 1.0)
    except Exception:
        pass

    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        return max(dpi / 96.0, 1.0)
    except Exception:
        return 1.0


def main(page: ft.Page) -> None:
    VersionBrowser(page).mount()


if __name__ == "__main__":
    # Flet 1.x 使用 ft.run；Flet 0.28.x 使用 ft.app(target=...)。
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)

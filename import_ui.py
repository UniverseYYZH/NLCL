"""拖拽导入弹窗：mod jar 与 Modrinth .mrpack。"""

from __future__ import annotations

import asyncio

import flet as ft

from instance_registry import InstanceRegistry
from mod_import import (
    MrpackInfo,
    copy_mod_jar,
    import_mrpack,
    inspect_jar,
    install_loader_for_instance,
    parse_mrpack,
)
from ui_theme import (
    BORDER,
    BORDER_COLOR,
    BUTTON_LABEL_FIELD,
    ERROR,
    FAINT,
    MUTED,
    PADDING,
    PRIMARY,
    SURFACE,
    TEXT,
    TEXT_BUTTON_LABEL_FIELD,
)
from version_scanner import LocalVersion

TYPE_LABELS = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "旧测试版",
    "old_alpha": "旧预览版",
}


class ImportDialog:
    def __init__(
        self,
        page: ft.Page,
        versions: list[LocalVersion],
        on_finished,
        registry: InstanceRegistry | None = None,
    ) -> None:
        self.page = page
        self.versions = list(versions)
        self.version_by_folder = {item.folder_name: item for item in versions}
        self.on_finished = on_finished
        self.registry = registry or InstanceRegistry()
        self.dialog: ft.AlertDialog | None = None
        self._busy = False
        self._loop = asyncio.get_running_loop()

    def open(self, paths: list[str]) -> None:
        files = [path for path in paths if path]
        if not files:
            return
        first = files[0].lower()
        try:
            if first.endswith((".mrpack", ".zip")):
                info = parse_mrpack(files[0])
                self._open_mrpack(info)
            elif first.endswith(".jar"):
                self._open_jar(files[0])
            else:
                self._show_error("只支持 .jar、.mrpack 或整合包 .zip")
        except Exception as exc:
            self._show_error(str(exc))

    def _open_jar(self, path: str) -> None:
        jar = inspect_jar(path)
        self.version_dropdown = ft.Dropdown(
            label="目标实例",
            width=320,
            dense=True,
            text_size=10,
            options=[
                ft.dropdown.Option(
                    key=version.folder_name,
                    text=f"{version.version_id} · {TYPE_LABELS.get(version.version_type, version.version_type)}",
                )
                for version in self.versions
            ],
            value=self.versions[0].folder_name if self.versions else None,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=4),
        )
        self.import_log = ft.Text("", size=9, color=MUTED, selectable=True, width=440)
        if jar.kind == "mod":
            message = f"检测到普通模组：{jar.name or jar.path.name}"
            action_text = "导入到 mods"
        else:
            loader_name = "Fabric" if jar.kind == "fabric_loader" else "Forge"
            message = (
                f"检测到 {loader_name} 加载器安装器。\n"
                "可以选择把对应加载器安装到目标实例，而不是放进 mods。"
            )
            action_text = f"安装 {loader_name} 加载器"
        self._jar = jar
        self._show_dialog(
            title="导入 JAR",
            content=ft.Column(
                controls=[
                    ft.Text(message, size=10, color=TEXT),
                    ft.Text(
                        "普通模组会复制到该实例的 mods 目录；加载器安装器会调用安装逻辑。",
                        size=9,
                        color=MUTED,
                    ),
                    self.version_dropdown,
                    ft.Container(
                        width=460,
                        height=90,
                        bgcolor=SURFACE,
                        border=BORDER.all(1, BORDER_COLOR),
                        border_radius=8,
                        padding=8,
                        content=ft.Column([self.import_log], scroll=ft.ScrollMode.AUTO),
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            actions=[
                ft.TextButton(
                    **{TEXT_BUTTON_LABEL_FIELD: "取消"},
                    on_click=lambda _e: self._close(),
                ),
                ft.FilledButton(
                    **{BUTTON_LABEL_FIELD: action_text},
                    bgcolor=PRIMARY,
                    color="#FFFFFF",
                    on_click=self._do_jar_import,
                ),
            ],
        )

    def _open_mrpack(self, info: MrpackInfo) -> None:
        self._mrpack = info
        self.import_log = ft.Text("", size=9, color=MUTED, selectable=True, width=440)
        self._show_dialog(
            title="导入 Modrinth 整合包",
            content=ft.Column(
                controls=[
                    ft.Text(f"整合包：{info.name}", size=12, color=TEXT, weight=ft.FontWeight.W_600),
                    ft.Text(
                        f"Minecraft {info.minecraft} · {info.loader} {info.loader_version} · "
                        f"{len(info.files)} 个下载文件",
                        size=9,
                        color=MUTED,
                    ),
                    ft.Text(
                        "会创建一个独立的 .minecraft 实例，自动安装加载器和匹配 Java，"
                        "部署 mods/config/资源，并注册到启动列表。",
                        size=9,
                        color=FAINT,
                    ),
                    ft.Container(
                        width=460,
                        height=130,
                        bgcolor=SURFACE,
                        border=BORDER.all(1, BORDER_COLOR),
                        border_radius=8,
                        padding=8,
                        content=ft.Column([self.import_log], scroll=ft.ScrollMode.AUTO),
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            actions=[
                ft.TextButton(
                    **{TEXT_BUTTON_LABEL_FIELD: "取消"},
                    on_click=lambda _e: self._close(),
                ),
                ft.FilledButton(
                    **{BUTTON_LABEL_FIELD: "创建独立实例"},
                    bgcolor=PRIMARY,
                    color="#FFFFFF",
                    on_click=self._do_mrpack_import,
                ),
            ],
        )

    def _show_dialog(self, title, content, actions) -> None:
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, size=16, color=TEXT),
            content=content,
            actions=actions,
            actions_padding=PADDING.symmetric(horizontal=18, vertical=10),
        )
        self.page.open(self.dialog)
        self.page.update()

    def _show_error(self, message: str) -> None:
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("导入失败", size=16, color=TEXT),
            content=ft.Text(message, size=10, color=ERROR, width=400),
            actions=[
                ft.TextButton(
                    **{TEXT_BUTTON_LABEL_FIELD: "关闭"},
                    on_click=lambda _e: self.page.close(dialog),
                )
            ],
        )
        self.page.open(dialog)
        self.page.update()

    def _append_log(self, message: str) -> None:
        if self.import_log is None:
            return
        current = self.import_log.value or ""
        lines = (current + "\n" + message).strip().splitlines()[-12:]
        self.import_log.value = "\n".join(lines)
        self.page.update()

    def _thread_progress(self, message: str) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self._append_log_async(message), self._loop)
        except Exception:
            pass

    async def _append_log_async(self, message: str) -> None:
        self._append_log(message)

    def _selected_version(self) -> LocalVersion | None:
        return self.version_by_folder.get(self.version_dropdown.value or "")

    def _do_jar_import(self, _event=None) -> None:
        if self._busy:
            return
        version = self._selected_version()
        if version is None:
            self._append_log("请选择目标实例")
            return
        root = version.directory.parent.parent
        jar = self._jar
        if jar.kind == "mod":
            try:
                target = copy_mod_jar(jar.path, root)
                self._append_log(f"已导入：{target}")
                self.on_finished(None)
                self._close()
            except Exception as exc:
                self._append_log(f"导入失败：{exc}")
            return

        self._busy = True
        self._append_log("开始安装加载器…")
        base_version = version.inherits_from or version.version_id
        mode = "fabric" if jar.kind == "fabric_loader" else "forge"
        self.page.run_task(
            self._install_loader_async,
            root,
            base_version,
            mode,
            version,
        )

    async def _install_loader_async(self, root, base_version, mode, version) -> None:
        try:
            installed = await asyncio.to_thread(
                install_loader_for_instance,
                root,
                base_version,
                mode,
                self._thread_progress,
            )
            self._append_log(f"加载器安装完成：{installed}")
            self.registry.add(
                f"{version.version_id} {mode}",
                root,
                installed,
                loader=mode,
                minecraft_version=base_version,
            )
            self.on_finished(installed)
            self._busy = False
            self._close()
        except Exception as exc:
            self._append_log(f"安装失败：{exc}")
        finally:
            self._busy = False
            self.page.update()

    def _do_mrpack_import(self, _event=None) -> None:
        if self._busy:
            return
        self._busy = True
        self._append_log("开始创建独立实例…")
        self.page.run_task(self._mrpack_async)

    async def _mrpack_async(self) -> None:
        try:
            entry = await asyncio.to_thread(
                import_mrpack,
                self._mrpack,
                self._thread_progress,
                self.registry,
            )
            self._append_log(f"完成：{entry.get('name')}")
            self.on_finished(entry)
            self._busy = False
            self._close()
        except Exception as exc:
            self._append_log(f"导入失败：{exc}")
        finally:
            self._busy = False
            self.page.update()

    def _current_minecraft_root(self, version: LocalVersion):
        # 当前扫描根目录；用于判断目标是否属于独立实例。
        try:
            return version.directory.parent.parent
        except Exception:
            return ""

    def _close(self) -> None:
        if self._busy:
            return
        if self.dialog is not None and self.dialog.open:
            self.page.close(self.dialog)
        self.dialog = None
        self.page.update()

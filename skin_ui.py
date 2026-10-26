"""皮肤管理弹窗：上传、历史、账号选择、2D 头像预览。"""

from __future__ import annotations

import flet as ft

from account_manager import Account, AccountStore
from skin_manager import SkinManager, SkinRecord, SkinError, avatar_base64, get_skin_manager
from ui_theme import (
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


class SkinManagerDialog:
    def __init__(
        self,
        page: ft.Page,
        store: AccountStore,
        on_changed=None,
        manager: SkinManager | None = None,
    ) -> None:
        self.page = page
        self.store = store
        self.on_changed = on_changed
        self.manager = manager or get_skin_manager()
        self.dialog: ft.AlertDialog | None = None
        self.file_picker = ft.FilePicker(on_result=self._on_file_picked)
        self._build()

    @property
    def is_open(self) -> bool:
        return self.dialog is not None and bool(self.dialog.open)

    def open(self) -> None:
        if self.dialog is not None and self.dialog.open:
            return
        self.page.overlay.append(self.file_picker)
        self.account_dropdown.options = [
            ft.dropdown.Option(key=account.id, text=f"{account.name} · {account.type_label}")
            for account in self.store.accounts
        ]
        active = self.store.active_account
        if active is not None:
            self.account_dropdown.value = active.id
        elif self.store.accounts:
            self.account_dropdown.value = self.store.accounts[0].id
        self.page.open(self.dialog)
        self._refresh()
        self.page.update()

    def _build(self) -> None:
        self.account_dropdown = ft.Dropdown(
            label="账号",
            width=300,
            dense=True,
            text_size=10,
            options=[],
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=8,
            content_padding=PADDING.symmetric(horizontal=10, vertical=4),
            on_change=lambda _e: self._refresh(),
        )
        self.upload_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "上传皮肤"},
            icon=ft.Icons.UPLOAD_FILE,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            on_click=self._pick_file,
        )
        self.preview_full = ft.Image(width=80, height=80, fit=ft.ImageFit.CONTAIN)
        self.preview_head = ft.Image(width=76, height=76, fit=ft.ImageFit.COVER, border_radius=38)
        self.preview_name = ft.Text("", size=12, color=TEXT, weight=ft.FontWeight.W_600)
        self.preview_meta = ft.Text("", size=9, color=MUTED)
        self.history_row = ft.Row(wrap=True, spacing=8, run_spacing=8)
        self.status = ft.Text("", size=9, color=FAINT)

        preview_card = ft.Container(
            width=620,
            bgcolor=SURFACE,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=10,
            padding=12,
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[self.preview_full, ft.Text("完整皮肤", size=8, color=FAINT)],
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Column(
                        controls=[
                            self.preview_head,
                            ft.Text("头像吸附预览", size=8, color=FAINT),
                        ],
                        spacing=4,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Column(
                        controls=[
                            self.preview_name,
                            self.preview_meta,
                            ft.Text(
                                "支持 64×64 / 64×32 PNG。微软正版账号优先显示官方皮肤；"
                                "离线账号使用这里选择的皮肤，没有选择时显示默认史蒂夫。",
                                size=8,
                                color=MUTED,
                                width=330,
                            ),
                        ],
                        spacing=4,
                        expand=True,
                    ),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        content = ft.Container(
            width=656,
            height=270,
            bgcolor=BG,
            padding=PADDING.symmetric(horizontal=14, vertical=10),
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[self.account_dropdown, self.upload_button],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    preview_card,
                    ft.Text("历史皮肤", size=9, color=FAINT),
                    ft.Container(
                        width=620,
                        height=54,
                        content=ft.Column(
                            controls=[self.history_row],
                            scroll=ft.ScrollMode.AUTO,
                        ),
                    ),
                    self.status,
                ],
                spacing=8,
            ),
        )
        close = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            icon_color=MUTED,
            on_click=lambda _e: self._close(),
        )
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Text("皮肤管理", size=16, color=TEXT),
                    close,
                ],
                width=620,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            content=content,
            content_padding=0,
            title_padding=PADDING.only(left=20, right=20, top=12),
            bgcolor=CARD,
            shape=ft.RoundedRectangleBorder(radius=18),
            inset_padding=18,
        )

    def _selected_account(self) -> Account | None:
        account_id = self.account_dropdown.value
        for account in self.store.accounts:
            if account.id == account_id:
                return account
        return None

    def _refresh(self) -> None:
        account = self._selected_account()
        if account is None:
            self.preview_full.src_base64 = None
            self.preview_head.src_base64 = None
            self.preview_name.value = "未选择账号"
            self.preview_meta.value = ""
            self.history_row.controls.clear()
            self.page.update()
            return

        selected = self.manager.selected(account.id)
        skin_path = selected
        if account.is_microsoft and account.skin_url:
            # 微软账号头像优先官方皮肤；预览仍允许展示本地历史。
            source_note = "微软正版 · 官方皮肤优先"
        else:
            source_note = "离线账号 · 本地皮肤" if selected else "离线账号 · 默认史蒂夫"
        if skin_path is not None:
            try:
                self.preview_full.src_base64 = self.manager.full_skin_base64(skin_path)
            except Exception:
                self.preview_full.src_base64 = None
        else:
            default = self.manager._ensure_default_skin()
            self.preview_full.src_base64 = self.manager.full_skin_base64(default)
        self.preview_head.src_base64 = avatar_base64(account, 96)
        self.preview_name.value = account.name
        self.preview_meta.value = f"{account.type_label} · {source_note}"

        self.history_row.controls.clear()
        records = self.manager.list_skins(account.id)
        if not records:
            self.history_row.controls.append(
                ft.Text("还没有上传过皮肤", size=9, color=FAINT)
            )
        for record in records:
            self.history_row.controls.append(self._history_card(account, record, selected))
        self.page.update()

    def _history_card(
        self,
        account: Account,
        record: SkinRecord,
        selected,
    ) -> ft.Container:
        is_selected = selected is not None and record.path == selected
        return ft.Container(
            width=140,
            bgcolor=PRIMARY_SOFT if is_selected else CARD,
            border=BORDER.all(1, PRIMARY if is_selected else BORDER_COLOR),
            border_radius=9,
            padding=8,
            content=ft.Column(
                controls=[
                    ft.Image(
                        src_base64=self.manager.full_skin_base64(record.path),
                        width=64,
                        height=64,
                        fit=ft.ImageFit.CONTAIN,
                    ),
                    ft.Text(record.title, size=8, color=MUTED, max_lines=1, width=120),
                    ft.Row(
                        controls=[
                            ft.TextButton(
                                **{TEXT_BUTTON_LABEL_FIELD: "使用"},
                                on_click=lambda _e, item=record: self._select(account, item),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=14,
                                icon_color=FAINT,
                                tooltip="删除",
                                on_click=lambda _e, item=record: self._remove(account, item),
                            ),
                        ],
                        spacing=0,
                    ),
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _pick_file(self, _event=None) -> None:
        if self._selected_account() is None:
            self.status.value = "请先选择账号"
            self.status.color = ERROR
            self.page.update()
            return
        self.file_picker.pick_files(
            dialog_title="选择 Minecraft 皮肤",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["png"],
            allow_multiple=False,
        )

    def _on_file_picked(self, event) -> None:
        account = self._selected_account()
        if account is None:
            return
        files = event.files or []
        if not files or not files[0].path:
            return
        try:
            record = self.manager.import_skin(account.id, files[0].path)
        except SkinError as exc:
            self.status.value = str(exc)
            self.status.color = ERROR
            self.page.update()
            return
        self.status.value = f"已上传并应用：{record.title}"
        self.status.color = PRIMARY
        self._changed()
        self._refresh()

    def _select(self, account: Account, record: SkinRecord) -> None:
        try:
            self.manager.select(account.id, record.path)
        except SkinError as exc:
            self.status.value = str(exc)
            self.status.color = ERROR
            self.page.update()
            return
        self.status.value = "已应用该皮肤"
        self.status.color = PRIMARY
        self._changed()
        self._refresh()

    def _remove(self, account: Account, record: SkinRecord) -> None:
        self.manager.remove(account.id, record.path)
        self.status.value = "已删除皮肤"
        self.status.color = MUTED
        self._changed()
        self._refresh()

    def _changed(self) -> None:
        if self.on_changed is not None:
            self.on_changed()

    def _close(self) -> None:
        if self.dialog is not None and self.dialog.open:
            self.page.close(self.dialog)
        try:
            self.page.overlay.remove(self.file_picker)
        except ValueError:
            pass
        self.page.update()

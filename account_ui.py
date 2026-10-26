"""账号管理弹窗：微软登录、离线登录、切换账号与登出。"""

from __future__ import annotations

import asyncio

import flet as ft

from account_manager import (
    Account,
    AccountStore,
    AccountStoreError,
    create_offline_account,
)
from skin_manager import avatar_base64
from skin_ui import SkinManagerDialog
from microsoft_auth import (
    DeviceCodeSession,
    DeviceCodeSlowDown,
    MicrosoftAuthError,
    complete_device_login,
    poll_device_login,
    start_device_login,
)
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

OUTLINED_BUTTON_LABEL_FIELD = (
    "text" if hasattr(ft.OutlinedButton, "text") else "content"
)
CONTENT_HEIGHT = 330


class AccountDialog:
    """账号管理界面。微软登录的网络操作全部在后台线程执行。"""

    def __init__(
        self,
        page: ft.Page,
        store: AccountStore,
        on_changed,
    ) -> None:
        self.page = page
        self.store = store
        self.on_changed = on_changed
        self._closed = False
        self.busy = False
        self._device_generation = 0
        self.device_session: DeviceCodeSession | None = None
        self._skin_dialog: SkinManagerDialog | None = None
        self._build()
        self._show_manager()

    @property
    def is_open(self) -> bool:
        return bool(self.dialog.open) and not self._closed

    # ---- 基础框架 --------------------------------------------------------
    def _build(self) -> None:
        self.close_button = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=18,
            icon_color=MUTED,
            tooltip="关闭",
            on_click=self._close,
        )
        self.title_text = ft.Text(
            "账号管理",
            size=18,
            color=TEXT,
            weight=ft.FontWeight.W_700,
        )
        self.subtitle_text = ft.Text(
            "登录、切换或登出账号",
            size=10,
            color=MUTED,
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
                                ft.Icons.MANAGE_ACCOUNTS_OUTLINED,
                                color=PRIMARY,
                                size=20,
                            ),
                        ),
                        ft.Column(
                            controls=[self.title_text, self.subtitle_text],
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

        self.dialog = ft.AlertDialog(
            modal=True,
            title=title,
            content=ft.Container(),
            content_padding=0,
            title_padding=PADDING.only(left=20, right=20, top=12),
            bgcolor=CARD,
            shape=ft.RoundedRectangleBorder(radius=18),
            inset_padding=24,
            on_dismiss=self._on_dismiss,
        )

    def _set_view(self, content: ft.Control, title: str, subtitle: str) -> None:
        self.title_text.value = title
        self.subtitle_text.value = subtitle
        self.dialog.content = content
        self.page.update()

    # ---- 账号管理主页 ----------------------------------------------------
    def _show_manager(self) -> None:
        active = self.store.active_account
        current_card = self._build_current_card(active)

        saved_rows: list[ft.Control] = [
            self._build_saved_account_row(account)
            for account in self.store.accounts
        ]
        if not saved_rows:
            saved_rows.append(
                ft.Container(
                    padding=PADDING.symmetric(vertical=16),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Text("还没有保存的账号", size=11, color=FAINT),
                )
            )

        saved_list = ft.ListView(
            width=688,
            height=96,
            spacing=4,
            padding=0,
            auto_scroll=False,
        )
        saved_list.controls.extend(saved_rows)

        left_actions = ft.Row(
            controls=(
                [
                    ft.TextButton(
                        **{TEXT_BUTTON_LABEL_FIELD: "登出当前账号"},
                        icon=ft.Icons.LOGOUT,
                        icon_color=ERROR,
                        style=ft.ButtonStyle(color=ERROR),
                        on_click=self._logout,
                    )
                ]
                if active is not None
                else []
            ),
            width=250,
            spacing=8,
        )

        right_actions = ft.Row(
            controls=[
                ft.FilledButton(
                    **{BUTTON_LABEL_FIELD: "微软登录"},
                    icon=ft.Icons.LOGIN,
                    bgcolor=PRIMARY,
                    color="#FFFFFF",
                    on_click=self._show_microsoft,
                ),
                ft.OutlinedButton(
                    **{OUTLINED_BUTTON_LABEL_FIELD: "离线登录"},
                    icon=ft.Icons.PERSON_OUTLINE,
                    on_click=self._show_offline,
                ),
                ft.OutlinedButton(
                    **{OUTLINED_BUTTON_LABEL_FIELD: "皮肤管理"},
                    icon=ft.Icons.PALETTE_OUTLINED,
                    on_click=self._open_skin_manager,
                ),
            ],
            spacing=8,
        )

        content = ft.Container(
            width=720,
            height=CONTENT_HEIGHT,
            bgcolor=BG,
            padding=PADDING.symmetric(horizontal=16, vertical=14),
            content=ft.Column(
                controls=[
                    current_card,
                    ft.Row(
                        controls=[
                            ft.Text("已保存账号", size=9, color=FAINT),
                            ft.Text(str(len(self.store.accounts)), size=9, color=FAINT),
                        ],
                        spacing=5,
                    ),
                    saved_list,
                    ft.Container(expand=True),
                    ft.Row(
                        controls=[left_actions, right_actions],
                        width=688,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=8,
                expand=True,
            ),
        )
        self._set_view(content, "账号管理", "登录、切换或登出账号")

    def _open_skin_manager(self, _event=None) -> None:
        if self._skin_dialog is not None and self._skin_dialog.is_open:
            return
        self._skin_dialog = SkinManagerDialog(
            self.page,
            self.store,
            on_changed=self._on_skin_changed,
        )
        self._skin_dialog.open()

    def _on_skin_changed(self) -> None:
        if self.dialog.open:
            self._show_manager()
        if self.on_changed is not None:
            self.on_changed()

    def _build_current_card(self, account: Account | None) -> ft.Container:
        if account is None:
            content = ft.Row(
                controls=[
                    _avatar(None, size=42),
                    ft.Column(
                        controls=[
                            ft.Text("未登录", size=15, color=TEXT, weight=ft.FontWeight.W_600),
                            ft.Text("登录微软账号或创建一个离线账号", size=10, color=MUTED),
                        ],
                        spacing=2,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        else:
            content = ft.Row(
                controls=[
                    _avatar(account, size=42),
                    ft.Column(
                        controls=[
                            ft.Text(
                                account.name,
                                size=16,
                                color=TEXT,
                                weight=ft.FontWeight.W_600,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=430,
                            ),
                            ft.Text(
                                f"{account.type_label} · {account.uuid}",
                                size=9,
                                color=MUTED,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=430,
                            ),
                        ],
                        spacing=2,
                    ),
                    ft.Container(
                        padding=PADDING.symmetric(horizontal=8, vertical=3),
                        border_radius=7,
                        bgcolor=PRIMARY_SOFT,
                        content=ft.Text("当前账号", size=9, color=PRIMARY),
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        return ft.Container(
            width=688,
            bgcolor=CARD,
            border=BORDER.all(1, BORDER_COLOR),
            border_radius=10,
            padding=12,
            content=content,
        )

    def _build_saved_account_row(self, account: Account) -> ft.Container:
        active_account = self.store.active_account
        active = active_account is not None and active_account.id == account.id
        return ft.Container(
            width=688,
            padding=PADDING.symmetric(horizontal=10, vertical=7),
            border_radius=8,
            border=BORDER.all(1, PRIMARY if active else BORDER_COLOR),
            bgcolor=PRIMARY_SOFT if active else CARD,
            ink=True,
            on_click=lambda _event, current=account: self._switch_account(current),
            content=ft.Row(
                controls=[
                    _avatar(account, size=26),
                    ft.Column(
                        controls=[
                            ft.Text(
                                account.name,
                                size=11,
                                color=TEXT,
                                weight=ft.FontWeight.W_600,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                width=430,
                            ),
                            ft.Text(account.type_label, size=9, color=MUTED),
                        ],
                        spacing=0,
                        width=470,
                    ),
                    ft.Text(
                        "当前" if active else "点击切换",
                        size=9,
                        color=PRIMARY if active else FAINT,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    # ---- 切换、登出 ------------------------------------------------------
    def _switch_account(self, account: Account) -> None:
        if self.busy:
            return
        try:
            state = self.store.set_active(account.id)
        except AccountStoreError as exc:
            self._show_snack(str(exc))
            return
        self.on_changed(state)
        self._show_manager()

    def _logout(self, _event=None) -> None:
        active = self.store.active_account
        if active is None:
            return
        try:
            state = self.store.remove_account(active.id)
        except AccountStoreError as exc:
            self._show_snack(str(exc))
            return
        self.on_changed(state)
        self._show_manager()

    def _show_snack(self, message: str) -> None:
        self.page.open(
            ft.SnackBar(
                content=ft.Text(message, color="#FFFFFF"),
                bgcolor=ERROR,
                duration=3500,
            )
        )

    # ---- 离线账号 --------------------------------------------------------
    def _show_offline(self, _event=None) -> None:
        self.offline_input = ft.TextField(
            width=420,
            height=42,
            dense=True,
            filled=True,
            bgcolor=CARD,
            border_color=BORDER_COLOR,
            focused_border_color=PRIMARY,
            border_radius=9,
            content_padding=PADDING.symmetric(horizontal=12, vertical=10),
            hint_text="3-16 位字母、数字或下划线",
            text_size=12,
            on_submit=self._offline_login,
        )
        self.offline_error = ft.Text("", size=10, color=ERROR, visible=False, width=520)

        content = ft.Container(
            width=720,
            height=CONTENT_HEIGHT,
            bgcolor=BG,
            padding=24,
            content=ft.Column(
                controls=[
                    ft.Text("离线账号", size=17, color=TEXT, weight=ft.FontWeight.W_600),
                    ft.Text(
                        "离线账号不需要微软认证，适合本地游戏或未开启正版验证的服务器。",
                        size=11,
                        color=MUTED,
                    ),
                    ft.Text("用户名", size=10, color=TEXT),
                    self.offline_input,
                    self.offline_error,
                    ft.Container(expand=True),
                    ft.Row(
                        controls=[
                            ft.TextButton(
                                **{TEXT_BUTTON_LABEL_FIELD: "返回账号管理"},
                                on_click=lambda _e: self._show_manager(),
                            ),
                            ft.FilledButton(
                                **{BUTTON_LABEL_FIELD: "登录离线账号"},
                                bgcolor=PRIMARY,
                                color="#FFFFFF",
                                on_click=self._offline_login,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.END,
                        spacing=8,
                    ),
                ],
                spacing=12,
                expand=True,
            ),
        )
        self._set_view(content, "离线账号", "使用本地用户名登录")

    def _offline_login(self, _event=None) -> None:
        username = (self.offline_input.value or "").strip()
        try:
            account = create_offline_account(username)
        except ValueError as exc:
            self.offline_error.value = str(exc)
            self.offline_error.visible = True
            self.page.update()
            return

        try:
            state = self.store.save_account(account, activate=True)
        except AccountStoreError as exc:
            self.offline_error.value = str(exc)
            self.offline_error.visible = True
            self.page.update()
            return

        self.on_changed(state)
        self._show_manager()

    # ---- 微软设备码登录 --------------------------------------------------
    def _show_microsoft(self, _event=None) -> None:
        self._device_generation += 1
        self.device_session = None
        self.busy = False
        self.close_button.disabled = False

        self.device_code_text = ft.Text(
            "正在获取…",
            size=24,
            font_family="Consolas",
            color=TEXT,
            weight=ft.FontWeight.W_700,
            text_align=ft.TextAlign.CENTER,
            selectable=True,
        )
        self.device_code_box = ft.Container(
            width=320,
            height=64,
            bgcolor=PRIMARY_SOFT,
            border=BORDER.all(1, "#B8D9C3"),
            border_radius=10,
            alignment=ft.Alignment(0, 0),
            content=self.device_code_text,
        )
        self.device_spinner = ft.ProgressRing(
            width=18,
            height=18,
            stroke_width=2.5,
            color=PRIMARY,
            visible=True,
        )
        self.device_status = ft.Text("正在获取设备验证码…", size=10, color=MUTED)
        self.device_error = ft.Text(
            "",
            size=10,
            color=ERROR,
            visible=False,
            width=620,
        )
        self.device_open_button = ft.FilledButton(
            **{BUTTON_LABEL_FIELD: "打开微软登录页面"},
            icon=ft.Icons.OPEN_IN_BROWSER,
            bgcolor=PRIMARY,
            color="#FFFFFF",
            disabled=True,
            on_click=self._open_device_page,
        )
        self.device_copy_button = ft.OutlinedButton(
            **{OUTLINED_BUTTON_LABEL_FIELD: "复制验证码"},
            icon=ft.Icons.CONTENT_COPY,
            disabled=True,
            on_click=self._copy_device_code,
        )
        self.device_retry_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "重新获取验证码"},
            visible=False,
            on_click=self._retry_device_login,
        )
        self.device_back_button = ft.TextButton(
            **{TEXT_BUTTON_LABEL_FIELD: "返回账号管理"},
            on_click=self._back_to_accounts,
        )

        content = ft.Container(
            width=720,
            height=CONTENT_HEIGHT,
            bgcolor=BG,
            padding=20,
            content=ft.Column(
                controls=[
                    ft.Text("微软账号登录", size=17, color=TEXT, weight=ft.FontWeight.W_600),
                    ft.Text(
                        "1. 点击“打开微软登录页面”，浏览器会自动打开。\n"
                        "2. 在网页中输入下方验证码，并按提示完成微软账号授权。\n"
                        "3. 授权成功后启动器会自动获取 Minecraft 凭证，无需复制链接。",
                        size=10,
                        color=MUTED,
                    ),
                    ft.Text("设备验证码", size=9, color=FAINT),
                    self.device_code_box,
                    ft.Row(
                        controls=[
                            self.device_open_button,
                            self.device_copy_button,
                            self.device_retry_button,
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.device_error,
                    ft.Row(
                        controls=[self.device_spinner, self.device_status],
                        spacing=7,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(expand=True),
                    ft.Row(
                        controls=[self.device_back_button],
                        alignment=ft.MainAxisAlignment.END,
                    ),
                ],
                spacing=8,
                expand=True,
            ),
        )
        self._set_view(content, "微软账号登录", "设备码登录，无需复制回调地址")
        self.page.run_task(self._request_device_code_async, self._device_generation)

    def _device_active(self, generation: int) -> bool:
        return (
            not self._closed
            and generation == self._device_generation
            and bool(self.dialog.open)
        )

    async def _request_device_code_async(self, generation: int) -> None:
        try:
            session = await asyncio.to_thread(start_device_login)
        except MicrosoftAuthError as exc:
            self._device_error(str(exc), generation)
            return
        except Exception as exc:
            self._device_error(f"获取设备验证码失败：{exc}", generation)
            return

        if not self._device_active(generation):
            return

        self.device_session = session
        self.device_code_text.value = session.user_code
        self.device_status.value = (
            f"验证码已生成，有效约 {max(1, session.expires_in // 60)} 分钟"
        )
        self.device_error.visible = False
        self.device_open_button.disabled = False
        self.device_copy_button.disabled = False
        self.device_spinner.visible = True
        self.page.update()
        self._open_device_page()
        self.page.run_task(self._poll_device_async, session, generation)

    async def _poll_device_async(
        self,
        session: DeviceCodeSession,
        generation: int,
    ) -> None:
        interval = max(5, session.interval)

        while self._device_active(generation):
            remaining = session.remaining_seconds()
            if remaining <= 0:
                self._device_error("设备验证码已过期，请重新获取", generation)
                return

            self.device_status.value = (
                f"等待你在浏览器中授权… 剩余 {remaining // 60:02d}:{remaining % 60:02d}"
            )
            self.page.update()
            await asyncio.sleep(interval)

            if not self._device_active(generation):
                return

            try:
                token_data = await asyncio.to_thread(poll_device_login, session)
            except DeviceCodeSlowDown:
                interval += 5
                continue
            except MicrosoftAuthError as exc:
                self._device_error(str(exc), generation)
                return
            except Exception as exc:
                self._device_error(f"登录失败：{exc}", generation)
                return

            if token_data is None:
                continue

            await self._finish_device_login_async(token_data, generation)
            return

    async def _finish_device_login_async(
        self,
        token_data: dict,
        generation: int,
    ) -> None:
        if not self._device_active(generation):
            return

        self.busy = True
        self.close_button.disabled = True
        self.device_back_button.disabled = True
        self.device_open_button.disabled = True
        self.device_copy_button.disabled = True
        self.device_retry_button.visible = False
        self.device_error.visible = False
        self.device_spinner.visible = True
        self.device_status.value = "授权成功，正在获取 Minecraft 凭证…"
        self.page.update()

        try:
            data = await asyncio.to_thread(complete_device_login, token_data)
        except MicrosoftAuthError as exc:
            self._device_error(str(exc), generation)
            return
        except Exception as exc:
            self._device_error(f"登录失败：{exc}", generation)
            return

        if not self._device_active(generation):
            return

        account = Account(
            id=data.account_id,
            account_type="microsoft",
            name=data.name,
            uuid=data.account_id,
            access_token=data.access_token,
            refresh_token=data.refresh_token,
            skin_url=data.skin_url,
            client_id=data.client_id,
        )
        try:
            state = self.store.save_account(account, activate=True)
        except AccountStoreError as exc:
            self._device_error(str(exc), generation)
            return

        self.busy = False
        self.close_button.disabled = False
        self.on_changed(state)
        self._show_manager()

    def _device_error(self, message: str, generation: int) -> None:
        if not self._device_active(generation):
            return
        self.busy = False
        self.close_button.disabled = False
        self.device_back_button.disabled = False
        self.device_spinner.visible = False
        self.device_status.value = "登录失败"
        self.device_error.value = message
        self.device_error.visible = True
        self.device_open_button.disabled = True
        self.device_copy_button.disabled = True
        self.device_retry_button.visible = True
        self.page.update()

    def _open_device_page(self, _event=None) -> None:
        if self.device_session is None:
            return
        try:
            self.page.launch_url(self.device_session.verification_uri)
        except Exception as exc:
            self._show_device_inline_error(f"无法打开浏览器：{exc}")

    def _copy_device_code(self, _event=None) -> None:
        if self.device_session is None:
            return
        try:
            self.page.set_clipboard(self.device_session.user_code)
            self.device_status.value = "验证码已复制，请粘贴到浏览器"
        except Exception as exc:
            self._show_device_inline_error(f"复制失败：{exc}")
        self.page.update()

    def _show_device_inline_error(self, message: str) -> None:
        self.device_error.value = message
        self.device_error.visible = True
        self.page.update()

    def _retry_device_login(self, _event=None) -> None:
        if self.busy:
            return
        self._show_microsoft()

    def _back_to_accounts(self, _event=None) -> None:
        if self.busy:
            return
        self._device_generation += 1
        self.device_session = None
        self._show_manager()

    # ---- 打开/关闭 -------------------------------------------------------
    def open(self) -> None:
        self.page.open(self.dialog)
        self.page.update()

    def _on_dismiss(self, _event=None) -> None:
        if not self.busy:
            self._device_generation += 1
            self._closed = True

    def _close(self, _event=None) -> None:
        if self.busy:
            return
        self._device_generation += 1
        self._closed = True
        self.page.close(self.dialog)
        self.page.update()


def account_avatar(account: Account | None, size: int = 32) -> ft.Container:
    """侧栏/顶部账号组件使用的圆形皮肤头像。"""

    if account is None:
        return ft.Container(
            width=size,
            height=size,
            border_radius=size / 2,
            bgcolor="#2A5A41",
            alignment=ft.Alignment(0, 0),
            content=ft.Icon(
                ft.Icons.PERSON_OUTLINE,
                size=size * 0.55,
                color="#D6E7DC",
            ),
        )
    return ft.Container(
        width=size,
        height=size,
        border_radius=size / 2,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=SURFACE,
        alignment=ft.Alignment(0, 0),
        content=ft.Image(
            src_base64=avatar_base64(account, max(size, 32)),
            width=size,
            height=size,
            fit=ft.ImageFit.COVER,
            border_radius=size / 2,
        ),
    )


def _avatar(account: Account | None, size: int = 32) -> ft.Container:
    """账号弹窗内使用的圆形皮肤头像。"""

    if account is None:
        return ft.Container(
            width=size,
            height=size,
            border_radius=size / 2,
            bgcolor=SURFACE,
            border=BORDER.all(1, BORDER_COLOR),
            alignment=ft.Alignment(0, 0),
            content=ft.Icon(ft.Icons.PERSON_OUTLINE, size=size * 0.55, color=MUTED),
        )
    return ft.Container(
        width=size,
        height=size,
        border_radius=size / 2,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=PRIMARY_SOFT,
        border=BORDER.all(1, BORDER_COLOR),
        alignment=ft.Alignment(0, 0),
        content=ft.Image(
            src_base64=avatar_base64(account, max(size, 32)),
            width=size,
            height=size,
            fit=ft.ImageFit.COVER,
            border_radius=size / 2,
        ),
    )

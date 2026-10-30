"""账号数据模型与 JSON 持久化。

账号文件默认位置：
    %APPDATA%\\NLMCL\\accounts.json

文件中会保存微软账号的 access_token / refresh_token。文件是本机私密数据，
不要把 accounts.json 提交到版本库或发给别人。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid as uuid_module
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ACCOUNT_FILE_VERSION = 1
OFFLINE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,16}$")


class AccountStoreError(Exception):
    """账号文件读写失败。"""


@dataclass(slots=True)
class Account:
    """一个已保存的账号。"""

    id: str
    account_type: str  # microsoft / offline
    name: str
    uuid: str
    access_token: str = ""
    refresh_token: str = ""
    skin_url: str = ""
    client_id: str = ""

    @property
    def is_microsoft(self) -> bool:
        return self.account_type == "microsoft"

    @property
    def type_label(self) -> str:
        return "微软正版" if self.is_microsoft else "离线账号"

    @property
    def initial(self) -> str:
        return (self.name or "?")[0].upper()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.account_type,
            "name": self.name,
            "uuid": self.uuid,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "skin_url": self.skin_url,
            "client_id": self.client_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Account | None":
        if not isinstance(data, dict):
            return None
        account_id = data.get("id")
        account_type = data.get("type")
        name = data.get("name")
        account_uuid = data.get("uuid")
        if not all(isinstance(value, str) and value for value in (
            account_id,
            account_type,
            name,
            account_uuid,
        )):
            return None
        if account_type not in ("microsoft", "offline"):
            return None
        return cls(
            id=account_id,
            account_type=account_type,
            name=name,
            uuid=account_uuid,
            access_token=str(data.get("access_token") or ""),
            refresh_token=str(data.get("refresh_token") or ""),
            skin_url=str(data.get("skin_url") or ""),
            client_id=str(data.get("client_id") or ""),
        )


@dataclass(slots=True)
class AccountState:
    accounts: list[Account] = field(default_factory=list)
    active_id: str | None = None

    def active_account(self) -> Account | None:
        if not self.active_id:
            return None
        for account in self.accounts:
            if account.id == self.active_id:
                return account
        return None


def default_accounts_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "NLMCL" / "accounts.json"
    return Path.home() / ".nlcl" / "accounts.json"


def create_offline_account(username: str) -> Account:
    """创建离线账号。用户名限制为 3-16 位字母/数字/下划线。"""

    name = (username or "").strip()
    if not OFFLINE_NAME_PATTERN.fullmatch(name):
        raise ValueError("离线用户名需要 3-16 位，只能包含字母、数字和下划线")

    offline_uuid = _offline_uuid(name)
    return Account(
        id=offline_uuid,
        account_type="offline",
        name=name,
        uuid=offline_uuid,
    )


class AccountStore:
    """账号列表与当前账号的持久化管理。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_accounts_path()
        self._lock = threading.Lock()
        self._loaded_from_temp = False
        self.state = self._load()
        if self._loaded_from_temp:
            # 上次写入在 rename/copy 阶段失败时，临时文件里仍是完整账号数据。
            # 启动时顺便把它提升为正式文件，避免用户再次登录。
            try:
                self._save()
            except AccountStoreError:
                pass

    @property
    def accounts(self) -> list[Account]:
        return self.state.accounts

    @property
    def active_account(self) -> Account | None:
        return self.state.active_account()

    def reload(self) -> AccountState:
        with self._lock:
            self.state = self._load()
            return self.state

    def save_account(self, account: Account, *, activate: bool = True) -> AccountState:
        """新增或更新账号，默认设为当前账号。"""

        with self._lock:
            accounts = list(self.state.accounts)
            for index, existing in enumerate(accounts):
                if existing.id == account.id:
                    accounts[index] = account
                    break
            else:
                accounts.append(account)

            active_id = account.id if activate else self.state.active_id
            if active_id and not any(item.id == active_id for item in accounts):
                active_id = accounts[0].id if accounts else None

            self.state = AccountState(accounts=accounts, active_id=active_id)
            self._save()
            return self.state

    def set_active(self, account_id: str) -> AccountState:
        with self._lock:
            if not any(account.id == account_id for account in self.state.accounts):
                raise AccountStoreError("账号不存在")
            self.state.active_id = account_id
            self._save()
            return self.state

    def remove_account(self, account_id: str) -> AccountState:
        """删除账号及其凭证，并在必要时自动切换到下一个账号。"""

        with self._lock:
            accounts = [account for account in self.state.accounts if account.id != account_id]
            active_id = self.state.active_id
            if active_id == account_id:
                active_id = accounts[0].id if accounts else None
            self.state = AccountState(accounts=accounts, active_id=active_id)
            self._save()
            return self.state

    def _load(self) -> AccountState:
        self._loaded_from_temp = False
        source = self.path
        if not source.is_file():
            temp_path = self.path.with_name(self.path.name + ".tmp")
            if not temp_path.is_file():
                return AccountState()
            # 兼容上次保存中断留下的临时文件。
            source = temp_path
            self._loaded_from_temp = True

        try:
            data = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            backup_corrupt_account_file(source)
            return AccountState()

        if not isinstance(data, dict):
            backup_corrupt_account_file(source)
            return AccountState()

        accounts: list[Account] = []
        raw_accounts = data.get("accounts")
        if isinstance(raw_accounts, list):
            for raw_account in raw_accounts:
                account = Account.from_dict(raw_account)
                if account is not None and not any(item.id == account.id for item in accounts):
                    accounts.append(account)

        active_id = data.get("active_id")
        if not isinstance(active_id, str) or not any(
            account.id == active_id for account in accounts
        ):
            active_id = accounts[0].id if accounts else None

        return AccountState(accounts=accounts, active_id=active_id)

    def _save(self) -> None:
        data = {
            "version": ACCOUNT_FILE_VERSION,
            "active_id": self.state.active_id,
            "accounts": [account.to_dict() for account in self.state.accounts],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(self.path.name + ".tmp")
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # Windows Store / MSIX 版 Python 会把 %APPDATA% 重定向到
            # D:\WpSystem\...\LocalCache。此时源路径和目标路径看起来在同一个
            # 目录，但 os.replace() 会报 WinError 17（不同磁盘驱动器）。
            # 用复制代替原子重命名，兼容普通安装和 MSIX 重定向环境。
            shutil.copyfile(temp_path, self.path)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            raise AccountStoreError(f"账号保存失败：{exc}") from exc


def backup_corrupt_account_file(path: Path) -> Path | None:
    """把损坏的账号文件备份一份，避免下次直接覆盖。"""

    if not path.is_file():
        return None
    target = path.with_name(
        f"{path.name}.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    try:
        shutil.copy2(path, target)
        return target
    except OSError:
        return None


def _offline_uuid(name: str) -> str:
    """生成 Java 版标准离线 UUID。"""

    digest = hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest()
    raw = bytearray(digest)
    raw[6] = (raw[6] & 0x0F) | 0x30
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid_module.UUID(bytes=bytes(raw)))

"""账号皮肤管理：上传、历史、账号选择和 2D 头像渲染。"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from account_manager import Account


def default_skin_root() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "NLMCL" / "skins"


@dataclass(frozen=True, slots=True)
class SkinRecord:
    path: Path
    size: int
    modified: float

    @property
    def title(self) -> str:
        return self.path.name


class SkinError(Exception):
    pass


class SkinManager:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else default_skin_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.selections_path = self.root / "selections.json"
        self.selections: dict[str, str] = {}
        self._load()

    # ---- 皮肤文件 --------------------------------------------------------
    def validate(self, path: str | Path) -> tuple[int, int]:
        image_path = Path(path)
        if image_path.suffix.lower() != ".png":
            raise SkinError("皮肤必须是 PNG 图片")
        try:
            with Image.open(image_path) as image:
                width, height = image.size
                if image.format != "PNG":
                    raise SkinError("皮肤必须是 PNG 图片")
        except SkinError:
            raise
        except Exception as exc:
            raise SkinError(f"无法读取图片：{exc}") from exc
        if (width, height) not in ((64, 64), (64, 32)):
            raise SkinError(
                f"皮肤尺寸必须为 64×64 或 64×32，当前为 {width}×{height}"
            )
        return width, height

    def import_skin(self, account_id: str, source: str | Path) -> SkinRecord:
        self.validate(source)
        directory = self._account_dir(account_id)
        directory.mkdir(parents=True, exist_ok=True)
        raw = Path(source).read_bytes()
        digest = hashlib.sha1(raw).hexdigest()[:10]
        target = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{digest}.png"
        target.write_bytes(raw)
        self.select(account_id, target)
        return SkinRecord(target, target.stat().st_size, target.stat().st_mtime)

    def list_skins(self, account_id: str) -> list[SkinRecord]:
        directory = self._account_dir(account_id)
        records: list[SkinRecord] = []
        if not directory.is_dir():
            return records
        for item in directory.glob("*.png"):
            try:
                self.validate(item)
                records.append(
                    SkinRecord(item, item.stat().st_size, item.stat().st_mtime)
                )
            except SkinError:
                continue
        records.sort(key=lambda item: item.modified, reverse=True)
        return records

    def select(self, account_id: str, path: str | Path) -> None:
        target = Path(path)
        self.validate(target)
        self.selections[account_id] = str(target)
        self._save()

    def selected(self, account_id: str) -> Path | None:
        raw = self.selections.get(account_id)
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_file() else None

    def remove(self, account_id: str, path: str | Path) -> None:
        target = Path(path)
        root = self._account_dir(account_id).resolve()
        try:
            resolved = target.resolve()
        except Exception:
            return
        if resolved.parent == root and resolved.is_file():
            resolved.unlink(missing_ok=True)
        if self.selections.get(account_id) == str(target):
            self.selections.pop(account_id, None)
            self._save()

    # ---- 头像 ------------------------------------------------------------
    def avatar_base64(self, account: Account | None, size: int = 64) -> str:
        skin_path = self._skin_for_account(account)
        if skin_path is None:
            skin_path = self._ensure_default_skin()
        try:
            return _face_base64(skin_path, size)
        except Exception:
            return _face_base64(self._ensure_default_skin(), size)

    def full_skin_base64(self, path: str | Path) -> str:
        with Image.open(path) as image:
            buffer = io.BytesIO()
            image.convert("RGBA").save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _skin_for_account(self, account: Account | None) -> Path | None:
        if account is None:
            return None
        if account.is_microsoft and account.skin_url:
            cached = self._cached_remote(account.skin_url)
            if cached is not None:
                return cached
        selected = self.selected(account.id)
        if selected is not None:
            return selected
        return None

    def prefetch(self, account: Account | None) -> None:
        """后台预取微软官方皮肤，避免构建头像时阻塞 UI。"""

        if (
            account is not None
            and account.is_microsoft
            and account.skin_url
            and self._cached_remote(account.skin_url) is None
        ):
            self._remote_skin(account.skin_url)

    def _cached_remote(self, url: str) -> Path | None:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        path = self.root / "remote" / f"{digest}.png"
        return path if path.is_file() else None

    def _remote_skin(self, url: str) -> Path | None:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        cache_dir = self.root / "remote"
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"{digest}.png"
        if path.is_file():
            return path
        try:
            response = requests.get(url, timeout=12)
            response.raise_for_status()
            if not response.content.startswith(b"\x89PNG"):
                return None
            path.write_bytes(response.content)
            self.validate(path)
            return path
        except Exception:
            return None

    def _ensure_default_skin(self) -> Path:
        # 使用随程序附带的 Minecraft 标准史蒂夫皮肤，避免旧版缓存中的错误头像。
        asset = Path(__file__).resolve().parent / "assets" / "steve.png"
        if asset.is_file():
            return asset
        path = self.root / "default-steve.png"
        if path.is_file():
            return path
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        # 64×64 皮肤头部正面位于 (8,8)-(16,16)，帽子层位于 (40,8)。
        face = [
            "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E",
            "#3B2A1E", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#3B2A1E",
            "#3B2A1E", "#B98A6A", "#FFFFFF", "#2F62A8", "#2F62A8", "#FFFFFF", "#B98A6A", "#3B2A1E",
            "#3B2A1E", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#3B2A1E",
            "#3B2A1E", "#B98A6A", "#B98A6A", "#7B4B36", "#7B4B36", "#B98A6A", "#B98A6A", "#3B2A1E",
            "#3B2A1E", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#3B2A1E",
            "#3B2A1E", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#B98A6A", "#3B2A1E",
            "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E", "#3B2A1E",
        ]
        for index, color in enumerate(face):
            x = 8 + index % 8
            y = 8 + index // 8
            draw.point((x, y), fill=color)
        image.save(path, format="PNG")
        return path

    def _account_dir(self, account_id: str) -> Path:
        safe = "".join(
            char if char.isalnum() or char in "-_." else "_"
            for char in account_id
        )
        return self.root / (safe or "unknown")

    def _load(self) -> None:
        try:
            data = json.loads(self.selections_path.read_text(encoding="utf-8-sig"))
        except Exception:
            self.selections = {}
            return
        self.selections = (
            {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
            if isinstance(data, dict)
            else {}
        )

    def _save(self) -> None:
        self.selections_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.selections_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self.selections, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        import shutil

        shutil.copyfile(temp, self.selections_path)
        temp.unlink(missing_ok=True)


def _face_base64(skin_path: str | Path, size: int = 64) -> str:
    with Image.open(skin_path) as source:
        image = source.convert("RGBA")
    face = image.crop((8, 8, 16, 16))
    # 64×64 皮肤有帽子/头发叠加层；64×32 只有基础头部。
    if image.height >= 64:
        hat = image.crop((40, 8, 48, 16))
        face.alpha_composite(hat)
    face = face.resize((max(size, 8), max(size, 8)), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    face.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


_default_manager: SkinManager | None = None


def get_skin_manager() -> SkinManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = SkinManager()
    return _default_manager


def avatar_base64(account: Account | None, size: int = 64) -> str:
    return get_skin_manager().avatar_base64(account, size)

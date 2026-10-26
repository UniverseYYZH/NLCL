"""NLCL 独立实例注册表：Modrinth 整合包导入后的实例根目录。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def default_registry_file() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "NLCL" / "instances" / "instances.json"


class InstanceRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_registry_file()
        self.items: list[dict] = []
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception:
            self.items = []
            return
        self.items = [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def add(
        self,
        name: str,
        root: str | Path,
        version_folder: str,
        *,
        loader: str = "",
        minecraft_version: str = "",
    ) -> dict:
        entry = {
            "id": f"instance-{int(time.time())}-{len(self.items) + 1}",
            "name": name,
            "root": str(Path(root)),
            "version_folder": version_folder,
            "loader": loader,
            "minecraft_version": minecraft_version,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.items.append(entry)
        self._save()
        return entry

    def roots(self) -> list[Path]:
        roots = []
        for item in self.items:
            root = Path(str(item.get("root") or ""))
            if root.is_dir():
                roots.append(root)
        return roots

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self.items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        import shutil

        shutil.copyfile(temp, self.path)
        temp.unlink(missing_ok=True)

"""实例级 Java 绑定（不修改全局「Java 与启动」设置）。"""

from __future__ import annotations

import json
import os
from pathlib import Path


def default_binding_file() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "NLMCL" / "instance_java.json"


class JavaBindingStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_binding_file()
        self.bindings: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception:
            self.bindings = {}
            return
        if isinstance(data, dict):
            self.bindings = {
                str(key): value
                for key, value in data.items()
                if isinstance(value, dict)
            }
        else:
            self.bindings = {}

    def get(self, folder_name: str) -> dict | None:
        value = self.bindings.get(folder_name)
        if not isinstance(value, dict):
            return None
        path = value.get("path")
        major = value.get("major")
        if not isinstance(path, str) or not Path(path).is_file():
            return None
        try:
            major = int(major)
        except (TypeError, ValueError):
            return None
        return {
            "path": path,
            "major": major,
            "component": str(value.get("component") or ""),
        }

    def set(
        self,
        folder_name: str,
        java_path: str,
        major: int,
        component: str = "",
    ) -> None:
        self.bindings[folder_name] = {
            "path": str(java_path),
            "major": int(major),
            "component": component,
        }
        self._save()

    def remove(self, folder_name: str) -> None:
        if self.bindings.pop(folder_name, None) is not None:
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self.bindings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # AppData 可能被 Windows Store Python 重定向到另一个盘，不能用 os.replace。
        import shutil

        shutil.copyfile(temp, self.path)
        temp.unlink(missing_ok=True)

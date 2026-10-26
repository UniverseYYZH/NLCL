"""全局设置存储：下载目录、限速、日志偏好。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def default_app_settings_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "NLCL" / "app_settings.json"


@dataclass(slots=True)
class AppSettings:
    download_directory: str = ""
    download_limit_kbps: int = 0
    log_max_lines: int = 5000
    log_auto_scroll: bool = True

    def normalized(self) -> "AppSettings":
        return AppSettings(
            download_directory=self.download_directory.strip(),
            download_limit_kbps=max(0, int(self.download_limit_kbps or 0)),
            log_max_lines=min(max(int(self.log_max_lines or 5000), 500), 20000),
            log_auto_scroll=bool(self.log_auto_scroll),
        )


class AppSettingsStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_app_settings_path()
        self.settings = self.load()

    def load(self) -> AppSettings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception:
            return AppSettings()
        if not isinstance(data, dict):
            return AppSettings()
        return AppSettings(
            download_directory=str(data.get("download_directory") or ""),
            download_limit_kbps=_to_int(data.get("download_limit_kbps"), 0),
            log_max_lines=_to_int(data.get("log_max_lines"), 5000),
            log_auto_scroll=bool(data.get("log_auto_scroll", True)),
        ).normalized()

    def save(self, settings: AppSettings) -> AppSettings:
        normalized = settings.normalized()
        self.settings = normalized
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "download_directory": normalized.download_directory,
            "download_limit_kbps": normalized.download_limit_kbps,
            "log_max_lines": normalized.log_max_lines,
            "log_auto_scroll": normalized.log_auto_scroll,
        }
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        import shutil

        shutil.copyfile(temp, self.path)
        temp.unlink(missing_ok=True)
        return normalized


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

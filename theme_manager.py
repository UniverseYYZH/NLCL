"""NLMCL 全局配色主题：三套主题、持久化与已加载 UI 模块热替换。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import flet as ft

DEFAULT_THEME = "sage"

THEME_LABELS = {
    "dark": "深色原版",
    "light": "浅色",
    "sage": "柔和灰绿",
}

PALETTES: dict[str, dict[str, str]] = {
    "sage": {
        "BG": "#F4F6F1",
        "CARD": "#FFFFFF",
        "SURFACE": "#F8FAF7",
        "BORDER_COLOR": "#E4E9E2",
        "TEXT": "#17231B",
        "MUTED": "#68776D",
        "FAINT": "#96A29A",
        "PRIMARY": "#2F6B4F",
        "PRIMARY_SOFT": "#E8F1EA",
        "SIDEBAR_BG": "#173B2B",
        "SIDEBAR_ACTIVE": "#285A41",
        "SIDEBAR_TEXT": "#F4FAF6",
        "SIDEBAR_MUTED": "#9DB5A6",
        "AMBER": "#966000",
        "AMBER_BG": "#FFF6E2",
        "AMBER_BORDER": "#EFDDB5",
        "SNAPSHOT": "#A85F00",
        "SNAPSHOT_BG": "#FFF1DA",
        "OLD": "#5D6B61",
        "OLD_BG": "#EFF2EE",
        "ERROR": "#B42318",
        "ERROR_BG": "#FEF3F2",
        "ERROR_BORDER": "#F3C7C3",
        "CONSOLE_BG": "#101E16",
        "CONSOLE_TEXT": "#C9D8CF",
        "SUCCESS": "#2E7D5B",
        "WARN": "#F2C96D",
    },
    "light": {
        "BG": "#F5F8FC",
        "CARD": "#FFFFFF",
        "SURFACE": "#EEF3F9",
        "BORDER_COLOR": "#DDE6F0",
        "TEXT": "#172433",
        "MUTED": "#5F7085",
        "FAINT": "#94A2B5",
        "PRIMARY": "#2E6BE6",
        "PRIMARY_SOFT": "#E8F0FF",
        "SIDEBAR_BG": "#1D2A44",
        "SIDEBAR_ACTIVE": "#30466D",
        "SIDEBAR_TEXT": "#F3F7FF",
        "SIDEBAR_MUTED": "#9FB1CA",
        "AMBER": "#976000",
        "AMBER_BG": "#FFF6E2",
        "AMBER_BORDER": "#EFDDB5",
        "SNAPSHOT": "#A85F00",
        "SNAPSHOT_BG": "#FFF1DA",
        "OLD": "#5D6B7E",
        "OLD_BG": "#EDF1F6",
        "ERROR": "#B42318",
        "ERROR_BG": "#FEF3F2",
        "ERROR_BORDER": "#F3C7C3",
        "CONSOLE_BG": "#0E1828",
        "CONSOLE_TEXT": "#CBD8EA",
        "SUCCESS": "#1F7A52",
        "WARN": "#F2C96D",
    },
    "dark": {
        "BG": "#0F1512",
        "CARD": "#17211B",
        "SURFACE": "#1C2820",
        "BORDER_COLOR": "#2B3A31",
        "TEXT": "#EDF6EF",
        "MUTED": "#A2B5A8",
        "FAINT": "#73877A",
        "PRIMARY": "#66C894",
        "PRIMARY_SOFT": "#1E3A2A",
        "SIDEBAR_BG": "#09110C",
        "SIDEBAR_ACTIVE": "#1A4A33",
        "SIDEBAR_TEXT": "#F1FAF4",
        "SIDEBAR_MUTED": "#8EAA9A",
        "AMBER": "#F2C96D",
        "AMBER_BG": "#2A2415",
        "AMBER_BORDER": "#4A3D1E",
        "SNAPSHOT": "#F2B35E",
        "SNAPSHOT_BG": "#2B2214",
        "OLD": "#A7B8AC",
        "OLD_BG": "#26332B",
        "ERROR": "#FF9B8A",
        "ERROR_BG": "#2D1A19",
        "ERROR_BORDER": "#5A302D",
        "CONSOLE_BG": "#070D09",
        "CONSOLE_TEXT": "#C9D8CF",
        "SUCCESS": "#7FE0A5",
        "WARN": "#F2C96D",
    },
}

_UI_MODULES = {
    "main",
    "download_ui",
    "account_ui",
    "skin_ui",
    "launch_console_ui",
    "multiplayer_ui",
    "snapshot_ui",
    "lan_scan_ui",
    "settings_ui",
    "launch_settings_ui",
    "version_details_ui",
    "ui_theme",
}


def default_theme_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "NLMCL" / "ui_theme.json"


class ThemeStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_theme_path()
        self.name = self.load()

    def load(self) -> str:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            name = data.get("theme") if isinstance(data, dict) else None
            if name in PALETTES:
                return str(name)
        except Exception:
            pass
        return DEFAULT_THEME

    def save(self, name: str) -> None:
        if name not in PALETTES:
            name = DEFAULT_THEME
        self.name = name
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps({"theme": name}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        import shutil

        shutil.copyfile(temp, self.path)
        temp.unlink(missing_ok=True)


def apply_theme(name: str) -> dict[str, str]:
    """把主题颜色写回已加载 UI 模块的全局变量。

    这样旧的弹窗模块不需要重新导入，下一次构建控件时就会使用新颜色。
    """

    palette = PALETTES.get(name, PALETTES[DEFAULT_THEME])
    for module_name in _UI_MODULES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for key, value in palette.items():
            if hasattr(module, key):
                setattr(module, key, value)
        if hasattr(module, "TYPE_STYLES"):
            setattr(
                module,
                "TYPE_STYLES",
                {
                    "release": (palette["PRIMARY"], palette["PRIMARY_SOFT"], ft.Icons.INVENTORY_2_OUTLINED),
                    "snapshot": (palette["SNAPSHOT"], palette["SNAPSHOT_BG"], ft.Icons.SCIENCE_OUTLINED),
                    "old_beta": (palette["OLD"], palette["OLD_BG"], ft.Icons.HISTORY),
                    "old_alpha": (palette["OLD"], palette["OLD_BG"], ft.Icons.HISTORY),
                },
            )
    return palette


def theme_mode(name: str) -> ft.ThemeMode:
    return ft.ThemeMode.DARK if name == "dark" else ft.ThemeMode.LIGHT

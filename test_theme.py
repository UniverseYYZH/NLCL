"""主题持久化测试。"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from theme_manager import PALETTES, ThemeStore, apply_theme


class ThemeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"theme-{uuid4().hex}"

    def tearDown(self) -> None:
        apply_theme("sage")
        shutil.rmtree(self.root, ignore_errors=True)

    def test_save_and_load(self) -> None:
        store = ThemeStore(self.root / "theme.json")
        self.assertIn(store.name, PALETTES)
        store.save("dark")
        reopened = ThemeStore(self.root / "theme.json")
        self.assertEqual(reopened.name, "dark")

    def test_apply_theme(self) -> None:
        import main

        palette = apply_theme("light")
        self.assertEqual(main.BG, palette["BG"])
        self.assertEqual(main.PRIMARY, palette["PRIMARY"])


if __name__ == "__main__":
    unittest.main()

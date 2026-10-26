"""全局设置与下载限速配置测试。"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from app_settings import AppSettings, AppSettingsStore
from download_throttle import get_download_limit, set_download_limit


class AppSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"settings-{uuid4().hex}"

    def tearDown(self) -> None:
        set_download_limit(0)
        shutil.rmtree(self.root, ignore_errors=True)

    def test_save_and_load(self) -> None:
        store = AppSettingsStore(self.root / "app.json")
        store.save(
            AppSettings(
                download_directory="D:/MC",
                download_limit_kbps=1024,
                log_max_lines=8000,
                log_auto_scroll=False,
            )
        )
        loaded = AppSettingsStore(self.root / "app.json").settings
        self.assertEqual(loaded.download_directory, "D:/MC")
        self.assertEqual(loaded.download_limit_kbps, 1024)
        self.assertEqual(loaded.log_max_lines, 8000)
        self.assertFalse(loaded.log_auto_scroll)

    def test_download_limit_global(self) -> None:
        set_download_limit(2048)
        self.assertEqual(get_download_limit(), 2048)


if __name__ == "__main__":
    unittest.main()

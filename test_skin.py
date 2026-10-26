"""皮肤管理测试：格式校验、上传、账号选择和头像渲染。"""

from __future__ import annotations

import base64
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from PIL import Image

from account_manager import create_offline_account
from skin_manager import SkinError, SkinManager, avatar_base64


class SkinTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"skin-{uuid4().hex}"
        self.root.mkdir(parents=True)
        self.manager = SkinManager(self.root / "skins")
        self.account = create_offline_account("Tester")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _png(self, name: str, size=(64, 64)) -> Path:
        path = self.root / name
        Image.new("RGBA", size, (120, 80, 60, 255)).save(path, format="PNG")
        return path

    def test_import_select_and_history(self) -> None:
        path = self._png("custom.png")
        record = self.manager.import_skin(self.account.id, path)
        self.assertTrue(record.path.is_file())
        self.assertEqual(self.manager.selected(self.account.id), record.path)
        history = self.manager.list_skins(self.account.id)
        self.assertEqual(len(history), 1)

        raw = base64.b64decode(self.manager.avatar_base64(self.account, 64))
        self.assertTrue(raw.startswith(b"\x89PNG"))

    def test_64x32_and_invalid_size(self) -> None:
        legacy = self._png("legacy.png", (64, 32))
        self.manager.validate(legacy)
        invalid = self._png("bad.png", (32, 32))
        with self.assertRaises(SkinError):
            self.manager.validate(invalid)

    def test_default_steve_for_no_skin(self) -> None:
        raw = base64.b64decode(avatar_base64(self.account, 64))
        self.assertTrue(raw.startswith(b"\x89PNG"))
        asset = Path(__file__).resolve().parent / "assets" / "steve.png"
        self.assertTrue(asset.is_file())
        self.assertEqual(self.manager._ensure_default_skin().resolve(), asset.resolve())
        with Image.open(asset) as image:
            self.assertEqual(image.size, (64, 64))


if __name__ == "__main__":
    unittest.main()

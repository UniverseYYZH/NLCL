"""版本详情扫描与安全删除的单元测试。"""

from __future__ import annotations

import json
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from version_details import (
    VersionDeleteError,
    delete_version_folder,
    scan_version_details,
)
from version_scanner import LocalVersion


class VersionDetailsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"details-{uuid4().hex}"
        self.versions = self.root / "versions"
        self.versions.mkdir(parents=True)
        self.version_dir = self.versions / "1.20.1"
        self.version_dir.mkdir()
        (self.version_dir / "1.20.1.json").write_text(
            json.dumps({"id": "1.20.1", "type": "release", "releaseTime": "2023-06-12T00:00:00Z"}),
            encoding="utf-8",
        )
        (self.version_dir / "1.20.1.jar").write_bytes(b"jar")
        (self.root / "mods").mkdir()
        (self.root / "mods" / "a.jar").write_bytes(b"a")
        (self.root / "mods" / "b.jar.disabled").write_bytes(b"bb")
        (self.version_dir / "mods").mkdir()
        (self.version_dir / "mods" / "c.jar").write_bytes(b"ccc")
        (self.root / "resourcepacks").mkdir()
        (self.root / "resourcepacks" / "pack.zip").write_bytes(b"pack")
        (self.root / "resourcepacks" / "folder-pack").mkdir()
        (self.version_dir / "resourcepacks").mkdir()
        (self.version_dir / "resourcepacks" / "local.zip").write_bytes(b"local")
        (self.root / "shaderpacks").mkdir()
        (self.root / "shaderpacks" / "shader.zip").write_bytes(b"shader")
        (self.version_dir / "modrinth.index.json").write_text(
            json.dumps({"name": "Test Pack", "versionId": "1.0.0", "files": []}),
            encoding="utf-8",
        )

        self.version = LocalVersion(
            folder_name="1.20.1",
            version_id="1.20.1",
            version_type="release",
            release_time=datetime(2023, 6, 12, tzinfo=timezone.utc),
            inherits_from=None,
            directory=self.version_dir,
            has_client_jar=True,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_scan_version_details(self) -> None:
        details = scan_version_details(self.version, self.root)

        self.assertEqual(len(details.mods), 3)
        self.assertEqual(details.mods[0].name, "a.jar")
        self.assertTrue(details.mods[0].enabled)
        self.assertFalse(any(item.name == "b.jar.disabled" and item.enabled for item in details.mods))
        self.assertEqual(len(details.resourcepacks), 3)
        self.assertEqual(len(details.shaderpacks), 1)
        self.assertIsNotNone(details.client_jar)
        self.assertIsNotNone(details.modpack)
        self.assertEqual(details.modpack.name, "Test Pack")
        self.assertEqual(details.modpack.kind, "Modrinth")

    def test_delete_only_target_version(self) -> None:
        keep_dir = self.versions / "keep"
        keep_dir.mkdir()
        (keep_dir / "keep.json").write_text("{}", encoding="utf-8")
        global_mod = self.root / "mods" / "keep.jar"
        global_mod.write_bytes(b"keep")

        deleted = delete_version_folder(self.root, "1.20.1")

        self.assertEqual(deleted, self.version_dir.resolve())
        self.assertFalse(self.version_dir.exists())
        self.assertTrue(keep_dir.exists())
        self.assertTrue(global_mod.exists())

    def test_delete_rejects_path_traversal(self) -> None:
        with self.assertRaises(VersionDeleteError):
            delete_version_folder(self.root, "../keep")
        self.assertTrue((self.versions / "1.20.1").exists())

    def test_delete_rejects_directory_without_version_json(self) -> None:
        fake = self.versions / "fake"
        fake.mkdir()
        with self.assertRaises(VersionDeleteError):
            delete_version_folder(self.root, "fake")
        self.assertTrue(fake.exists())


if __name__ == "__main__":
    unittest.main()

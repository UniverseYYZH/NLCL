"""轻量快照测试。"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from snapshot_manager import SnapshotError, SnapshotManager


class SnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"snapshot-{uuid4().hex}"
        self.mc = self.root / ".minecraft"
        (self.mc / "saves" / "world").mkdir(parents=True)
        (self.mc / "saves" / "world" / "level.dat").write_bytes(b"level")
        (self.mc / "config").mkdir()
        (self.mc / "config" / "mod.json").write_text('{"a":1}', encoding="utf-8")
        (self.mc / "options.txt").write_text("fov:70", encoding="utf-8")
        (self.mc / "mods").mkdir()
        (self.mc / "mods" / "big.jar").write_bytes(b"not backed up")
        self.manager = SnapshotManager(self.root / "snapshots")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_only_lightweight_items(self) -> None:
        snapshot = self.manager.create_snapshot(
            self.mc,
            "Test 1.20.1",
            "test",
            "before mods",
        )
        self.assertTrue((snapshot.path / "saves" / "world" / "level.dat").is_file())
        self.assertTrue((snapshot.path / "config" / "mod.json").is_file())
        self.assertTrue((snapshot.path / "options.txt").is_file())
        self.assertFalse((snapshot.path / "mods").exists())
        self.assertEqual(snapshot.note, "before mods")
        self.assertGreater(snapshot.files, 0)

    def test_rollback_restores_and_creates_safety_snapshot(self) -> None:
        snapshot = self.manager.create_snapshot(
            self.mc,
            "Test 1.20.1",
            "test",
            "good state",
        )
        (self.mc / "saves" / "world" / "level.dat").write_bytes(b"changed")
        (self.mc / "options.txt").write_text("fov:30", encoding="utf-8")
        (self.mc / "config" / "mod.json").unlink()

        safety = self.manager.rollback(snapshot, self.mc)

        self.assertIsNotNone(safety)
        self.assertEqual(
            (self.mc / "saves" / "world" / "level.dat").read_bytes(),
            b"level",
        )
        self.assertEqual((self.mc / "options.txt").read_text(encoding="utf-8"), "fov:70")
        self.assertTrue((self.mc / "config" / "mod.json").is_file())
        snapshots = self.manager.list_snapshots()
        self.assertGreaterEqual(len(snapshots), 2)
        self.assertTrue(any(item.snapshot_id.startswith("auto-") for item in snapshots))

    def test_empty_instance_cannot_snapshot(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(SnapshotError):
            self.manager.create_snapshot(empty, "empty", "empty")

    def test_delete(self) -> None:
        snapshot = self.manager.create_snapshot(self.mc, "v", "v")
        self.manager.delete(snapshot)
        self.assertFalse(snapshot.path.exists())


if __name__ == "__main__":
    unittest.main()

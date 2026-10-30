"""拖拽导入解析测试（不联网、不安装整合包）。"""

from __future__ import annotations

import json
import shutil
import unittest
import zipfile
from pathlib import Path
from uuid import uuid4

from instance_registry import InstanceRegistry
from java_bindings import JavaBindingStore
from mod_import import (
    copy_mod_jar,
    inspect_jar,
    parse_mrpack,
    _rename_version,
    _safe_target,
)


class ImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"import-{uuid4().hex}"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _jar(self, name: str, entries: dict[str, bytes]) -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for key, value in entries.items():
                archive.writestr(key, value)
        return path

    def test_inspect_fabric_mod_and_loader(self) -> None:
        mod = self._jar(
            "example.jar",
            {"fabric.mod.json": json.dumps({"id": "example", "name": "Example"}).encode()},
        )
        self.assertEqual(inspect_jar(mod).kind, "mod")

        loader = self._jar("fabric-installer.jar", {"fabric-installer.json": b"{}"})
        self.assertEqual(inspect_jar(loader).kind, "fabric_loader")

        forge = self._jar(
            "forge-installer.jar",
            {
                "install_profile.json": b"{}",
                "net/minecraftforge/installer/Main.class": b"x",
            },
        )
        self.assertEqual(inspect_jar(forge).kind, "forge_loader")

    def test_copy_mod(self) -> None:
        jar = self._jar("a.jar", {"a.txt": b"a"})
        target = copy_mod_jar(jar, self.root / ".minecraft")
        self.assertTrue(target.is_file())
        self.assertEqual(target.parent.name, "mods")

    def test_parse_mrpack(self) -> None:
        path = self.root / "pack.mrpack"
        index = {
            "name": "My Pack",
            "versionId": "1.0",
            "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"},
            "files": [{"path": "mods/a.jar", "downloads": ["https://example.invalid/a"]}],
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("modrinth.index.json", json.dumps(index))
            archive.writestr("overrides/config/a.json", "{}")
        info = parse_mrpack(path)
        self.assertEqual(info.minecraft, "1.20.1")
        self.assertEqual(info.loader, "fabric")
        self.assertEqual(info.loader_version, "0.15.0")
        self.assertEqual(len(info.files), 1)

    def test_safe_target_and_registry(self) -> None:
        with self.assertRaises(Exception):
            _safe_target(self.root, "../outside.txt")
        registry = InstanceRegistry(self.root / "instances.json")
        entry = registry.add("Pack", self.root / ".minecraft", "NLMCL-pack")
        self.assertEqual(registry.items[0]["id"], entry["id"])

    def test_java_binding_store(self) -> None:
        java = self.root / "java.exe"
        java.write_bytes(b"fake")
        store = JavaBindingStore(self.root / "bindings.json")
        store.set("pack", str(java), 21, "java-runtime-delta")
        loaded = JavaBindingStore(self.root / "bindings.json").get("pack")
        self.assertEqual(loaded["major"], 21)
        self.assertTrue(loaded["path"].endswith("java.exe"))

    def test_rename_version(self) -> None:
        version_dir = self.root / "versions" / "fabric-loader-1.20.1"
        version_dir.mkdir(parents=True)
        (version_dir / "fabric-loader-1.20.1.json").write_text(
            json.dumps({"id": "fabric-loader-1.20.1", "inheritsFrom": "1.20.1"}),
            encoding="utf-8",
        )
        _rename_version(self.root, "fabric-loader-1.20.1", "NLMCL-pack", "My Pack")
        target = self.root / "versions" / "NLMCL-pack"
        self.assertTrue((target / "NLMCL-pack.json").is_file())
        self.assertEqual(
            json.loads((target / "NLMCL-pack.json").read_text(encoding="utf-8"))["id"],
            "My Pack",
        )


if __name__ == "__main__":
    unittest.main()

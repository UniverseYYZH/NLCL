"""Java 设置持久化与 Java 17 校验的单元测试（不访问网络）。"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from launch_settings import (
    JavaValidationError,
    LaunchSettings,
    LaunchSettingsStore,
    parse_java_version,
    validate_java_17,
)


class LaunchSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"settings-{uuid4().hex}"
        self.path = self.root / "launch_settings.json"
        self.store = LaunchSettingsStore(self.path)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_parse_java_versions(self) -> None:
        self.assertEqual(
            parse_java_version('openjdk version "17.0.20.1" 2026-08-18'),
            ("17.0.20.1", 17),
        )
        self.assertEqual(
            parse_java_version('java version "1.8.0_301"'),
            ("1.8.0_301", 8),
        )
        self.assertEqual(
            parse_java_version('openjdk version "21.0.2" 2024-01-16'),
            ("21.0.2", 21),
        )
        with self.assertRaises(JavaValidationError):
            parse_java_version("not java output")

    def test_validate_java_17_success(self) -> None:
        java_path = self.root / "java.exe"
        self.root.mkdir(parents=True, exist_ok=True)
        java_path.write_bytes(b"")
        completed = subprocess.CompletedProcess(
            args=[str(java_path), "-version"],
            returncode=0,
            stdout=b"",
            stderr=b'openjdk version "17.0.20.1" 2026-08-18',
        )
        with patch("launch_settings.subprocess.run", return_value=completed):
            info = validate_java_17(str(java_path))

        self.assertEqual(info.path, str(java_path))
        self.assertEqual(info.version, "17.0.20.1")
        self.assertEqual(info.major, 17)

    def test_validate_rejects_non_17(self) -> None:
        java_path = self.root / "java.exe"
        self.root.mkdir(parents=True, exist_ok=True)
        java_path.write_bytes(b"")
        completed = subprocess.CompletedProcess(
            args=[str(java_path), "-version"],
            returncode=0,
            stdout=b"",
            stderr=b'openjdk version "21.0.2" 2024-01-16',
        )
        with patch("launch_settings.subprocess.run", return_value=completed):
            with self.assertRaises(JavaValidationError):
                validate_java_17(str(java_path))

    def test_validate_rejects_missing_path(self) -> None:
        with self.assertRaises(JavaValidationError):
            validate_java_17(str(self.root / "missing-java.exe"))

    def test_memory_normalization(self) -> None:
        settings = LaunchSettings(
            min_memory_mb=4096,
            max_memory_mb=1024,
        ).normalized()
        self.assertEqual(settings.min_memory_mb, 4096)
        self.assertEqual(settings.max_memory_mb, 4096)

        settings = LaunchSettings(
            min_memory_mb=100,
            max_memory_mb=999999,
        ).normalized()
        self.assertEqual(settings.min_memory_mb, 512)
        self.assertEqual(settings.max_memory_mb, 32768)

    def test_settings_roundtrip(self) -> None:
        original = LaunchSettings(
            java_path=r"E:\JDK\bin\java.exe",
            java_version="17.0.20.1",
            java_major=17,
            min_memory_mb=2048,
            max_memory_mb=8192,
            jvm_args="-XX:+UseG1GC\n-XX:+UnlockExperimentalVMOptions",
        )
        saved = self.store.save(original)
        self.assertEqual(saved.java_path, original.java_path)
        self.assertTrue(self.path.is_file())

        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(stored["memory"]["min_mb"], 2048)
        self.assertEqual(stored["memory"]["max_mb"], 8192)

        restored = LaunchSettingsStore(self.path).settings
        self.assertEqual(restored.java_major, 17)
        self.assertEqual(restored.jvm_args, original.jvm_args)

    def test_missing_file_returns_defaults(self) -> None:
        settings = self.store.load()
        self.assertEqual(settings.min_memory_mb, 1024)
        self.assertEqual(settings.max_memory_mb, 4096)
        self.assertEqual(settings.java_path, "")


if __name__ == "__main__":
    unittest.main()

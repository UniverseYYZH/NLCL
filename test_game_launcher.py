"""启动前检查、JVM 参数和启动命令构建的单元测试。"""

from __future__ import annotations

import json
import shutil
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from account_manager import Account, create_offline_account
from game_launcher import (
    LaunchError,
    account_launch_token,
    build_minecraft_command,
    check_version_files,
    ensure_natives,
    memory_summary,
    split_jvm_args,
)
from launch_settings import LaunchSettings
from version_scanner import LocalVersion


class GameLauncherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"launcher-{uuid4().hex}"
        self.minecraft_dir = self.root / ".minecraft"
        self.version_dir = self.minecraft_dir / "versions" / "1.20.1"
        self.version_dir.mkdir(parents=True)
        (self.minecraft_dir / "libraries").mkdir()
        (self.minecraft_dir / "assets").mkdir()
        (self.minecraft_dir / "assets" / "indexes").mkdir()
        (self.minecraft_dir / "assets" / "indexes" / "1.json").write_text(
            "{}",
            encoding="utf-8",
        )
        self.version_data = {
            "id": "1.20.1",
            "mainClass": "net.minecraft.client.main.Main",
            "assetIndex": {"id": "1"},
            "libraries": [],
            "javaVersion": {"majorVersion": 17},
        }
        (self.version_dir / "1.20.1.json").write_text(
            json.dumps(self.version_data),
            encoding="utf-8",
        )
        (self.version_dir / "1.20.1.jar").write_bytes(b"jar")
        self.version = LocalVersion(
            folder_name="1.20.1",
            version_id="1.20.1",
            version_type="release",
            release_time=None,
            inherits_from=None,
            directory=self.version_dir,
            has_client_jar=True,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_split_jvm_args(self) -> None:
        self.assertEqual(
            split_jvm_args("-XX:+UseG1GC -Xss1M"),
            ["-XX:+UseG1GC", "-Xss1M"],
        )
        self.assertEqual(
            split_jvm_args(r"-Dfoo=C:\bar -Xmx2G"),
            [r"-Dfoo=C:\bar", "-Xmx2G"],
        )
        self.assertEqual(
            split_jvm_args('-Dfoo="bar baz"'),
            ["-Dfoo=bar baz"],
        )
        with self.assertRaises(LaunchError):
            split_jvm_args('"unclosed')

    def test_check_version_files_success(self) -> None:
        result = check_version_files(self.version, self.minecraft_dir)
        self.assertEqual(result.client_jar, self.version_dir / "1.20.1.jar")
        self.assertEqual(result.required_java_major, 17)
        self.assertFalse(result.warnings)

    def test_ensure_natives_extracts_windows_dll(self) -> None:
        library_dir = self.minecraft_dir / "libraries" / "org" / "lwjgl" / "lwjgl" / "3.3.1"
        library_dir.mkdir(parents=True)
        native_jar = library_dir / "lwjgl-3.3.1-natives-windows.jar"
        with zipfile.ZipFile(native_jar, "w") as archive:
            archive.writestr("lwjgl.dll", b"dll")
            archive.writestr("META-INF/MANIFEST.MF", b"manifest")

        version_data = {
            "id": "1.20.1",
            "libraries": [
                {
                    "name": "org.lwjgl:lwjgl:3.3.1:natives-windows",
                    "downloads": {
                        "artifact": {
                            "path": "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows.jar"
                        }
                    },
                }
            ],
        }
        (self.version_dir / "1.20.1.json").write_text(
            json.dumps(version_data),
            encoding="utf-8",
        )

        result = ensure_natives(self.version, self.minecraft_dir)
        self.assertEqual(result.extracted, 1)
        self.assertTrue((self.version_dir / "natives" / "lwjgl.dll").is_file())
        self.assertFalse(result.warnings)

    def test_check_version_files_missing_jar(self) -> None:
        (self.version_dir / "1.20.1.jar").unlink()
        with self.assertRaises(LaunchError):
            check_version_files(self.version, self.minecraft_dir)

    def test_check_version_files_inherited_jar(self) -> None:
        parent_dir = self.minecraft_dir / "versions" / "parent"
        parent_dir.mkdir()
        (parent_dir / "parent.jar").write_bytes(b"parent")
        (parent_dir / "parent.json").write_text(
            json.dumps(
                {
                    "id": "parent",
                    "mainClass": "net.minecraft.client.main.Main",
                    "assetIndex": {"id": "1"},
                    "libraries": [],
                    "javaVersion": {"majorVersion": 17},
                }
            ),
            encoding="utf-8",
        )
        version = LocalVersion(
            folder_name="fabric",
            version_id="fabric",
            version_type="release",
            release_time=None,
            inherits_from="parent",
            directory=self.version_dir,
            has_client_jar=False,
        )
        (self.version_dir / "fabric.json").write_text(
            json.dumps({"id": "fabric", "inheritsFrom": "parent"}),
            encoding="utf-8",
        )
        result = check_version_files(version, self.minecraft_dir)
        self.assertEqual(result.client_jar, parent_dir / "parent.jar")

    def test_version_validation_reports_missing_asset_index_and_library(self) -> None:
        (self.minecraft_dir / "assets" / "indexes" / "1.json").unlink()
        data = dict(self.version_data)
        data["libraries"] = [
            {
                "name": "example:missing:1.0",
                "downloads": {
                    "artifact": {
                        "path": "example/missing/1.0/missing-1.0.jar",
                    }
                },
            }
        ]
        (self.version_dir / "1.20.1.json").write_text(
            json.dumps(data),
            encoding="utf-8",
        )
        with self.assertRaises(LaunchError) as context:
            check_version_files(self.version, self.minecraft_dir)
        message = str(context.exception)
        self.assertIn("资源索引", message)
        self.assertIn("缺少依赖库", message)
        self.assertIn("1.20.1", message)

    def test_version_validation_reports_required_java(self) -> None:
        data = dict(self.version_data)
        data["javaVersion"] = {"majorVersion": 21}
        (self.version_dir / "1.20.1.json").write_text(
            json.dumps(data),
            encoding="utf-8",
        )
        result = check_version_files(self.version, self.minecraft_dir)
        self.assertEqual(result.required_java_major, 21)

    def test_build_command_applies_memory_and_custom_args(self) -> None:
        account = create_offline_account("Tester")
        settings = LaunchSettings(
            min_memory_mb=2048,
            max_memory_mb=8192,
            jvm_args="-XX:+UseG1GC",
        )
        with patch(
            "game_launcher.get_minecraft_command",
            return_value=["java", "-version"],
        ) as command_mock:
            command = build_minecraft_command(
                self.version,
                self.minecraft_dir,
                account,
                settings,
                r"E:\JDK\bin\java.exe",
                "0",
            )

        self.assertEqual(command, ["java", "-version"])
        options = command_mock.call_args.args[2]
        self.assertEqual(options["username"], "Tester")
        self.assertEqual(options["token"], "0")
        self.assertEqual(options["executablePath"], r"E:\JDK\bin\java.exe")
        self.assertIn("-Xms2048M", options["jvmArguments"])
        self.assertIn("-Xmx8192M", options["jvmArguments"])
        self.assertIn("-XX:+UseG1GC", options["jvmArguments"])

    def test_account_token(self) -> None:
        offline = create_offline_account("Tester")
        self.assertEqual(account_launch_token(offline), "0")

        microsoft = Account(
            id="ms",
            account_type="microsoft",
            name="MS",
            uuid="ms",
        )
        with self.assertRaises(LaunchError):
            account_launch_token(microsoft)
        self.assertEqual(account_launch_token(microsoft, "token"), "token")

    def test_memory_summary(self) -> None:
        settings = LaunchSettings(min_memory_mb=1024, max_memory_mb=4096)
        self.assertEqual(memory_summary(settings), "1024 - 4096 MB")


if __name__ == "__main__":
    unittest.main()

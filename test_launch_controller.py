"""多实例启动控制器测试（使用假进程，不启动 Minecraft）。"""

from __future__ import annotations

import asyncio
import shutil
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from account_manager import AccountStore, create_offline_account
from game_launcher import NativesResult
from launch_controller import GameLauncherController, GameSession
from launch_settings import JavaInfo, LaunchSettings, LaunchSettingsStore
from version_scanner import LocalVersion


class _FakePage:
    def update(self) -> None:
        pass

    def run_task(self, *args, **kwargs) -> None:
        pass


class LaunchControllerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"controller-{uuid4().hex}"
        self.root.mkdir(parents=True)
        self.account_store = AccountStore(self.root / "accounts.json")
        self.account = create_offline_account("Tester")
        self.account_store.save_account(self.account)
        self.settings_store = LaunchSettingsStore(self.root / "settings.json")
        self.settings_store.save(
            LaunchSettings(
                java_path=r"E:\JDK\bin\java.exe",
                java_version="17.0.20.1",
                java_major=17,
            )
        )
        self.version_dir = self.root / "versions" / "test"
        self.version_dir.mkdir(parents=True)
        self.version = LocalVersion(
            folder_name="test",
            version_id="test",
            version_type="release",
            release_time=None,
            inherits_from=None,
            directory=self.version_dir,
            has_client_jar=True,
        )
        self.controller = GameLauncherController(
            _FakePage(),
            self.account_store,
            self.settings_store,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    async def test_two_sessions_run_independently(self) -> None:
        sessions = [
            GameSession(
                id=f"game-{index}",
                version=self.version,
                account_id=self.account.id,
                account_name=self.account.name,
                account_type=self.account.type_label,
            )
            for index in range(1, 3)
        ]
        command = [
            sys.executable,
            "-u",
            "-c",
            "import time; print('hello', flush=True); time.sleep(0.2)",
        ]
        fake_check = SimpleNamespace(warnings=(), required_java_major=17)
        fake_java = JavaInfo(
            path=r"E:\JDK\bin\java.exe",
            version="17.0.20.1",
            major=17,
        )
        fake_natives = NativesResult(directory=self.version_dir / "natives", extracted=0)
        with (
            patch("launch_controller.check_version_files", return_value=fake_check),
            patch("launch_controller.validate_java_17", return_value=fake_java),
            patch("launch_controller.ensure_natives", return_value=fake_natives),
            patch("launch_controller.build_minecraft_command", return_value=command),
        ):
            await asyncio.gather(
                *(self.controller._run_session(session) for session in sessions)
            )

        self.assertEqual([session.status for session in sessions], ["exited", "exited"])
        for session in sessions:
            self.assertTrue(any("hello" in entry.text for entry in session.logs))
            self.assertIsNone(session.process)

    async def test_instance_java_override(self) -> None:
        session = GameSession(
            id="game-override",
            version=self.version,
            account_id=self.account.id,
            account_name=self.account.name,
            account_type=self.account.type_label,
            java_path_override=r"E:\Java21\bin\java.exe",
            java_major_override=21,
        )
        java_info = JavaInfo(
            path=r"E:\Java21\bin\java.exe",
            version="21.0.7",
            major=21,
        )
        captured = {}

        def fake_build(*args):
            captured["java"] = args[4]
            return [sys.executable, "-u", "-c", "print('ok', flush=True)"]

        fake_check = SimpleNamespace(warnings=(), required_java_major=21)
        fake_natives = NativesResult(directory=self.version_dir / "natives", extracted=0)
        with (
            patch("launch_controller.check_version_files", return_value=fake_check),
            patch("launch_controller.inspect_java", return_value=java_info),
            patch("launch_controller.ensure_natives", return_value=fake_natives),
            patch("launch_controller.build_minecraft_command", side_effect=fake_build),
        ):
            await self.controller._run_session(session)

        self.assertEqual(session.status, "exited")
        self.assertEqual(captured["java"], r"E:\Java21\bin\java.exe")
        self.assertTrue(any("实例绑定 Java" in item.text for item in session.logs))

    async def test_export_and_clear_logs(self) -> None:
        session = GameSession(
            id="game-1",
            version=self.version,
            account_id=self.account.id,
            account_name=self.account.name,
            account_type=self.account.type_label,
        )
        self.controller.sessions.append(session)
        self.controller._log(session, "line one", "info")
        self.controller._log(session, "line two", "warn")
        self.assertIn("line one", self.controller.export_text(session.id))
        self.assertIn("line two", self.controller.export_text(session.id))
        self.controller.clear_logs(session.id)
        self.assertEqual(self.controller.export_text(session.id), "")

    def test_remove_only_ended_session(self) -> None:
        session = GameSession(
            id="game-ended",
            version=self.version,
            account_id=self.account.id,
            account_name=self.account.name,
            account_type=self.account.type_label,
            status="running",
        )
        self.controller.sessions.append(session)
        self.assertFalse(self.controller.remove_session(session.id))
        self.assertEqual(len(self.controller.sessions), 1)

        session.status = "exited"
        self.assertTrue(session.is_ended)
        self.assertTrue(self.controller.remove_session(session.id))
        self.assertEqual(self.controller.sessions, [])


if __name__ == "__main__":
    unittest.main()

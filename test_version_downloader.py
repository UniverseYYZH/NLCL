"""原版下载模块的单元测试（不访问网络）。"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from ui_helpers import format_bytes, format_speed, same_directory
from version_downloader import (
    VersionDownloadTask,
    parse_version_manifest,
)


class VersionDownloaderTest(unittest.TestCase):
    def test_parse_manifest_filters_and_sorts(self) -> None:
        data = {
            "versions": [
                {
                    "id": "1.20.1",
                    "type": "release",
                    "releaseTime": "2023-06-12T12:00:00+00:00",
                    "url": "https://example.invalid/1.20.1.json",
                },
                {
                    "id": "24w14a",
                    "type": "snapshot",
                    "releaseTime": "2024-04-03T12:00:00+00:00",
                },
                {
                    "id": "a1.2.6",
                    "type": "old_alpha",
                    "releaseTime": "2012-01-01T00:00:00+00:00",
                },
                {
                    "id": "1.21",
                    "type": "release",
                    "releaseTime": "2024-08-08T12:00:00+00:00",
                },
            ]
        }

        versions = parse_version_manifest(data)

        self.assertEqual(
            [version.version_id for version in versions],
            ["1.21", "24w14a", "1.20.1"],
        )
        self.assertEqual(versions[0].version_type, "release")
        self.assertIsNotNone(versions[0].release_time)
        self.assertEqual(
            versions[-1].url,
            "https://example.invalid/1.20.1.json",
        )

    def test_download_task_success(self) -> None:
        def fake_installer(version, directory, callback):
            callback["setStatus"]("Download Libraries")
            callback["setMax"](4)
            callback["setProgress"](2)
            callback["setStatus"]("Download Assets")
            callback["setMax"](2)
            callback["setProgress"](2)
            callback["setStatus"](f"Download {version}.jar")
            callback["setStatus"]("Installation complete")

        task = VersionDownloadTask(
            "1.21",
            "D:/MC",
            installer=fake_installer,
        )
        task.start()

        snapshot = self._wait_done(task)
        self.assertTrue(snapshot.success)
        self.assertTrue(snapshot.done)
        self.assertEqual(snapshot.percent, 100.0)
        self.assertEqual(snapshot.status, "下载完成")
        self.assertEqual(snapshot.error, "")

    def test_download_task_failure(self) -> None:
        def failing_installer(version, directory, callback):
            raise RuntimeError("网络断开")

        task = VersionDownloadTask(
            "1.21",
            "D:/MC",
            installer=failing_installer,
        )
        task.start()

        snapshot = self._wait_done(task)
        self.assertFalse(snapshot.success)
        self.assertTrue(snapshot.done)
        self.assertEqual(snapshot.status, "下载失败")
        self.assertIn("网络断开", snapshot.error)

    def test_phase_progress_is_monotonic(self) -> None:
        task = VersionDownloadTask("1.21", "D:/MC")
        task._on_status("Download Libraries")
        task._on_max(10)
        task._on_progress(5)
        after_libraries = task.snapshot().percent

        task._on_status("Download Assets")
        task._on_max(4)
        task._on_progress(4)
        after_assets = task.snapshot().percent

        task._on_status("Download 1.21.jar")
        after_client = task.snapshot().percent

        task._on_status("Install java runtime")
        task._on_max(10)
        task._on_progress(5)
        after_runtime = task.snapshot().percent

        task._on_status("Installation complete")

        self.assertGreaterEqual(after_libraries, 3.0)
        self.assertGreater(after_assets, after_libraries)
        self.assertGreaterEqual(after_assets, 75.0)
        self.assertGreaterEqual(after_client, 75.0)
        self.assertGreater(after_runtime, after_client)
        self.assertEqual(task.snapshot().percent, 100.0)

    def test_progress_span(self) -> None:
        task = VersionDownloadTask(
            "java-runtime-gamma",
            "D:/MC",
            progress_span=(0.0, 100.0),
        )
        task._on_max(10)
        task._on_progress(5)
        self.assertGreaterEqual(task.snapshot().percent, 50.0)
        task._on_progress(10)
        self.assertGreaterEqual(task.snapshot().percent, 100.0)

    def test_byte_and_speed_formatting(self) -> None:
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1024 * 1024), "1.0 MB")
        self.assertEqual(format_speed(1024), "1.0 KB/s")

    def test_same_directory(self) -> None:
        current = Path.cwd()
        self.assertTrue(same_directory(current, current / "."))
        self.assertFalse(same_directory(current, current / "not-same-dir"))

    def _wait_done(self, task: VersionDownloadTask, timeout: float = 3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = task.snapshot()
            if snapshot.done:
                return snapshot
            time.sleep(0.01)
        self.fail("下载任务超时未结束")


if __name__ == "__main__":
    unittest.main()

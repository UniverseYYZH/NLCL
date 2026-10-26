"""下载弹窗完成提示的轻量测试（不联网、不下载）。"""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from download_ui import DownloadDialog
from java_runtime import JavaRecommendation
from ui_theme import BUTTON_LABEL_FIELD
from version_downloader import VanillaVersion


class _FakePage:
    def __init__(self) -> None:
        self.overlay = []
        self.closed = False

    def update(self) -> None:
        pass

    def open(self, control) -> None:
        control.open = True

    def close(self, control) -> None:
        control.open = False
        self.closed = True

    def run_task(self, function, *args) -> None:
        coroutine = function(*args)
        if inspect.iscoroutine(coroutine):
            coroutine.close()


class DownloadDialogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"dlg-{uuid4().hex}"
        self.page = _FakePage()
        self.downloaded: list[str] = []
        self.dialog = DownloadDialog(
            self.page,
            str(self.root),
            on_downloaded=self.downloaded.append,
        )

    def test_success_prompt_is_clickable_and_closes(self) -> None:
        snapshot = SimpleNamespace(
            success=True,
            elapsed=1.2,
            bytes_received=123,
            error="",
        )
        self.dialog._finish_download(snapshot)

        self.assertTrue(self.dialog.completion_hint.visible)
        self.assertIn("点击关闭", self.dialog.completion_text.value)
        self.assertEqual(
            getattr(self.dialog.download_button, BUTTON_LABEL_FIELD),
            "完成并关闭",
        )
        self.assertEqual(self.downloaded, [str(self.root)])

        self.dialog.completion_hint.on_click(None)
        self.assertTrue(self.page.closed)
        self.assertTrue(self.dialog._closed)

    def test_java_success_does_not_refresh_versions(self) -> None:
        self.dialog.install_kind = "java"
        snapshot = SimpleNamespace(
            success=True,
            elapsed=1.2,
            bytes_received=123,
            error="",
        )
        self.dialog._finish_download(snapshot)

        self.assertTrue(self.dialog.completion_hint.visible)
        self.assertEqual(self.downloaded, [])
        self.assertEqual(
            getattr(self.dialog.download_button, BUTTON_LABEL_FIELD),
            "完成并关闭",
        )


    def test_loader_installer_prepares_java_and_vanilla(self) -> None:
        class FakeTask:
            last = None

            def __init__(self, *args, **kwargs):
                self.installer = kwargs.get("installer")
                FakeTask.last = self

            def start(self) -> None:
                pass

        class FakeLoader:
            def __init__(self):
                self.calls = []

            def install(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return "fabric-loader-test"

        loader = FakeLoader()
        callback_calls = []

        def callback_set_status(value):
            callback_calls.append(value)

        from unittest.mock import patch

        self.dialog.mode = "fabric"
        self.dialog.selected = VanillaVersion(
            version_id="1.20.1",
            version_type="release",
            release_time=None,
        )
        self.dialog.recommendation = JavaRecommendation(
            major=17,
            component="java-runtime-gamma",
        )
        self.dialog.loader_dropdown.disabled = False
        self.dialog.loader_dropdown.value = "latest"
        self.dialog.loader_error = ""

        with (
            patch("download_ui.VersionDownloadTask", FakeTask),
            patch("download_ui.get_mod_loader", return_value=loader),
            patch("download_ui.runtime_executable", side_effect=[None, "java.exe"]),
            patch("download_ui.install_java_runtime") as install_java,
            patch("download_ui.is_version_valid", return_value=False),
            patch("download_ui.install_minecraft_version") as install_vanilla,
        ):
            self.dialog._start_download()
            installer = FakeTask.last.installer
            installer(
                "1.20.1",
                str(self.root),
                {"setStatus": callback_set_status},
            )

        install_java.assert_called_once()
        install_vanilla.assert_called_once()
        self.assertEqual(loader.calls[0][1]["java"], "java.exe")
        self.assertIn("安装 Java 17", callback_calls)
        self.assertIn("安装 Fabric", callback_calls)


if __name__ == "__main__":
    unittest.main()

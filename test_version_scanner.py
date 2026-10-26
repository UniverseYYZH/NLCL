"""version_scanner 的单元测试。

运行：
    .venv\\Scripts\\python.exe -m unittest -v test_version_scanner.py
"""

from __future__ import annotations

import json
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from version_scanner import scan_local_versions, version_type_label


class VersionScannerTest(unittest.TestCase):
    def setUp(self) -> None:
        # 固定放在项目的 .tmp 下，避免部分 Windows 沙箱不允许在系统临时目录
        # 内再创建子目录；.tmp 已加入 .gitignore。
        self.root = Path(__file__).resolve().parent / ".tmp" / f"test-{uuid4().hex}"
        self.root.mkdir(parents=True)
        (self.root / "versions").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def make_version(
        self,
        folder_name: str,
        *,
        version_type: str = "release",
        release_time: str | None = "2024-01-01T00:00:00+00:00",
        inherits_from: str | None = None,
        with_jar: bool = True,
        encoding: str = "utf-8",
        raw_json: str | None = None,
    ) -> Path:
        version_dir = self.root / "versions" / folder_name
        version_dir.mkdir(parents=True)

        metadata = {
            "id": folder_name,
            "type": version_type,
            "releaseTime": release_time,
        }
        if inherits_from:
            metadata["inheritsFrom"] = inherits_from

        metadata_path = version_dir / f"{folder_name}.json"
        if raw_json is not None:
            metadata_path.write_text(raw_json, encoding=encoding)
        else:
            metadata_path.write_text(json.dumps(metadata), encoding=encoding)

        if with_jar:
            (version_dir / f"{folder_name}.jar").write_bytes(b"fake jar")
        return version_dir

    def test_scan_reads_and_sorts_versions(self) -> None:
        self.make_version("1.20.1", release_time="2024-06-13T00:00:00+00:00")
        self.make_version(
            "1.21",
            release_time="2024-08-08T00:00:00+00:00",
            with_jar=False,
        )
        self.make_version(
            "24w29a",
            version_type="snapshot",
            release_time="2024-07-15T00:00:00+00:00",
        )
        self.make_version(
            "fabric-loader-0.15-1.21",
            release_time="2024-07-20T00:00:00+0000",
            inherits_from="1.21",
            with_jar=False,
        )

        result = scan_local_versions(self.root)

        self.assertEqual(result.version_count, 4)
        self.assertEqual([v.version_id for v in result.versions], [
            "1.21",
            "fabric-loader-0.15-1.21",
            "24w29a",
            "1.20.1",
        ])
        self.assertEqual(result.issues, [])

        fabric = result.versions[1]
        self.assertEqual(fabric.inherits_from, "1.21")
        self.assertFalse(fabric.has_client_jar)
        self.assertEqual(fabric.release_time, datetime(2024, 7, 20, tzinfo=timezone.utc))

    def test_broken_json_does_not_break_other_versions(self) -> None:
        self.make_version("good", release_time="2024-03-01T00:00:00+00:00")
        self.make_version("broken", raw_json="{ not valid json")

        result = scan_local_versions(self.root)

        self.assertEqual([v.version_id for v in result.versions], ["good"])
        self.assertEqual(len(result.issues), 1)
        self.assertIn("broken", result.issues[0].path.name)
        self.assertIn("读取失败", result.issues[0].message)

    def test_ignores_manifests_and_folders_without_matching_json(self) -> None:
        (self.root / "versions" / "version_manifest_v2.json").write_text("{}", encoding="utf-8")
        (self.root / "versions" / "jre_manifest.json").write_text("{}", encoding="utf-8")
        (self.root / "versions" / "not-a-version").mkdir()

        result = scan_local_versions(self.root)

        self.assertEqual(result.versions, [])
        self.assertEqual(result.issues, [])

    def test_missing_versions_folder_reports_issue(self) -> None:
        empty_root = self.root / "empty"
        empty_root.mkdir()

        result = scan_local_versions(empty_root)

        self.assertEqual(result.versions, [])
        self.assertEqual(len(result.issues), 1)
        self.assertIn("没有 versions 文件夹", result.issues[0].message)

    def test_reads_bom_json_and_compact_timezone(self) -> None:
        raw_json = (
            '{"id": "custom-client", "type": "release", '
            '"releaseTime": "2026-10-19T11:05:02+0000"}'
        )
        self.make_version("folder-name", raw_json=raw_json, encoding="utf-8-sig")

        result = scan_local_versions(self.root)

        self.assertEqual(result.issues, [])
        self.assertEqual(result.versions[0].version_id, "custom-client")
        self.assertEqual(result.versions[0].folder_name, "folder-name")
        self.assertIsNotNone(result.versions[0].release_time)

    def test_type_labels(self) -> None:
        self.assertEqual(version_type_label("release"), "正式版")
        self.assertEqual(version_type_label("snapshot"), "快照")
        self.assertEqual(version_type_label("custom"), "custom")
        self.assertEqual(version_type_label(""), "未知")


if __name__ == "__main__":
    unittest.main()

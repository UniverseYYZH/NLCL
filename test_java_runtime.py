"""Java 版本推荐函数测试（不访问网络）。"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from java_runtime import (
    component_for_major,
    parse_version_java,
    read_local_version_java,
    recommend_java_major,
)
from version_scanner import LocalVersion


class JavaRuntimeTest(unittest.TestCase):
    def test_recommend_major_for_known_versions(self) -> None:
        cases = {
            "1.16.5": 8,
            "1.17.1": 16,
            "1.18.2": 17,
            "1.20.1": 17,
            "1.20.4": 17,
            "1.20.5": 21,
            "1.21.11": 21,
            "26.1": 21,
            "26.2": 25,
            "26.3": 25,
        }
        for version, expected in cases.items():
            self.assertEqual(
                recommend_java_major(version),
                expected,
                msg=version,
            )

    def test_component_mapping(self) -> None:
        self.assertEqual(component_for_major(8), "jre-legacy")
        self.assertEqual(component_for_major(16), "java-runtime-alpha")
        self.assertEqual(component_for_major(17), "java-runtime-gamma")
        self.assertEqual(component_for_major(21), "java-runtime-delta")
        self.assertEqual(component_for_major(25), "java-runtime-epsilon")
        self.assertEqual(component_for_major(30), "java-runtime-epsilon")

    def test_parse_version_json_java(self) -> None:
        major, component = parse_version_java(
            {"javaVersion": {"majorVersion": 21, "component": "java-runtime-delta"}}
        )
        self.assertEqual(major, 21)
        self.assertEqual(component, "java-runtime-delta")

        major, component = parse_version_java(
            {"javaVersion": {"majorVersion": 17}}
        )
        self.assertEqual(major, 17)
        self.assertEqual(component, "java-runtime-gamma")

        self.assertEqual(parse_version_java({}), (None, None))

    def test_read_local_version_java(self) -> None:
        root = Path(__file__).resolve().parent / ".tmp" / f"java-{uuid4().hex}"
        version_dir = root / "versions" / "1.20.1"
        version_dir.mkdir(parents=True)
        (version_dir / "1.20.1.json").write_text(
            json.dumps(
                {
                    "id": "1.20.1",
                    "javaVersion": {
                        "majorVersion": 17,
                        "component": "java-runtime-gamma",
                    },
                }
            ),
            encoding="utf-8",
        )
        version = LocalVersion(
            folder_name="1.20.1",
            version_id="1.20.1",
            version_type="release",
            release_time=None,
            inherits_from=None,
            directory=version_dir,
            has_client_jar=False,
        )
        try:
            recommendation = read_local_version_java(version)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(recommendation.major, 17)
        self.assertEqual(recommendation.component, "java-runtime-gamma")
        self.assertTrue(recommendation.is_exact)


if __name__ == "__main__":
    unittest.main()

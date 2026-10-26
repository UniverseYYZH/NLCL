"""日志语义标签测试。"""

from __future__ import annotations

import unittest

from log_tags import (
    TAG_JAVA,
    TAG_MOD_CONFLICT,
    TAG_NORMAL,
    TAG_RESOURCE,
    classify_log,
    tag_color,
    tag_label,
)


class LogTagsTest(unittest.TestCase):
    def test_java_incompatibility(self) -> None:
        self.assertEqual(
            classify_log("java.lang.UnsupportedClassVersionError: class file version 65.0"),
            TAG_JAVA,
        )
        self.assertEqual(
            classify_log("Minecraft requires Java 21 but Java 17 is installed"),
            TAG_JAVA,
        )

    def test_mod_conflict(self) -> None:
        self.assertEqual(
            classify_log("Incompatible mod set! Missing or unsupported mandatory dependencies"),
            TAG_MOD_CONFLICT,
        )
        self.assertEqual(
            classify_log("Mixin apply failed for mod sodium"),
            TAG_MOD_CONFLICT,
        )

    def test_resource_error(self) -> None:
        self.assertEqual(
            classify_log("Failed to load texture minecraft:textures/block/stone.png"),
            TAG_RESOURCE,
        )
        self.assertEqual(
            classify_log("FileNotFoundException: assets/example/lang/en_us.json"),
            TAG_RESOURCE,
        )

    def test_normal_and_colors(self) -> None:
        self.assertEqual(classify_log("Render thread started"), TAG_NORMAL)
        self.assertEqual(classify_log("INFO: Loaded 42 mods"), TAG_NORMAL)
        self.assertEqual(tag_label(TAG_NORMAL), "正常信息")
        self.assertTrue(tag_color(TAG_MOD_CONFLICT).startswith("#"))


if __name__ == "__main__":
    unittest.main()

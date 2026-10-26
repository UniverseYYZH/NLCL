"""游戏日志语义分类：模组冲突、Java 不兼容、资源加载失败、正常信息。"""

from __future__ import annotations

import re

TAG_MOD_CONFLICT = "mod_conflict"
TAG_JAVA = "java_error"
TAG_RESOURCE = "resource_error"
TAG_NORMAL = "normal"

TAG_LABELS = {
    TAG_MOD_CONFLICT: "模组冲突",
    TAG_JAVA: "Java不兼容",
    TAG_RESOURCE: "资源加载失败",
    TAG_NORMAL: "正常信息",
}

TAG_COLORS = {
    TAG_MOD_CONFLICT: "#FF8A7A",
    TAG_JAVA: "#C79BFF",
    TAG_RESOURCE: "#F2C96D",
    TAG_NORMAL: "#C9D8CF",
}

# 顺序很重要：先判断 Java，再判断模组冲突，最后判断资源。
_JAVA_PATTERNS = (
    r"unsupportedclassversionerror",
    r"unsupported class version",
    r"requires java\s*\d+",
    r"需要\s*java\s*\d+",
    r"java version.*(?:incompatible|not supported)",
    r"java 版本.*(?:不兼容|不支持)",
    r"java\.lang\.unsupportedclassversion",
    r"could not find java",
    r"java executable.*not found",
    r"class file version \d+",
)

_MOD_CONFLICT_PATTERNS = (
    r"mod resolution",
    r"incompatible mod",
    r"mod conflict",
    r"duplicate mod",
    r"模组冲突",
    r"缺少.*依赖",
    r"mixin.*(?:error|fail|exception)",
    r"missing or unsupported mandatory dependencies",
    r"loaderException",
    r"modlauncher",
    r"forge.*(?:conflict|incompatible)",
    r"fabric.*(?:conflict|incompatible)",
    r"requires .* version .* of .*",
)

_RESOURCE_PATTERNS = (
    r"failed to load (?:texture|model|resource|sound)",
    r"unable to load (?:texture|model|resource|sound)",
    r"无法加载(?:资源|纹理|模型|声音)",
    r"missing texture",
    r"resource(?:pack)? not found",
    r"filenotfoundexception",
    r"couldn't load .*\.(?:png|json|ogg)",
    r"assets/.*\.(?:png|json|ogg).*not found",
    r"model .* not found",
)

_JAVA_RE = re.compile("|".join(_JAVA_PATTERNS), re.IGNORECASE)
_MOD_RE = re.compile("|".join(_MOD_CONFLICT_PATTERNS), re.IGNORECASE)
_RESOURCE_RE = re.compile("|".join(_RESOURCE_PATTERNS), re.IGNORECASE)


def classify_log(text: str, level: str = "info") -> str:
    """根据关键词给一行日志打标签。正常 INFO 不会被误标为错误。"""

    line = text or ""
    if _JAVA_RE.search(line):
        return TAG_JAVA
    if _MOD_RE.search(line):
        return TAG_MOD_CONFLICT
    if _RESOURCE_RE.search(line):
        return TAG_RESOURCE
    return TAG_NORMAL


def tag_label(tag: str) -> str:
    return TAG_LABELS.get(tag, TAG_LABELS[TAG_NORMAL])


def tag_color(tag: str) -> str:
    return TAG_COLORS.get(tag, TAG_COLORS[TAG_NORMAL])

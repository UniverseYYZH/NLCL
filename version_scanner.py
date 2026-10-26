"""扫描本地 .minecraft 中已经安装的 Minecraft 版本。

扫描过程是只读的，不会修改游戏目录。一个版本的标准结构是：

    .minecraft/
    └── versions/
        └── 1.21.1/
            ├── 1.21.1.json   <- 版本元数据（必须）
            └── 1.21.1.jar    <- 客户端文件（原版通常有，加载器版本可能没有）

设计说明：
- 直接读取每个版本的 JSON，而不是一次性调用库函数。这样某个版本 JSON
  损坏时，只会记录一条错误，不会导致整个列表扫描失败。
- 返回值使用 dataclass，方便后续启动模块继续使用，而不是把 UI 数据混在一起。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# 版本类型显示名。未知类型直接显示原始值，方便排查自定义客户端。
TYPE_LABELS = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "旧版 Beta",
    "old_alpha": "旧版 Alpha",
}


@dataclass(frozen=True, slots=True)
class LocalVersion:
    """一个本地版本的只读信息。"""

    folder_name: str
    version_id: str
    version_type: str
    release_time: datetime | None
    inherits_from: str | None
    directory: Path
    has_client_jar: bool


@dataclass(frozen=True, slots=True)
class ScanIssue:
    """扫描过程中遇到的单个问题。"""

    path: Path
    message: str


@dataclass(slots=True)
class ScanResult:
    """一次扫描的完整结果。"""

    minecraft_dir: Path
    versions: list[LocalVersion] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)

    @property
    def version_count(self) -> int:
        return len(self.versions)


def default_minecraft_dir() -> Path:
    """返回 Windows 默认的 .minecraft 路径。"""

    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / ".minecraft"


def version_type_label(version_type: str) -> str:
    """把 JSON 中的版本类型转换成中文显示名称。"""

    return TYPE_LABELS.get(version_type, version_type or "未知")


def scan_local_versions(minecraft_dir: str | os.PathLike[str]) -> ScanResult:
    """扫描指定游戏目录下的 versions 文件夹。

    不存在的目录、缺失的 versions 文件夹、损坏的版本 JSON 都会以
    ``ScanIssue`` 的形式返回，调用方可以继续展示其他正常版本。
    """

    root = Path(minecraft_dir).expanduser()
    result = ScanResult(minecraft_dir=root)
    versions_dir = root / "versions"

    try:
        if not root.is_dir():
            result.issues.append(ScanIssue(root, "游戏目录不存在"))
            return result
        if not versions_dir.is_dir():
            result.issues.append(ScanIssue(versions_dir, "没有 versions 文件夹"))
            return result
        entries = sorted(versions_dir.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        result.issues.append(ScanIssue(versions_dir, f"无法读取目录：{exc}"))
        return result

    for folder in entries:
        # versions 文件夹里可能还有 manifest 之类的文件，只处理文件夹。
        if not folder.is_dir():
            continue

        metadata_path = folder / f"{folder.name}.json"
        if not metadata_path.is_file():
            # 例如 versions/1.21.1/ 下缺少 1.21.1.json，无法确认是有效版本，直接跳过。
            continue

        try:
            with metadata_path.open("r", encoding="utf-8-sig") as file:
                data = json.load(file)
        except Exception as exc:  # 单个版本损坏不应中断整个列表
            result.issues.append(ScanIssue(metadata_path, f"版本 JSON 读取失败：{exc}"))
            continue

        if not isinstance(data, dict):
            result.issues.append(ScanIssue(metadata_path, "版本 JSON 顶层必须是对象"))
            continue

        version_id = data.get("id")
        if not isinstance(version_id, str) or not version_id.strip():
            version_id = folder.name

        version_type = data.get("type")
        if not isinstance(version_type, str) or not version_type.strip():
            version_type = "unknown"

        inherits_from = data.get("inheritsFrom")
        if not isinstance(inherits_from, str) or not inherits_from.strip():
            inherits_from = None

        result.versions.append(
            LocalVersion(
                folder_name=folder.name,
                version_id=version_id.strip(),
                version_type=version_type.strip(),
                release_time=_parse_release_time(data.get("releaseTime")),
                inherits_from=inherits_from,
                directory=folder,
                has_client_jar=(folder / f"{folder.name}.jar").is_file(),
            )
        )

    # 先按名称排序，再按发布时间倒序；发布时间相同时名称顺序保持稳定。
    result.versions.sort(key=lambda version: version.version_id.casefold())
    result.versions.sort(key=_release_sort_key, reverse=True)
    return result


def _parse_release_time(raw_value: object) -> datetime | None:
    """解析 ISO 8601 时间；兼容 Z 结尾和没有冒号的时区。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        return None

    text = raw_value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # 极少数第三方版本写出的格式，Python 的 fromisoformat 也不接受。
        for pattern in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        else:
            return None

    # 没有时区的时间按 UTC 处理，保证所有版本之间可以比较。
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _release_sort_key(version: LocalVersion) -> datetime:
    """让没有发布时间的版本排在最后，同时避免 naive/aware 时间比较错误。"""

    fallback = datetime.min.replace(tzinfo=timezone.utc)
    release_time = version.release_time or fallback
    if release_time.tzinfo is None:
        release_time = release_time.replace(tzinfo=timezone.utc)
    return release_time.astimezone(timezone.utc)

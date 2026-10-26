"""本地版本详情扫描与安全删除。

详情只读取目录和文件信息，不启动游戏、不修改内容：
- 版本目录中的客户端 JAR；
- 游戏目录 / 版本目录下的 mods、resourcepacks、shaderpacks；
- 常见整合包清单（Modrinth / CurseForge / MultiMC）。

删除只允许删除 `.minecraft/versions/<版本目录>`，并且要求目录内存在
同名版本 JSON；不会删除全局 mods、resourcepacks 或其他版本。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from version_scanner import LocalVersion

MAX_MODPACK_MANIFEST_SIZE = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ContentItem:
    """一个 mod、资源包或光影包。"""

    name: str
    path: Path
    size: int
    source: str
    enabled: bool | None = None
    is_dir: bool = False


@dataclass(frozen=True, slots=True)
class ModpackInfo:
    """检测到的整合包清单。"""

    name: str
    kind: str
    version: str
    source: str


@dataclass(slots=True)
class VersionDetails:
    """版本详情的完整数据。"""

    version: LocalVersion
    minecraft_directory: Path
    client_jar: Path | None
    mods: list[ContentItem] = field(default_factory=list)
    resourcepacks: list[ContentItem] = field(default_factory=list)
    shaderpacks: list[ContentItem] = field(default_factory=list)
    modpack: ModpackInfo | None = None
    issues: list[str] = field(default_factory=list)


class VersionDeleteError(Exception):
    """删除版本失败。"""


def scan_version_details(version: LocalVersion, minecraft_directory: str | Path) -> VersionDetails:
    """扫描一个本地版本的详情。只读操作。"""

    mc_dir = Path(minecraft_directory).expanduser()
    version_dir = Path(version.directory)

    details = VersionDetails(
        version=version,
        minecraft_directory=mc_dir,
        client_jar=(
            version_dir / f"{version.folder_name}.jar"
            if (version_dir / f"{version.folder_name}.jar").is_file()
            else None
        ),
    )

    details.mods = _collect_mods(mc_dir / "mods", "游戏目录", details.issues)
    details.mods += _collect_mods(version_dir / "mods", "版本目录", details.issues)
    details.mods.sort(key=lambda item: (not bool(item.enabled), item.name.casefold()))

    details.resourcepacks = _collect_packs(
        mc_dir / "resourcepacks",
        "游戏目录",
        details.issues,
    )
    details.resourcepacks += _collect_packs(
        version_dir / "resourcepacks",
        "版本目录",
        details.issues,
    )
    details.resourcepacks.sort(key=lambda item: item.name.casefold())

    details.shaderpacks = _collect_packs(
        mc_dir / "shaderpacks",
        "游戏目录",
        details.issues,
    )
    details.shaderpacks += _collect_packs(
        version_dir / "shaderpacks",
        "版本目录",
        details.issues,
    )
    details.shaderpacks.sort(key=lambda item: item.name.casefold())

    details.modpack = _detect_modpack(version_dir, mc_dir)
    return details


def delete_version_folder(
    minecraft_directory: str | Path,
    folder_name: str,
) -> Path:
    """安全删除一个版本目录。

    只删除 `<minecraft>/versions/<folder_name>`，且必须满足：
    - folder_name 是单层目录名；
    - 目标目录恰好位于 versions 下；
    - 目录内存在 `<folder_name>.json`。
    """

    root = Path(minecraft_directory).expanduser()
    versions_root = (root / "versions").resolve()

    if not versions_root.is_dir():
        raise VersionDeleteError("versions 目录不存在")
    if not folder_name or Path(folder_name).name != folder_name:
        raise VersionDeleteError("版本目录名不合法")

    target = (versions_root / folder_name).resolve()
    if target.parent != versions_root:
        raise VersionDeleteError("拒绝删除 versions 之外的目录")
    if not target.is_dir():
        raise VersionDeleteError("版本目录不存在")
    if not (target / f"{folder_name}.json").is_file():
        raise VersionDeleteError("版本 JSON 不存在，已拒绝删除")

    try:
        shutil.rmtree(target)
    except OSError as exc:
        raise VersionDeleteError(f"删除失败：{exc}") from exc

    return target


def _collect_mods(directory: Path, source: str, issues: list[str]) -> list[ContentItem]:
    items: list[ContentItem] = []
    for child in _iter_directory(directory, issues):
        name = child.name
        if name.startswith(".") or child.is_dir():
            continue
        if not (name.endswith(".jar") or name.endswith(".jar.disabled")):
            continue
        size = _file_size(child, issues)
        items.append(
            ContentItem(
                name=name,
                path=child,
                size=size,
                source=source,
                enabled=not name.endswith(".disabled"),
            )
        )
    return items


def _collect_packs(directory: Path, source: str, issues: list[str]) -> list[ContentItem]:
    items: list[ContentItem] = []
    for child in _iter_directory(directory, issues):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            items.append(
                ContentItem(
                    name=child.name,
                    path=child,
                    size=0,
                    source=source,
                    is_dir=True,
                )
            )
        elif child.is_file() and child.suffix.lower() == ".zip":
            items.append(
                ContentItem(
                    name=child.name,
                    path=child,
                    size=_file_size(child, issues),
                    source=source,
                )
            )
    return items


def _iter_directory(directory: Path, issues: list[str]) -> list[Path]:
    if not directory.is_dir():
        return []
    try:
        return sorted(directory.iterdir(), key=lambda path: path.name.casefold())
    except OSError as exc:
        issues.append(f"无法读取 {directory}：{exc}")
        return []


def _file_size(path: Path, issues: list[str]) -> int:
    try:
        return path.stat().st_size
    except OSError as exc:
        issues.append(f"无法读取文件信息 {path.name}：{exc}")
        return 0


def _detect_modpack(version_dir: Path, minecraft_dir: Path) -> ModpackInfo | None:
    seen: set[Path] = set()
    for base, source in (
        (version_dir, "版本目录"),
        (minecraft_dir, "游戏目录"),
    ):
        try:
            resolved = base.resolve()
        except OSError:
            resolved = base
        if resolved in seen:
            continue
        seen.add(resolved)

        modrinth = _load_json(base / "modrinth.index.json")
        if isinstance(modrinth, dict) and modrinth.get("name"):
            return ModpackInfo(
                name=str(modrinth["name"]),
                kind="Modrinth",
                version=str(modrinth.get("versionId") or ""),
                source=source,
            )

        manifest = _load_json(base / "manifest.json")
        if (
            isinstance(manifest, dict)
            and manifest.get("manifestType") == "minecraftModpack"
            and manifest.get("name")
        ):
            return ModpackInfo(
                name=str(manifest["name"]),
                kind="CurseForge",
                version=str(manifest.get("version") or ""),
                source=source,
            )

        if (base / "mmc-pack.json").is_file():
            return ModpackInfo(
                name=_read_mmc_instance_name(base),
                kind="MultiMC",
                version="",
                source=source,
            )

    return None


def _read_mmc_instance_name(base: Path) -> str:
    cfg = base / "instance.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("name="):
                return line.split("=", 1)[1].strip() or base.name
    except OSError:
        pass
    return base.name


def _load_json(path: Path):
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_MODPACK_MANIFEST_SIZE:
            return None
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None

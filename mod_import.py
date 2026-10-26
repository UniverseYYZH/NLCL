"""拖拽导入：mods jar 与 Modrinth .mrpack 整合包。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests
from minecraft_launcher_lib.install import install_minecraft_version
from minecraft_launcher_lib.mod_loader import get_mod_loader
from minecraft_launcher_lib.utils import is_version_valid

from instance_registry import InstanceRegistry
from java_bindings import JavaBindingStore
from java_runtime import (
    component_for_major,
    install_java_runtime,
    recommend_java_major,
    runtime_executable,
)

Progress = Callable[[str], None]


class ImportErrorInfo(Exception):
    pass


@dataclass(frozen=True, slots=True)
class JarInfo:
    path: Path
    kind: str  # mod / fabric_loader / forge_loader
    name: str = ""


@dataclass(frozen=True, slots=True)
class MrpackInfo:
    path: Path
    name: str
    version_id: str
    minecraft: str
    loader: str
    loader_version: str
    files: list[dict]
    override_prefixes: tuple[str, ...] = ("overrides/", "client-overrides/")


def inspect_jar(path: str | Path) -> JarInfo:
    jar = Path(path)
    if jar.suffix.lower() != ".jar" or not jar.is_file():
        raise ImportErrorInfo("不是有效的 .jar 文件")
    try:
        with zipfile.ZipFile(jar) as archive:
            names = set(archive.namelist())
            if "install_profile.json" in names and any(
                name.startswith("net/minecraftforge/installer/") for name in names
            ):
                return JarInfo(jar, "forge_loader", jar.stem)
            if "fabric-installer.json" in names or any(
                name.startswith("net/fabricmc/installer/") for name in names
            ):
                return JarInfo(jar, "fabric_loader", jar.stem)
            if "fabric.mod.json" in names:
                try:
                    data = json.loads(archive.read("fabric.mod.json").decode("utf-8"))
                except Exception:
                    data = {}
                mod_id = str(data.get("id") or "")
                if mod_id in {"fabricloader", "fabric-loader"}:
                    return JarInfo(jar, "fabric_loader", jar.stem)
                return JarInfo(jar, "mod", str(data.get("name") or jar.stem))
            if "META-INF/mods.toml" in names:
                return JarInfo(jar, "mod", jar.stem)
    except zipfile.BadZipFile as exc:
        raise ImportErrorInfo("jar 文件损坏，无法读取") from exc
    return JarInfo(jar, "mod", jar.stem)


def copy_mod_jar(jar: str | Path, minecraft_root: str | Path) -> Path:
    source = Path(jar)
    mods = Path(minecraft_root) / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    target = mods / source.name
    suffix = 1
    while target.exists():
        target = mods / f"{source.stem}-{suffix}{source.suffix}"
        suffix += 1
    shutil.copy2(source, target)
    return target


def install_loader_for_instance(
    minecraft_root: str | Path,
    minecraft_version: str,
    mode: str,
    progress: Progress | None = None,
) -> str:
    """给现有实例安装 Fabric/Forge（用于拖入加载器安装器 jar）。"""

    root = Path(minecraft_root)
    callback = _callback(progress)
    java = _ensure_java(minecraft_version, root, progress)
    if not is_version_valid(minecraft_version, root):
        _progress(progress, f"安装原版 {minecraft_version}…")
        install_minecraft_version(minecraft_version, str(root), callback=callback)
    loader = get_mod_loader(mode)
    if not loader.is_minecraft_version_supported(minecraft_version):
        raise ImportErrorInfo(f"{minecraft_version} 不支持 {mode}")
    _progress(progress, f"安装 {mode} 加载器…")
    return loader.install(
        minecraft_version,
        str(root),
        callback=callback,
        java=java,
    )


def parse_mrpack(path: str | Path) -> MrpackInfo:
    mrpack = Path(path)
    if mrpack.suffix.lower() != ".mrpack" and mrpack.suffix.lower() != ".zip":
        raise ImportErrorInfo("请选择 Modrinth .mrpack 整合包")
    try:
        with zipfile.ZipFile(mrpack) as archive:
            raw = archive.read("modrinth.index.json")
            data = json.loads(raw.decode("utf-8"))
    except (KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ImportErrorInfo("不是有效的 Modrinth 整合包（缺少 modrinth.index.json）") from exc
    dependencies = data.get("dependencies") if isinstance(data.get("dependencies"), dict) else {}
    minecraft = str(dependencies.get("minecraft") or "").strip()
    if not minecraft:
        raise ImportErrorInfo("整合包没有声明 Minecraft 版本")
    if dependencies.get("fabric-loader"):
        loader, loader_version = "fabric", str(dependencies["fabric-loader"])
    elif dependencies.get("forge"):
        loader, loader_version = "forge", str(dependencies["forge"])
    elif dependencies.get("quilt-loader"):
        raise ImportErrorInfo("暂不支持 Quilt 整合包，请使用 Fabric/Forge 版本")
    elif dependencies.get("neoforge"):
        raise ImportErrorInfo("暂不支持 NeoForge 整合包")
    else:
        raise ImportErrorInfo("整合包没有声明 Fabric/Forge 加载器")
    files = data.get("files") if isinstance(data.get("files"), list) else []
    return MrpackInfo(
        path=mrpack,
        name=str(data.get("name") or mrpack.stem),
        version_id=str(data.get("versionId") or ""),
        minecraft=minecraft,
        loader=loader,
        loader_version=loader_version,
        files=[item for item in files if isinstance(item, dict)],
    )


def import_mrpack(
    info: MrpackInfo,
    progress: Progress | None = None,
    registry: InstanceRegistry | None = None,
) -> dict:
    """创建独立实例根目录，安装加载器/Java，部署 mods 与 overrides。"""

    registry = registry or InstanceRegistry()
    base_root = (
        Path(os.environ.get("APPDATA", str(Path.home()))) / "NLCL" / "instances"
    )
    slug = _slug(info.name or info.path.stem)
    root = base_root / f"{slug}-{int(time.time())}" / ".minecraft"
    root.mkdir(parents=True, exist_ok=True)

    _progress(progress, "准备 Java 运行时…")
    java = _ensure_java(info.minecraft, root, progress)
    callback = _callback(progress)
    if not is_version_valid(info.minecraft, root):
        _progress(progress, f"安装原版 {info.minecraft}…")
        install_minecraft_version(info.minecraft, str(root), callback=callback)

    loader = get_mod_loader(info.loader)
    if not loader.is_minecraft_version_supported(info.minecraft):
        raise ImportErrorInfo(f"{info.minecraft} 不支持 {info.loader}")
    _progress(progress, f"安装 {info.loader} {info.loader_version}…")
    installed_id = loader.install(
        info.minecraft,
        str(root),
        loader_version=info.loader_version,
        callback=callback,
        java=java,
    )

    alias = _unique_alias(root, f"NLCL-{slug}")
    _rename_version(root, installed_id, alias, f"{info.name} {info.version_id}".strip())
    _deploy_files(info, root, progress)
    _extract_overrides(info.path, root, progress)

    entry = registry.add(
        info.name,
        root,
        alias,
        loader=info.loader,
        minecraft_version=info.minecraft,
    )
    major = recommend_java_major(info.minecraft)
    JavaBindingStore().set(
        alias,
        java,
        major,
        component_for_major(major),
    )
    _write_instance_metadata(root, entry, info)
    _progress(progress, f"实例已创建：{info.name}")
    return entry


def _ensure_java(base_version: str, root: Path, progress: Progress | None) -> str:
    major = recommend_java_major(base_version)
    component = component_for_major(major)
    executable = runtime_executable(component, root)
    if not executable:
        _progress(progress, f"下载 Java {major}（{component}）…")
        install_java_runtime(component, root)
        executable = runtime_executable(component, root)
    if not executable:
        raise ImportErrorInfo("无法准备整合包所需的 Java")
    return executable


def _deploy_files(info: MrpackInfo, root: Path, progress: Progress | None) -> None:
    total = len(info.files)
    for index, item in enumerate(info.files, start=1):
        env = item.get("env") if isinstance(item.get("env"), dict) else {}
        if env.get("client") == "unsupported":
            continue
        relative = str(item.get("path") or "")
        if not relative:
            continue
        target = _safe_target(root, relative)
        urls = item.get("downloads") if isinstance(item.get("downloads"), list) else []
        if not urls:
            continue
        _progress(progress, f"下载整合包文件 {index}/{total}：{target.name}")
        response = requests.get(str(urls[0]), timeout=60)
        response.raise_for_status()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        expected = item.get("hashes") if isinstance(item.get("hashes"), dict) else {}
        sha1 = expected.get("sha1")
        if isinstance(sha1, str) and sha1:
            actual = hashlib.sha1(target.read_bytes()).hexdigest()
            if actual.lower() != sha1.lower():
                raise ImportErrorInfo(f"文件校验失败：{relative}")


def _extract_overrides(mrpack: Path, root: Path, progress: Progress | None) -> None:
    _progress(progress, "部署整合包配置与覆盖文件…")
    with zipfile.ZipFile(mrpack) as archive:
        # overrides 先部署，client-overrides 最后覆盖客户端专属文件。
        for prefix in ("overrides/", "client-overrides/"):
            for name in archive.namelist():
                if not name.startswith(prefix) or name.endswith("/"):
                    continue
                relative = name[len(prefix) :]
                target = _safe_target(root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)


def _rename_version(
    root: Path,
    installed_id: str,
    alias: str,
    display_id: str,
) -> None:
    source = root / "versions" / installed_id
    if not source.is_dir():
        raise ImportErrorInfo(f"加载器安装后未找到版本目录：{installed_id}")
    target = root / "versions" / alias
    if target.exists():
        shutil.rmtree(target)
    source.rename(target)
    old_json = target / f"{installed_id}.json"
    if not old_json.is_file():
        raise ImportErrorInfo(f"加载器版本缺少 JSON：{old_json}")
    if old_json.is_file():
        try:
            data = json.loads(old_json.read_text(encoding="utf-8-sig"))
        except Exception:
            data = {}
        if isinstance(data, dict):
            data["id"] = display_id
            (target / f"{alias}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            old_json.unlink(missing_ok=True)
    old_jar = target / f"{installed_id}.jar"
    if old_jar.is_file():
        old_jar.rename(target / f"{alias}.jar")


def _unique_alias(root: Path, base: str) -> str:
    alias = re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-") or "NLCL-instance"
    candidate = alias
    index = 1
    while (root / "versions" / candidate).exists():
        index += 1
        candidate = f"{alias}-{index}"
    return candidate


def _safe_target(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise ImportErrorInfo(f"整合包包含非法路径：{relative}")
    return target


def _write_instance_metadata(root: Path, entry: dict, info: MrpackInfo) -> None:
    data = {**entry, "modrinth_name": info.name, "modrinth_version": info.version_id}
    (root / ".nlcl-instance.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-").lower()
    return slug[:40] or "modpack"


def _callback(progress: Progress | None) -> dict:
    def set_status(text: str) -> None:
        _progress(progress, str(text))

    return {
        "setStatus": set_status,
        "setMax": lambda _value: None,
        "setProgress": lambda _value: None,
    }


def _progress(progress: Progress | None, message: str) -> None:
    if progress is not None:
        try:
            progress(message)
        except Exception:
            pass

"""游戏启动前检查、JVM 参数与 minecraft-launcher-lib 启动命令构建。"""

from __future__ import annotations

import ctypes
import json
import os
import shlex
import zipfile
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from minecraft_launcher_lib.command import get_minecraft_command
from minecraft_launcher_lib.natives import (
    get_library_path,
    get_natives,
    inherit_json,
    parse_rule_list,
)

from account_manager import Account
from launch_settings import JavaInfo, LaunchSettings
from version_scanner import LocalVersion


class LaunchError(Exception):
    """启动前检查或命令构建失败。"""


@dataclass(frozen=True, slots=True)
class VersionCheck:
    client_jar: Path
    warnings: tuple[str, ...] = ()
    required_java_major: int | None = None


@dataclass(frozen=True, slots=True)
class VersionValidation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    client_jar: Path | None
    required_java_major: int | None


@dataclass(frozen=True, slots=True)
class NativesResult:
    directory: Path
    extracted: int
    warnings: tuple[str, ...] = ()


def validate_version_installation(
    version: LocalVersion,
    minecraft_directory: str | Path,
) -> VersionValidation:
    """检查版本 JSON、客户端 JAR、资源索引、依赖库和 Java 版本要求。"""

    root = Path(minecraft_directory)
    label = version.version_id or version.folder_name
    errors: list[str] = []
    warnings: list[str] = []

    if not version.directory.is_dir():
        return VersionValidation(
            errors=(f"版本「{label}」目录不存在：{version.directory}",),
            warnings=(),
            client_jar=None,
            required_java_major=None,
        )

    json_path = version.directory / f"{version.folder_name}.json"
    if not json_path.is_file():
        return VersionValidation(
            errors=(f"版本「{label}」缺少版本 JSON：{json_path}",),
            warnings=(),
            client_jar=None,
            required_java_major=None,
        )

    try:
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        if data.get("inheritsFrom"):
            data = inherit_json(data, root)
    except Exception as exc:
        return VersionValidation(
            errors=(f"版本「{label}」的 JSON 无法读取：{exc}",),
            warnings=(),
            client_jar=None,
            required_java_major=None,
        )

    if not isinstance(data, dict):
        return VersionValidation(
            errors=(f"版本「{label}」的 JSON 格式不正确",),
            warnings=(),
            client_jar=None,
            required_java_major=None,
        )

    required_java: int | None = None
    java_data = data.get("javaVersion")
    if isinstance(java_data, dict):
        try:
            required_java = int(java_data.get("majorVersion"))
        except (TypeError, ValueError):
            warnings.append(f"版本「{label}」没有声明可识别的 Java 版本")

    if not data.get("mainClass"):
        errors.append(f"版本「{label}」的 JSON 缺少 mainClass，无法启动")

    client_jar = resolve_client_jar(version, root)
    if client_jar is None:
        errors.append(
            f"版本「{label}」缺少客户端 JAR："
            f"versions/{version.folder_name}/{version.folder_name}.jar"
        )

    libraries_dir = root / "libraries"
    assets_dir = root / "assets"
    if not libraries_dir.is_dir():
        errors.append(f"版本「{label}」缺少 libraries 目录：{libraries_dir}")
    if not assets_dir.is_dir():
        errors.append(f"版本「{label}」缺少 assets 目录：{assets_dir}")

    asset_index = data.get("assetIndex")
    if isinstance(asset_index, dict) and asset_index.get("id"):
        index_path = assets_dir / "indexes" / f"{asset_index['id']}.json"
        if not index_path.is_file():
            errors.append(f"版本「{label}」缺少资源索引：{index_path}")

    libraries = data.get("libraries")
    if isinstance(libraries, list):
        missing_libraries: list[Path] = []
        for library in libraries:
            if not isinstance(library, dict):
                continue
            rules = library.get("rules")
            if isinstance(rules, list) and not parse_rule_list(rules, {}):
                continue
            downloads = library.get("downloads")
            if not isinstance(downloads, dict):
                continue
            artifact = downloads.get("artifact")
            if not isinstance(artifact, dict):
                continue
            artifact_path = artifact.get("path")
            if not artifact_path:
                continue
            path = libraries_dir / str(artifact_path)
            if not path.is_file():
                missing_libraries.append(path)

        if missing_libraries:
            for path in missing_libraries[:5]:
                errors.append(f"版本「{label}」缺少依赖库：{path}")
            if len(missing_libraries) > 5:
                errors.append(
                    f"版本「{label}」共缺少 {len(missing_libraries)} 个依赖库，"
                    "请通过下载模块重新安装该版本。"
                )
    else:
        errors.append(f"版本「{label}」的 JSON 没有 libraries 列表")

    return VersionValidation(
        errors=tuple(errors),
        warnings=tuple(warnings),
        client_jar=client_jar,
        required_java_major=required_java,
    )


def check_version_files(
    version: LocalVersion,
    minecraft_directory: str | Path,
) -> VersionCheck:
    """检查版本完整性；失败时返回清晰、可读的合并错误。"""

    validation = validate_version_installation(version, minecraft_directory)
    if validation.errors:
        raise LaunchError("\n".join(validation.errors))
    if validation.client_jar is None:
        raise LaunchError(f"版本「{version.version_id}」缺少客户端 JAR")

    return VersionCheck(
        client_jar=validation.client_jar,
        warnings=validation.warnings,
        required_java_major=validation.required_java_major,
    )


def resolve_client_jar(
    version: LocalVersion,
    minecraft_directory: str | Path,
) -> Path | None:
    """查找当前版本或继承版本的客户端 JAR。"""

    direct = version.directory / f"{version.folder_name}.jar"
    if direct.is_file():
        return direct

    parent_id = version.inherits_from
    if parent_id:
        parent_jar = Path(minecraft_directory) / "versions" / parent_id / f"{parent_id}.jar"
        if parent_jar.is_file():
            return parent_jar
    return None


def ensure_natives(
    version: LocalVersion,
    minecraft_directory: str | Path,
) -> NativesResult:
    """把版本 JSON 中的 Windows 本地库解压到 versions/<版本>/natives。

    某些启动器/旧版本不会在版本目录保留 natives，Minecraft 启动时会找不到
    lwjgl.dll 等本地库。这里在每次启动前做一次幂等准备。
    """

    root = Path(minecraft_directory)
    json_path = version.directory / f"{version.folder_name}.json"
    if not json_path.is_file():
        raise LaunchError(f"缺少版本 JSON：{json_path}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        if data.get("inheritsFrom"):
            data = inherit_json(data, root)
    except Exception as exc:
        raise LaunchError(f"无法读取版本 JSON：{exc}") from exc

    natives_dir = version.directory / "natives"
    natives_dir.mkdir(parents=True, exist_ok=True)

    jar_paths: set[Path] = set()
    warnings: list[str] = []

    for library in data.get("libraries", []):
        if not isinstance(library, dict):
            continue
        rules = library.get("rules")
        if isinstance(rules, list) and not parse_rule_list(rules, {}):
            continue

        name = str(library.get("name") or "")
        downloads = library.get("downloads")
        if not isinstance(downloads, dict):
            downloads = {}

        # 现代版本 JSON 使用 natives-windows classifier。
        if "natives-windows" in name and not any(
            suffix in name
            for suffix in ("natives-windows-arm64", "natives-windows-x86")
        ):
            artifact = downloads.get("artifact")
            if isinstance(artifact, dict) and artifact.get("path"):
                jar_paths.add(root / "libraries" / str(artifact["path"]))

        classifiers = downloads.get("classifiers")
        if isinstance(classifiers, dict):
            for key in ("natives-windows", "natives-windows-64"):
                artifact = classifiers.get(key)
                if isinstance(artifact, dict) and artifact.get("path"):
                    jar_paths.add(root / "libraries" / str(artifact["path"]))

        # 旧版本 JSON 使用 natives 字段。
        native = get_natives(library)
        if native:
            library_path, extension = os.path.splitext(get_library_path(name, root))
            jar_paths.add(Path(f"{library_path}-{native}{extension}"))

    extracted = 0
    for jar_path in sorted(jar_paths):
        if not jar_path.is_file():
            warnings.append(f"缺少本地库文件：{jar_path.name}")
            continue
        try:
            with zipfile.ZipFile(jar_path) as archive:
                for member in archive.namelist():
                    if not member.lower().endswith((".dll", ".so", ".dylib")):
                        continue
                    target = natives_dir / Path(member).name
                    target.write_bytes(archive.read(member))
                    extracted += 1
        except (OSError, zipfile.BadZipFile) as exc:
            warnings.append(f"解压本地库失败：{jar_path.name}（{exc}）")

    if extracted == 0 and not warnings:
        warnings.append("没有找到可解压的 Windows 本地库")

    return NativesResult(
        directory=natives_dir,
        extracted=extracted,
        warnings=tuple(warnings),
    )


def split_jvm_args(raw_args: str) -> list[str]:
    """把自定义 JVM 参数字符串拆成参数列表，支持引号。

    Windows 下使用 CommandLineToArgvW，避免 POSIX shlex 把 ``C:\\path``
    中的反斜杠当成转义符。
    """

    text = (raw_args or "").strip()
    if not text:
        return []
    if text.count('"') % 2:
        raise LaunchError("自定义 JVM 参数格式错误：引号没有闭合")
    try:
        if os.name == "nt":
            return _split_windows_command_line(text)
        return [part for part in shlex.split(text, posix=True) if part]
    except (ValueError, OSError) as exc:
        raise LaunchError(f"自定义 JVM 参数格式错误：{exc}") from exc


def _split_windows_command_line(text: str) -> list[str]:
    shell32 = ctypes.windll.shell32
    argc = ctypes.c_int()
    shell32.CommandLineToArgvW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_int),
    ]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)

    # CommandLineToArgvW 会把第一个 token 当成程序名，因此补一个占位程序名。
    argv = shell32.CommandLineToArgvW(f"java {text}", ctypes.byref(argc))
    if not argv:
        raise OSError("CommandLineToArgvW 解析失败")
    try:
        return [argv[index] for index in range(1, argc.value) if argv[index]]
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(argv)


def build_minecraft_command(
    version: LocalVersion,
    minecraft_directory: str | Path,
    account: Account,
    settings: LaunchSettings,
    java_path: str,
    minecraft_token: str,
) -> list[str]:
    """调用 minecraft-launcher-lib 构建完整启动命令。"""

    if not account.name or not account.uuid:
        raise LaunchError("账号信息不完整，请重新登录")

    custom_args = split_jvm_args(settings.jvm_args)
    jvm_arguments = [
        f"-Xms{settings.min_memory_mb}M",
        f"-Xmx{settings.max_memory_mb}M",
        *custom_args,
    ]

    options = {
        "username": account.name,
        "uuid": account.uuid,
        "token": minecraft_token or "0",
        "executablePath": java_path,
        "jvmArguments": jvm_arguments,
        "launcherName": "NLMCL",
        "launcherVersion": "0.5",
        "gameDirectory": str(minecraft_directory),
    }

    try:
        return get_minecraft_command(
            version.folder_name,
            str(minecraft_directory),
            options,
        )
    except Exception as exc:
        raise LaunchError(f"无法生成启动命令：{exc}") from exc


def with_server_address(command: list[str], host: str, port: int) -> list[str]:
    """给启动命令追加直连服务器参数。"""

    return [*command, "--server", host, "--port", str(port)]


def account_launch_token(account: Account, refreshed_token: str = "") -> str:
    """离线账号使用占位 token；微软账号使用刷新后的 Minecraft token。"""

    if account.is_microsoft:
        if not refreshed_token:
            raise LaunchError("微软账号凭证为空，请重新登录")
        return refreshed_token
    return "0"


def memory_summary(settings: LaunchSettings) -> str:
    return f"{settings.min_memory_mb} - {settings.max_memory_mb} MB"


def java_summary(java_info: JavaInfo | None, settings: LaunchSettings) -> str:
    if java_info is not None:
        return f"Java {java_info.version}"
    if settings.java_version:
        return f"Java {settings.java_version}（待校验）"
    return "Java 未配置"

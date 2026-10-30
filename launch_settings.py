"""Java 与启动参数配置：JSON 持久化、内存规范化、Java 17 校验。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SETTINGS_FILE_VERSION = 1
MIN_MEMORY_MB = 512
MAX_MEMORY_MB = 32768
MIN_MEMORY_SLIDER_MAX = 16384
MAX_MEMORY_SLIDER_MIN = 1024


class LaunchSettingsError(Exception):
    """启动设置读写失败。"""


class JavaValidationError(Exception):
    """Java 路径或版本不符合要求。"""


@dataclass(slots=True)
class LaunchSettings:
    java_path: str = ""
    java_version: str = ""
    java_major: int = 0
    min_memory_mb: int = 1024
    max_memory_mb: int = 4096
    jvm_args: str = ""

    def normalized(self) -> "LaunchSettings":
        """限制内存范围，并保证最小内存不大于最大内存。"""

        min_memory = _clamp_int(self.min_memory_mb, MIN_MEMORY_MB, MIN_MEMORY_SLIDER_MAX)
        max_memory = _clamp_int(self.max_memory_mb, MAX_MEMORY_SLIDER_MIN, MAX_MEMORY_MB)
        if max_memory < min_memory:
            max_memory = min_memory
        return LaunchSettings(
            java_path=self.java_path.strip(),
            java_version=self.java_version.strip(),
            java_major=max(0, int(self.java_major or 0)),
            min_memory_mb=min_memory,
            max_memory_mb=max_memory,
            jvm_args=self.jvm_args,
        )


@dataclass(frozen=True, slots=True)
class JavaInfo:
    path: str
    version: str
    major: int
    output: str = ""


def default_launch_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "NLMCL" / "launch_settings.json"
    return Path.home() / ".nlcl" / "launch_settings.json"


def parse_java_version(output: str) -> tuple[str, int]:
    """从 java -version 输出中解析版本字符串和主版本号。"""

    match = re.search(r'version\s+"([^"]+)"', output or "", re.IGNORECASE)
    if not match:
        raise JavaValidationError("没有从 java -version 输出中找到版本号")

    version = match.group(1).strip()
    parts = version.split(".")
    try:
        if parts[0] == "1" and len(parts) > 1:
            major = int(parts[1])
        else:
            major = int(parts[0])
    except (ValueError, IndexError) as exc:
        raise JavaValidationError(f"无法识别 Java 版本：{version}") from exc

    return version, major


def validate_java_17(java_path: str) -> JavaInfo:
    """校验指定路径是可运行的 Java 17。

    该函数会启动子进程，调用方应放到后台线程执行。
    """

    path = _resolve_java_executable(java_path)
    command = [str(path), "-version"]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=10,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise JavaValidationError("校验超时：java -version 超过 10 秒没有响应") from exc
    except OSError as exc:
        raise JavaValidationError(f"无法运行 Java：{exc}") from exc

    raw_output = (completed.stdout or b"") + (completed.stderr or b"")
    output = _decode_java_output(raw_output)
    version, major = parse_java_version(output)

    if major != 17:
        raise JavaValidationError(
            f"检测到 Java {version}（主版本 {major}），本启动器需要 Java 17"
        )

    return JavaInfo(path=str(path), version=version, major=major, output=output)


class LaunchSettingsStore:
    """启动设置 JSON 存储。

    默认路径：%APPDATA%\\NLMCL\\launch_settings.json
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_launch_settings_path()
        self.settings = self.load()

    def load(self) -> LaunchSettings:
        if not self.path.is_file():
            return LaunchSettings()

        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return LaunchSettings()

        if not isinstance(data, dict):
            return LaunchSettings()

        java = data.get("java")
        memory = data.get("memory")
        if not isinstance(java, dict):
            java = {}
        if not isinstance(memory, dict):
            memory = {}

        settings = LaunchSettings(
            java_path=str(java.get("path") or ""),
            java_version=str(java.get("version") or ""),
            java_major=_to_int(java.get("major"), 0),
            min_memory_mb=_to_int(memory.get("min_mb"), 1024),
            max_memory_mb=_to_int(memory.get("max_mb"), 4096),
            jvm_args=str(data.get("jvm_args") or ""),
        )
        return settings.normalized()

    def save(self, settings: LaunchSettings) -> LaunchSettings:
        normalized = settings.normalized()
        data = {
            "version": SETTINGS_FILE_VERSION,
            "java": {
                "path": normalized.java_path,
                "version": normalized.java_version,
                "major": normalized.java_major,
            },
            "memory": {
                "min_mb": normalized.min_memory_mb,
                "max_mb": normalized.max_memory_mb,
            },
            "jvm_args": normalized.jvm_args,
        }

        temp_path = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # 与账号文件相同：兼容 Windows Store/MSIX 的 AppData 重定向，
            # 不使用可能跨盘的 os.replace()。
            shutil.copyfile(temp_path, self.path)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        except OSError as exc:
            raise LaunchSettingsError(f"设置保存失败：{exc}") from exc

        self.settings = normalized
        return normalized


def _resolve_java_executable(java_path: str) -> Path:
    raw = (java_path or "").strip().strip('"')
    if not raw:
        raise JavaValidationError("请选择 Java 路径")

    path = Path(raw).expanduser()
    if path.is_dir():
        path = path / "bin" / "java.exe"

    if path.name.lower() == "javaw.exe":
        java_exe = path.with_name("java.exe")
        if java_exe.is_file():
            path = java_exe

    if not path.is_file():
        raise JavaValidationError(f"找不到 Java 可执行文件：{path}")
    return path


def _decode_java_output(raw: bytes) -> str:
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clamp_int(value: object, minimum: int, maximum: int) -> int:
    number = _to_int(value, minimum)
    return max(minimum, min(maximum, number))


def _to_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

"""Minecraft 版本对应的 Java 版本推荐与 Mojang 运行时查询。

下载页面用这里的纯函数/网络辅助函数决定：
- 这个 Minecraft 版本建议使用 Java 几；
- 对应 Mojang 运行时组件（jre-legacy / gamma / delta / epsilon）。
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import requests
from minecraft_launcher_lib import runtime
from minecraft_launcher_lib.natives import inherit_json

from launch_settings import JavaInfo
from version_scanner import LocalVersion

DEFAULT_TIMEOUT = 15
USER_AGENT = "NLMCL/0.8"

# Mojang 官方 JVM 运行时组件。Java 25 使用 epsilon。
JAVA_COMPONENTS: dict[int, str] = {
    8: "jre-legacy",
    16: "java-runtime-alpha",
    17: "java-runtime-gamma",
    21: "java-runtime-delta",
    25: "java-runtime-epsilon",
}

_RECOMMENDATION_CACHE: dict[str, tuple[int | None, str | None]] = {}
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class JavaRecommendation:
    major: int
    component: str
    source: str = "fallback"
    note: str = ""

    @property
    def title(self) -> str:
        return f"Java {self.major}"

    @property
    def detail(self) -> str:
        return f"{self.title} · {self.component}"

    @property
    def is_exact(self) -> bool:
        return self.source == "version-json"


def component_for_major(major: int) -> str:
    """把 Java 主版本映射到 Mojang 运行时组件名。"""

    if major in JAVA_COMPONENTS:
        return JAVA_COMPONENTS[major]
    # 对未知的新版本给出最接近的已知运行时，界面仍会显示真实主版本。
    if major >= 25:
        return "java-runtime-epsilon"
    if major >= 21:
        return "java-runtime-delta"
    if major >= 17:
        return "java-runtime-gamma"
    if major >= 16:
        return "java-runtime-alpha"
    return "jre-legacy"


def recommend_java_major(version_id: str) -> int:
    """在无法读取版本 JSON 时，按 Minecraft 版本号给出可靠兜底推荐。"""

    value = (version_id or "").strip().lower()

    # 新的 26.x 版本线：26.2 起要求 Java 25，26.1 为 Java 21。
    match = re.match(r"^26\.(\d+)", value)
    if match:
        return 25 if int(match.group(1)) >= 2 else 21

    match = re.match(r"^1\.(\d+)(?:\.(\d+))?", value)
    if match:
        minor = int(match.group(1))
        patch = int(match.group(2) or 0)
        if minor >= 21:
            return 21
        if minor == 20 and patch >= 5:
            return 21
        if minor >= 18:
            return 17
        if minor == 17:
            return 16
        return 8

    # 快照/旧预览版没有稳定规则时，现代启动器默认 Java 17；
    # 如果能拿到版本 JSON，会优先使用精确的 javaVersion。
    return 17


def parse_version_java(data: dict) -> tuple[int | None, str | None]:
    """从 Mojang version JSON 读取 javaVersion。"""

    java_version = data.get("javaVersion")
    if not isinstance(java_version, dict):
        return None, None
    major: int | None = None
    try:
        major = int(java_version.get("majorVersion"))
    except (TypeError, ValueError):
        pass
    component = java_version.get("component")
    if not isinstance(component, str) or not component.strip():
        component = None
    if major is not None and component is None:
        component = component_for_major(major)
    return major, component


def fetch_java_recommendation(
    version_id: str,
    version_url: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> JavaRecommendation:
    """读取官方 version JSON 的 Java 要求；网络失败时使用版本号兜底。"""

    fallback_major = recommend_java_major(version_id)
    fallback = JavaRecommendation(
        major=fallback_major,
        component=component_for_major(fallback_major),
        source="fallback",
    )
    if not version_url:
        return fallback

    with _CACHE_LOCK:
        cached = _RECOMMENDATION_CACHE.get(version_url)
    if cached is not None:
        major, component = cached
        if major is None:
            return fallback
        return JavaRecommendation(
            major=major,
            component=component or component_for_major(major),
            source="version-json",
        )

    try:
        response = requests.get(
            version_url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()
        major, component = parse_version_java(data if isinstance(data, dict) else {})
    except Exception:
        major, component = None, None

    with _CACHE_LOCK:
        if major is not None:
            _RECOMMENDATION_CACHE[version_url] = (major, component)

    if major is None:
        return fallback
    return JavaRecommendation(
        major=major,
        component=component or component_for_major(major),
        source="version-json",
    )


def runtime_executable(component: str, minecraft_directory: str | Path) -> str | None:
    """返回已安装运行时的 java.exe；未安装时返回 None。"""

    try:
        return runtime.get_executable_path(component, str(minecraft_directory))
    except Exception:
        return None


def runtime_installed(component: str, minecraft_directory: str | Path) -> bool:
    return runtime_executable(component, minecraft_directory) is not None


def read_local_version_java(version: LocalVersion) -> JavaRecommendation:
    """从本地版本 JSON（含继承）读取 Java 要求。"""

    fallback_major = recommend_java_major(version.version_id)
    fallback = JavaRecommendation(
        major=fallback_major,
        component=component_for_major(fallback_major),
    )
    json_path = version.directory / f"{version.folder_name}.json"
    try:
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        if data.get("inheritsFrom"):
            data = inherit_json(data, version.directory.parent.parent)
        major, component = parse_version_java(data if isinstance(data, dict) else {})
    except Exception:
        return fallback
    if major is None:
        return fallback
    return JavaRecommendation(
        major=major,
        component=component or component_for_major(major),
        source="version-json",
    )


def inspect_java(java_path: str | Path, timeout: float = 15) -> JavaInfo:
    """运行 java -version，返回任意主版本的 JavaInfo（供实例绑定使用）。"""

    executable = Path(java_path)
    if not executable.is_file():
        raise FileNotFoundError(f"Java 不存在：{executable}")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [str(executable), "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=flags,
    )
    output = (result.stderr or "") + (result.stdout or "")
    match = re.search(r'version\s+"([^"]+)"', output)
    if match is None:
        raise ValueError(f"无法识别 Java 版本：{output.strip()[:200]}")
    version = match.group(1)
    if version.startswith("1."):
        major = int(version.split(".")[1])
    else:
        major = int(re.match(r"\d+", version).group(0))
    return JavaInfo(path=str(executable), version=version, major=major)


def install_java_runtime(
    component: str,
    minecraft_directory: str | Path,
    callback: dict | None = None,
) -> None:
    """安装 Mojang 运行时；网络瞬断时自动重试一次。"""

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            runtime.install_jvm_runtime(
                component,
                str(minecraft_directory),
                callback=callback,
            )
            return
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                if callback and "setStatus" in callback:
                    callback["setStatus"]("网络中断，正在重试 Java 下载…")
                continue
    if last_error is not None:
        raise last_error

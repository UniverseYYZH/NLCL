"""Minecraft 版本列表获取与通用后台安装任务。

- 版本列表来自 Mojang 官方 version_manifest_v2.json；
- 原版下载调用 install_minecraft_version；
- Fabric / Forge / Java 运行时通过 installer 参数复用同一个后台任务；
- 下载在后台线程运行，UI 只读取 DownloadSnapshot。

注意：minecraft-launcher-lib 的进度回调是“文件数量”进度，不是字节进度，
且依赖库、资源文件、Java 运行时、客户端 JAR 会分阶段重置。这里把各阶段
映射到一条 0~100 的总进度上，尽量保持进度条单调前进。
速度则通过统计 urllib3 实际读取的网络字节数来计算。
"""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import requests
from urllib3.response import HTTPResponse as Urllib3HTTPResponse

from minecraft_launcher_lib.install import install_minecraft_version

MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
DOWNLOAD_MANIFEST_TIMEOUT = 20

# mll 的阶段顺序：版本 JSON -> 依赖库 -> 资源文件 -> 客户端 JAR -> Java 运行时。
# 每个阶段映射到总进度的一段，避免进度条在阶段切换时倒退。
_PHASE_SPANS = {
    "prepare": (0.0, 1.0),
    "metadata": (1.0, 3.0),
    "libraries": (3.0, 30.0),
    "assets": (30.0, 75.0),
    "client": (75.0, 80.0),
    "runtime": (80.0, 98.0),
    "complete": (100.0, 100.0),
}


@dataclass(frozen=True, slots=True)
class VanillaVersion:
    """一个可以下载的官方原版版本。"""

    version_id: str
    version_type: str
    release_time: datetime | None
    # 官方 version JSON 地址；用于读取该版本要求的 Java 版本。
    url: str = ""


@dataclass(frozen=True, slots=True)
class DownloadSnapshot:
    """下载任务在某一时刻的快照，供 UI 定时读取。"""

    status: str
    percent: float
    current: int
    total: int
    bytes_received: int
    done: bool
    success: bool
    error: str
    elapsed: float


class _HttpByteCounter:
    """统计本进程通过 urllib3 读取的 HTTP 响应字节数。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = 0

    @property
    def value(self) -> int:
        with self._lock:
            return self._value

    def add(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            self._value += count


_HTTP_PATCH_LOCK = threading.Lock()


@contextlib.contextmanager
def _count_http_downloads(counter: _HttpByteCounter):
    """临时给 urllib3 的 read() 计数。

    minecraft-launcher-lib 下载文件时使用 requests 的流式响应，并最终调用
    urllib3 HTTPResponse.read()。这个包装只在本进程下载期间生效，退出时恢复。
    同一时间只允许一个下载任务，避免两个任务互相覆盖 patch。
    """

    with _HTTP_PATCH_LOCK:
        original_read = Urllib3HTTPResponse.read

        def counted_read(response, *args, **kwargs):
            data = original_read(response, *args, **kwargs)
            if data:
                counter.add(len(data))
            return data

        Urllib3HTTPResponse.read = counted_read
        try:
            yield counter
        finally:
            Urllib3HTTPResponse.read = original_read


def parse_version_manifest(data: dict) -> list[VanillaVersion]:
    """从官方 manifest JSON 中提取正式版和快照，并按时间倒序排列。

    独立成纯函数，便于测试，不依赖网络。
    """

    versions: list[VanillaVersion] = []
    raw_versions = data.get("versions", [])
    if not isinstance(raw_versions, list):
        return versions

    for item in raw_versions:
        if not isinstance(item, dict):
            continue

        version_id = item.get("id")
        version_type = item.get("type")
        if not isinstance(version_id, str) or not version_id.strip():
            continue
        if version_type not in ("release", "snapshot"):
            continue

        release_time = _parse_datetime(item.get("releaseTime"))
        url = item.get("url")
        versions.append(
            VanillaVersion(
                version_id=version_id.strip(),
                version_type=version_type,
                release_time=release_time,
                url=url.strip() if isinstance(url, str) else "",
            )
        )

    versions.sort(key=_version_sort_key, reverse=True)
    return versions


def fetch_vanilla_versions(timeout: float = DOWNLOAD_MANIFEST_TIMEOUT) -> list[VanillaVersion]:
    """从 Mojang 获取原版版本列表。"""

    response = requests.get(
        MANIFEST_URL,
        timeout=timeout,
        headers={"User-Agent": "NLCL/0.1"},
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("版本列表格式不正确")
    return parse_version_manifest(data)


class VersionDownloadTask:
    """在后台线程中下载一个原版版本。

    UI 调用 start() 后，通过 snapshot() 定时读取状态，并通过
    page.run_task 的协程刷新控件，主线程不会被阻塞。
    """

    def __init__(
        self,
        version_id: str,
        minecraft_directory: str,
        *,
        installer: Callable[..., None] | None = None,
        progress_span: tuple[float, float] | None = None,
    ) -> None:
        self.version_id = version_id
        self.minecraft_directory = str(minecraft_directory)
        self._installer = installer or install_minecraft_version
        self._progress_span = progress_span

        self._lock = threading.Lock()
        self._byte_counter = _HttpByteCounter()
        self._thread: threading.Thread | None = None
        self._started_at = 0.0

        self._status = "准备下载…"
        self._phase = "prepare"
        self._percent = 0.0
        self._current = 0
        self._total = 0

        self._done = False
        self._success = False
        self._error = ""

    def start(self) -> None:
        """启动后台下载线程；重复调用不会启动第二个线程。"""

        if self._thread is not None:
            return

        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=self._run,
            name=f"nlcl-download-{self.version_id}",
            daemon=True,
        )
        self._thread.start()

    def snapshot(self) -> DownloadSnapshot:
        """线程安全地读取当前状态。"""

        with self._lock:
            return DownloadSnapshot(
                status=self._status,
                percent=round(self._percent, 1),
                current=self._current,
                total=self._total,
                bytes_received=self._byte_counter.value,
                done=self._done,
                success=self._success,
                error=self._error,
                elapsed=max(time.monotonic() - self._started_at, 0.0),
            )

    # ---- 后台线程和 mll 回调 ------------------------------------------------
    def _run(self) -> None:
        callback = {
            "setStatus": self._on_status,
            "setProgress": self._on_progress,
            "setMax": self._on_max,
        }

        try:
            with _count_http_downloads(self._byte_counter):
                self._installer(
                    self.version_id,
                    self.minecraft_directory,
                    callback=callback,
                )
        except Exception as exc:
            with self._lock:
                self._status = "下载失败"
                self._error = str(exc) or type(exc).__name__
                self._done = True
                self._success = False
            return

        with self._lock:
            self._percent = 100.0
            self._status = "下载完成"
            self._done = True
            self._success = True
            self._error = ""

    def _on_status(self, raw_status: str) -> None:
        phase = self._phase
        if raw_status == "Download Libraries":
            phase = "libraries"
        elif raw_status == "Download Assets":
            phase = "assets"
        elif raw_status == "Install java runtime":
            phase = "runtime"
        elif raw_status == f"Download {self.version_id}.jar":
            phase = "client"
        elif raw_status == "Installation complete":
            phase = "complete"
        elif self._phase in ("prepare", "metadata") and raw_status.startswith("Download "):
            phase = "metadata"

        with self._lock:
            self._status = _translate_status(raw_status, self.version_id)
            if phase != self._phase:
                self._phase = phase
                self._current = 0
                self._total = 0
                self._percent = max(self._percent, self._phase_span()[0])
            if phase == "complete":
                self._percent = 100.0

    def _on_max(self, maximum: int) -> None:
        with self._lock:
            self._total = max(int(maximum), 0)
            self._current = 0
            self._recalculate_percent_locked()

    def _on_progress(self, current: int) -> None:
        with self._lock:
            self._current = max(int(current), 0)
            self._recalculate_percent_locked()

    def _recalculate_percent_locked(self) -> None:
        start, end = self._phase_span()
        if self._total <= 0:
            return

        fraction = min(max(self._current / self._total, 0.0), 1.0)
        self._percent = max(self._percent, start + (end - start) * fraction)

    def _phase_span(self) -> tuple[float, float]:
        if self._progress_span is not None:
            return self._progress_span
        return _PHASE_SPANS.get(self._phase, (0.0, 0.0))


def _translate_status(raw_status: str, version_id: str) -> str:
    """把 mll 的英文状态文本转成界面可读的中文。"""

    mapping = {
        "Download Libraries": "下载依赖库",
        "Download Assets": "下载资源文件",
        "Install java runtime": "安装 Java 运行环境",
        "Installation complete": "下载完成",
    }
    if raw_status in mapping:
        return mapping[raw_status]

    if raw_status.startswith("Download "):
        filename = raw_status[len("Download ") :]
        if filename == f"{version_id}.jar":
            return "下载客户端 JAR"
        if filename == f"{version_id}.json":
            return "下载版本信息"
        return f"下载 {filename}"

    return raw_status or "准备下载…"


def _parse_datetime(raw_value: object) -> datetime | None:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw_value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _version_sort_key(version: VanillaVersion) -> datetime:
    fallback = datetime.min.replace(tzinfo=timezone.utc)
    release_time = version.release_time or fallback
    if release_time.tzinfo is None:
        release_time = release_time.replace(tzinfo=timezone.utc)
    return release_time.astimezone(timezone.utc)

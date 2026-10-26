"""界面上的小格式化函数，供版本页和下载弹窗共用。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def format_release_date(release_time: datetime | None) -> str:
    """把 UTC 发布时间转成当前系统时区的日期。"""

    if release_time is None:
        return "日期未知"
    return release_time.astimezone().strftime("%Y-%m-%d")


def same_directory(left: str | Path, right: str | Path) -> bool:
    """判断两个目录是否指向同一位置（用于决定下载后是否刷新版本页）。"""

    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return str(left).lower() == str(right).lower()


def format_bytes(num_bytes: int) -> str:
    """把字节数格式化成 B / KB / MB / GB。"""

    value = max(float(num_bytes), 0.0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def format_speed(bytes_per_second: float) -> str:
    """把每秒字节数格式化成速度文本。"""

    return f"{format_bytes(max(int(bytes_per_second), 0))}/s"

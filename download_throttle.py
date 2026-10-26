"""全局下载限速：通过 urllib3 读取包装实现，不修改下载模块代码。"""

from __future__ import annotations

import threading
import time

from urllib3.response import HTTPResponse

_lock = threading.Lock()
_installed = False
_original_read = None
_limit_kbps = 0


def set_download_limit(kbps: int) -> None:
    """设置全局下载限速（KB/s），0 表示不限速。"""

    global _limit_kbps
    _limit_kbps = max(0, int(kbps or 0))
    _ensure_installed()


def get_download_limit() -> int:
    return _limit_kbps


def _ensure_installed() -> None:
    global _installed, _original_read
    if _installed:
        return
    with _lock:
        if _installed:
            return
        _original_read = HTTPResponse.read

        def throttled_read(response, *args, **kwargs):
            data = _original_read(response, *args, **kwargs)
            limit = _limit_kbps
            if limit > 0 and data:
                delay = len(data) / (limit * 1024)
                if delay > 0:
                    time.sleep(delay)
            return data

        HTTPResponse.read = throttled_read
        _installed = True

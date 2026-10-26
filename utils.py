"""旧的日志辅助函数。"""

from __future__ import annotations

import re

LAN_PORT_PATTERN = re.compile(r"Local game hosted on .*?:(\d+)")


def extract_lan_port(log_line: str) -> int | None:
    match = LAN_PORT_PATTERN.search(log_line)
    if match:
        return int(match.group(1))
    return None

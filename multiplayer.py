"""局域网联机辅助：Minecraft LAN 广播识别、端口校验和本地地址。"""

from __future__ import annotations

import re
import socket
import struct
import time

LAN_MULTICAST_GROUP = "224.0.2.60"
LAN_MULTICAST_PORT = 4445


class MultiplayerError(Exception):
    """局域网地址识别或校验失败。"""


def parse_lan_packet(data: bytes) -> int | None:
    """解析 Minecraft 的局域网广播，例如 [MOTD]...[/MOTD][AD]54321[/AD]。"""

    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        return None
    match = re.search(r"\[AD\](\d{1,5})\[/AD\]", text)
    if not match:
        return None
    port = int(match.group(1))
    return port if 1 <= port <= 65535 else None


def discover_lan_port(timeout: float = 25.0) -> int:
    """监听 Minecraft 局域网广播，返回开放端口。

    该函数会阻塞等待，调用方应放到后台线程执行。用户需要在等待期间
    在游戏内执行“对局域网开放”。
    """

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", LAN_MULTICAST_PORT))
        except OSError as exc:
            raise MultiplayerError(
                f"无法监听局域网端口 {LAN_MULTICAST_PORT}：{exc}"
            ) from exc

        membership = struct.pack(
            "4s4s",
            socket.inet_aton(LAN_MULTICAST_GROUP),
            socket.inet_aton("0.0.0.0"),
        )
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        except OSError as exc:
            raise MultiplayerError(f"无法加入 Minecraft 局域网广播组：{exc}") from exc

        sock.settimeout(0.8)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, _address = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                raise MultiplayerError(f"读取局域网广播失败：{exc}") from exc
            port = parse_lan_packet(data)
            if port is not None:
                return port
    finally:
        sock.close()

    raise MultiplayerError(
        "没有检测到 Minecraft 局域网端口。请进入单人存档，按 Esc → "
        "“对局域网开放”，然后立即重试；也可以手动填写游戏聊天栏显示的端口。"
    )


def parse_join_address(text: str) -> tuple[str, int]:
    """解析联机地址，支持 host:port 和 tcp://host:port。"""

    value = (text or "").strip()
    if not value:
        raise MultiplayerError("请输入对方提供的联机地址")
    if value.lower().startswith("tcp://"):
        value = value[6:]
    if "://" in value:
        raise MultiplayerError("联机地址格式应为 host:port")
    if "/" in value or " " in value:
        raise MultiplayerError("联机地址不能包含空格或路径")
    if ":" not in value:
        raise MultiplayerError("联机地址缺少端口，格式应为 host:port")

    host, port_text = value.rsplit(":", 1)
    host = host.strip()
    if not host:
        raise MultiplayerError("联机地址缺少主机名")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise MultiplayerError("联机端口不是有效数字") from exc
    if not 1 <= port <= 65535:
        raise MultiplayerError("联机端口必须在 1-65535 之间")
    return host, port


def is_tcp_port_open(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 1.5,
) -> bool:
    """确认本地局域网端口是否有程序监听。"""

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def get_local_ipv4() -> str | None:
    """获取本机局域网 IPv4，用于展示 192.168.x.x:port。"""

    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and ip != "0.0.0.0":
                candidates.append(ip)
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and ip not in candidates:
                candidates.append(ip)
    except OSError:
        pass

    for ip in candidates:
        if ip.startswith(("10.", "192.168.", "172.")):
            return ip
    return candidates[0] if candidates else None


def format_lan_address(host: str | None, port: int) -> str:
    return f"{host or '127.0.0.1'}:{port}"

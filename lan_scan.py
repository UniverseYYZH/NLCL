"""局域网房间扫描：UDP 广播 + Minecraft Server List Ping + 收藏 + 二维码。"""

from __future__ import annotations

import base64
import io
import json
import os
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path

LAN_GROUP = "224.0.2.60"
LAN_PORT = 4445


class LanScanError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LanRoom:
    address: str
    port: int
    motd: str = "Minecraft 房间"
    version: str = "未知"
    players_online: int | None = None
    players_max: int | None = None
    source: str = ""
    last_seen: float = 0.0

    @property
    def endpoint(self) -> str:
        return f"{self.address}:{self.port}"

    @property
    def players_text(self) -> str:
        if self.players_online is None:
            return "玩家未知"
        return f"{self.players_online}/{self.players_max or '?'} 玩家"


def default_favorites_file() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "NLCL" / "lan_favorites.json"


class LanFavorites:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_favorites_file()
        self.items: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception:
            self.items = {}
            return
        self.items = (
            {str(k): v for k, v in data.items() if isinstance(v, dict)}
            if isinstance(data, dict)
            else {}
        )

    def contains(self, endpoint: str) -> bool:
        return endpoint in self.items

    def toggle(self, room: LanRoom) -> bool:
        if room.endpoint in self.items:
            self.items.pop(room.endpoint, None)
            added = False
        else:
            self.items[room.endpoint] = {
                "address": room.address,
                "port": room.port,
                "motd": room.motd,
                "version": room.version,
                "players_online": room.players_online,
                "players_max": room.players_max,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            added = True
        self._save()
        return added

    def rooms(self) -> list[LanRoom]:
        rooms = []
        for endpoint, item in self.items.items():
            try:
                port = int(item.get("port"))
            except (TypeError, ValueError):
                continue
            rooms.append(
                LanRoom(
                    address=str(item.get("address") or endpoint.rsplit(":", 1)[0]),
                    port=port,
                    motd=str(item.get("motd") or "收藏房间"),
                    version=str(item.get("version") or "未知"),
                    players_online=_optional_int(item.get("players_online")),
                    players_max=_optional_int(item.get("players_max")),
                )
            )
        rooms.sort(key=lambda item: item.motd)
        return rooms

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self.items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        import shutil

        shutil.copyfile(temp, self.path)
        temp.unlink(missing_ok=True)


def scan_lan_rooms(
    duration: float = 8.0,
    *,
    ping_timeout: float = 1.5,
) -> list[LanRoom]:
    """监听局域网广播，并 ping 每个端点获取版本/玩家信息。"""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    rooms: dict[str, LanRoom] = {}
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", LAN_PORT))
        except OSError as exc:
            raise LanScanError(f"无法监听局域网端口 {LAN_PORT}：{exc}") from exc
        membership = struct.pack(
            "4s4s",
            socket.inet_aton(LAN_GROUP),
            socket.inet_aton("0.0.0.0"),
        )
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        except OSError as exc:
            raise LanScanError(f"无法加入 Minecraft 广播组：{exc}") from exc
        sock.settimeout(0.5)
        deadline = time.monotonic() + max(duration, 1.0)
        while time.monotonic() < deadline:
            try:
                data, source = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                raise LanScanError(f"读取广播失败：{exc}") from exc
            parsed = _parse_broadcast(data)
            if parsed is None:
                continue
            port, motd = parsed
            host = source[0]
            endpoint = f"{host}:{port}"
            if endpoint in rooms:
                continue
            info = ping_server(host, port, timeout=ping_timeout)
            rooms[endpoint] = LanRoom(
                address=host,
                port=port,
                motd=info.get("motd") or motd or "Minecraft 房间",
                version=info.get("version") or "未知",
                players_online=info.get("players_online"),
                players_max=info.get("players_max"),
                source=host,
                last_seen=time.time(),
            )
    finally:
        sock.close()
    return sorted(rooms.values(), key=lambda room: room.motd.lower())


def _parse_broadcast(data: bytes) -> tuple[int, str] | None:
    text = data.decode("utf-8", errors="ignore")
    start = text.find("[AD]")
    end = text.find("[/AD]", start + 4)
    if start < 0 or end < 0:
        return None
    try:
        port = int(text[start + 4 : end])
    except ValueError:
        return None
    motd = ""
    motd_start = text.find("[MOTD]")
    motd_end = text.find("[/MOTD]", motd_start + 6)
    if motd_start >= 0 and motd_end >= 0:
        motd = text[motd_start + 6 : motd_end].strip()
    return (port, motd) if 1 <= port <= 65535 else None


def ping_server(host: str, port: int, timeout: float = 1.5) -> dict:
    """Minecraft Server List Ping，读取 MOTD/版本/在线人数。"""

    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            host_bytes = host.encode("utf-8")
            handshake = (
                _varint(0)
                + _varint(767)
                + _varint(len(host_bytes))
                + host_bytes
                + struct.pack(">H", port)
                + _varint(1)
            )
            sock.sendall(_varint(len(handshake)) + handshake)
            sock.sendall(_varint(1) + _varint(0))
            length = _read_varint_sock(sock)
            if length <= 0:
                return {}
            payload = _recv_exact(sock, length)
            if not payload:
                return {}
            # packet id + JSON string
            offset = 1 if payload[0] == 0 else 0
            text_length = _read_varint_bytes(payload, offset)
            if text_length is None:
                return {}
            json_start = offset + text_length[1]
            raw = payload[json_start : json_start + text_length[0]]
            data = json.loads(raw.decode("utf-8", errors="replace"))
            motd_data = data.get("description", "")
            if isinstance(motd_data, dict):
                motd = str(motd_data.get("text") or "")
                if not motd and isinstance(motd_data.get("extra"), list):
                    motd = "".join(
                        str(part.get("text", ""))
                        for part in motd_data["extra"]
                        if isinstance(part, dict)
                    )
            else:
                motd = str(motd_data or "")
            version = ""
            if isinstance(data.get("version"), dict):
                version = str(data["version"].get("name") or "")
            players = data.get("players") if isinstance(data.get("players"), dict) else {}
            return {
                "motd": motd.strip(),
                "version": version,
                "players_online": _optional_int(players.get("online")),
                "players_max": _optional_int(players.get("max")),
            }
    except Exception:
        return {}


def qr_png_base64(text: str, scale: int = 4) -> str:
    import segno

    qr = segno.make(text, error="m")
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=scale, border=2)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _varint(value: int) -> bytes:
    value &= 0xFFFFFFFF
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _read_varint_sock(sock: socket.socket) -> int:
    value = 0
    for index in range(5):
        raw = sock.recv(1)
        if not raw:
            return -1
        byte = raw[0]
        value |= (byte & 0x7F) << (7 * index)
        if not (byte & 0x80):
            return value
    return -1


def _read_varint_bytes(data: bytes, offset: int = 0) -> tuple[int, int] | None:
    value = 0
    for index in range(5):
        if offset + index >= len(data):
            return None
        byte = data[offset + index]
        value |= (byte & 0x7F) << (7 * index)
        if not (byte & 0x80):
            return value, index + 1
    return None


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        data = sock.recv(length - len(chunks))
        if not data:
            break
        chunks.extend(data)
    return bytes(chunks)


def _optional_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

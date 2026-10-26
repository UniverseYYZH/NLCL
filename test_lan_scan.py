"""局域网扫描辅助测试。"""

from __future__ import annotations

import base64
import json
import shutil
import socket
import threading
import time
import unittest
from pathlib import Path
from uuid import uuid4

from lan_scan import (
    LanFavorites,
    LanRoom,
    _parse_broadcast,
    _varint,
    ping_server,
    qr_png_base64,
)


class LanScanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".tmp" / f"lan-{uuid4().hex}"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_parse_broadcast(self) -> None:
        port, motd = _parse_broadcast(
            b"[MOTD]Tester - 1.20.1[/MOTD][AD]54321[/AD]"
        )
        self.assertEqual(port, 54321)
        self.assertEqual(motd, "Tester - 1.20.1")
        self.assertIsNone(_parse_broadcast(b"not a packet"))

    def test_favorites_persist(self) -> None:
        path = self.root / "favorites.json"
        room = LanRoom("192.168.1.20", 54321, "Room", "1.20.1", 2, 8)
        store = LanFavorites(path)
        self.assertTrue(store.toggle(room))
        self.assertTrue(store.contains(room.endpoint))
        reopened = LanFavorites(path)
        self.assertTrue(reopened.contains(room.endpoint))
        self.assertEqual(reopened.rooms()[0].motd, "Room")
        self.assertFalse(reopened.toggle(room))
        self.assertFalse(reopened.contains(room.endpoint))

    def test_qr_png(self) -> None:
        raw = base64.b64decode(qr_png_base64("192.168.1.20:54321"))
        self.assertTrue(raw.startswith(b"\x89PNG"))

    def test_ping_server(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        payload = {
            "description": {"text": "Test Room"},
            "version": {"name": "1.20.1"},
            "players": {"online": 3, "max": 10},
        }

        def serve():
            connection, _ = server.accept()
            try:
                connection.settimeout(2)
                connection.recv(4096)
                encoded = json.dumps(payload).encode("utf-8")
                body = b"\x00" + _varint(len(encoded)) + encoded
                connection.sendall(_varint(len(body)) + body)
                time.sleep(0.1)
            finally:
                connection.close()
                server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        info = ping_server("127.0.0.1", port, timeout=2)
        thread.join(timeout=3)
        self.assertEqual(info["motd"], "Test Room")
        self.assertEqual(info["version"], "1.20.1")
        self.assertEqual(info["players_online"], 3)
        self.assertEqual(info["players_max"], 10)


if __name__ == "__main__":
    unittest.main()

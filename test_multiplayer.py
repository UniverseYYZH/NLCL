"""局域网联机辅助函数测试。"""

from __future__ import annotations

import socket
import threading
import time
import unittest

from game_launcher import with_server_address
from multiplayer import (
    MultiplayerError,
    format_lan_address,
    is_tcp_port_open,
    parse_join_address,
    parse_lan_packet,
)


class MultiplayerTest(unittest.TestCase):
    def test_parse_lan_packet(self) -> None:
        packet = b"[MOTD]Tester - 1.20.1[/MOTD][AD]54321[/AD]"
        self.assertEqual(parse_lan_packet(packet), 54321)
        self.assertIsNone(parse_lan_packet(b"no port"))
        self.assertIsNone(parse_lan_packet(b"[AD]99999[/AD]"))

    def test_parse_join_address(self) -> None:
        self.assertEqual(
            parse_join_address("192.168.1.20:54321"),
            ("192.168.1.20", 54321),
        )
        self.assertEqual(
            parse_join_address("tcp://192.168.1.20:54321"),
            ("192.168.1.20", 54321),
        )
        with self.assertRaises(MultiplayerError):
            parse_join_address("192.168.1.20")
        with self.assertRaises(MultiplayerError):
            parse_join_address("192.168.1.20:0")
        with self.assertRaises(MultiplayerError):
            parse_join_address("http://192.168.1.20:54321")

    def test_with_server_address(self) -> None:
        command = ["java", "-cp", "client.jar", "net.minecraft.client.main.Main"]
        self.assertEqual(
            with_server_address(command, "192.168.1.20", 54321),
            [
                "java",
                "-cp",
                "client.jar",
                "net.minecraft.client.main.Main",
                "--server",
                "192.168.1.20",
                "--port",
                "54321",
            ],
        )

    def test_port_probe(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            self.assertTrue(is_tcp_port_open(port))
        finally:
            server.close()

    def test_format_lan_address(self) -> None:
        self.assertEqual(format_lan_address("192.168.1.20", 54321), "192.168.1.20:54321")
        self.assertEqual(format_lan_address(None, 54321), "127.0.0.1:54321")


if __name__ == "__main__":
    unittest.main()

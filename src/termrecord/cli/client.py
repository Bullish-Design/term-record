"""Watcher client for CLI."""

from __future__ import annotations

import json
import socket
from pathlib import Path


class WatcherClient:
    """Client for communicating with watcher service."""

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path.expanduser()

    def send(self, message: dict) -> dict:
        """Send message to watcher and get response."""
        if not self.socket_path.exists():
            raise ConnectionError(f"Socket not found: {self.socket_path}")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(self.socket_path))
            sock.sendall(json.dumps(message).encode() + b"\n")

            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\n" in response:
                    break

            return json.loads(response.decode().strip())
        finally:
            sock.close()

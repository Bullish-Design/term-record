"""Unix socket server for status queries."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from termrecord.watcher.exporter import ExportQueue
from termrecord.watcher.indexer import Indexer


class StatusServer:
    """Unix socket server for CLI communication."""

    def __init__(
        self, socket_path: Path, indexer: Indexer, exporter: ExportQueue
    ):
        self.socket_path = socket_path.expanduser()
        self.indexer = indexer
        self.exporter = exporter
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start the server."""
        # Remove stale socket
        if self.socket_path.exists():
            self.socket_path.unlink()

        # Ensure parent directory exists
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_client, str(self.socket_path)
        )

    async def stop(self) -> None:
        """Stop the server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        if self.socket_path.exists():
            self.socket_path.unlink()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a client connection."""
        try:
            data = await reader.readline()
            message = json.loads(data.decode().strip())

            response = await self._process_message(message)

            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
        except Exception as e:
            error_response = {"error": str(e)}
            writer.write(json.dumps(error_response).encode() + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _process_message(self, message: dict) -> dict:
        """Process a client message."""
        action = message.get("action")

        if action == "status":
            stats = await self.indexer.get_stats()
            return {"status": "running", "stats": stats}

        elif action == "list":
            recordings = []
            async for rec in self.indexer.list_recordings(
                limit=message.get("limit", 50),
                offset=message.get("offset", 0),
                failed_only=message.get("failed_only", False),
                cwd=message.get("cwd"),
            ):
                recordings.append(rec.model_dump())
            return {"recordings": recordings}

        elif action == "get":
            recording_id = message.get("id")
            # Try as recording ID first
            rec = await self.indexer.get_by_id(recording_id)
            # Try as atuin ID if not found
            if not rec:
                rec = await self.indexer.get_by_atuin_id(recording_id)

            if rec:
                return {"recording": rec.model_dump()}
            else:
                return {"recording": None}

        elif action == "cleanup":
            from termrecord.watcher.cleanup import CleanupScheduler

            cleanup = CleanupScheduler(self.exporter.config, self.indexer)
            result = await cleanup.run_cleanup(dry_run=message.get("dry_run", False))
            return result

        else:
            return {"error": f"Unknown action: {action}"}

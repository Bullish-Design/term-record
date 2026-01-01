"""Main watcher service."""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from termrecord.config import load_config
from termrecord.watcher.cleanup import CleanupScheduler
from termrecord.watcher.exporter import ExportQueue
from termrecord.watcher.file_watcher import FileWatcher
from termrecord.watcher.indexer import Indexer
from termrecord.watcher.server import StatusServer


class WatcherService:
    """Main watcher service orchestrator."""

    def __init__(self, config_path: Path | None = None):
        self.config = load_config(config_path)
        self.storage_dir = self.config.recording.storage_dir.expanduser()
        self.recordings_dir = self.storage_dir / "recordings"

        # Set up logging
        log_file = self.config.watcher.log_file.expanduser()
        log_file.parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=getattr(logging, self.config.watcher.log_level.upper()),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger("termrecord.watcher")

        # Initialize components
        self.indexer = Indexer(self.storage_dir / "index.db")
        self.exporter = ExportQueue(self.config, self.indexer)
        self.cleanup = CleanupScheduler(self.config, self.indexer)
        self.file_watcher = FileWatcher(
            self.recordings_dir, on_new_recording=self._handle_new_recording
        )
        self.server = StatusServer(
            self.config.watcher.socket_path, indexer=self.indexer, exporter=self.exporter
        )

    async def _handle_new_recording(self, meta_path: Path) -> None:
        """Handle a new .meta.json file."""
        try:
            self.logger.info(f"Indexing new recording: {meta_path}")
            await self.indexer.index_recording(meta_path)

            if self.config.export.gif_enabled:
                recording_id = meta_path.stem.replace(".meta", "")
                await self.exporter.enqueue(recording_id, "gif")
        except Exception as e:
            self.logger.error(f"Failed to handle recording {meta_path}: {e}")

    async def start(self) -> None:
        """Start the watcher service."""
        self.logger.info("Starting termrecord watcher service")

        # Ensure directories exist
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        await self.indexer.initialize()
        await self.file_watcher.start()
        await self.exporter.start()
        await self.cleanup.start()
        await self.server.start()

        self.logger.info("Watcher service started")

    async def stop(self) -> None:
        """Stop the watcher service."""
        self.logger.info("Stopping termrecord watcher service")

        await self.server.stop()
        await self.cleanup.stop()
        await self.exporter.stop()
        await self.file_watcher.stop()
        await self.indexer.close()

        self.logger.info("Watcher service stopped")

    async def run(self) -> None:
        """Run the watcher service until interrupted."""
        await self.start()

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        # Wait for stop signal
        await stop_event.wait()

        await self.stop()


def main() -> None:
    """Main entry point."""
    asyncio.run(WatcherService().run())


if __name__ == "__main__":
    main()

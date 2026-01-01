"""File watcher for new recordings."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

from watchfiles import Change, awatch


class FileWatcher:
    """Watches for new .meta.json files."""

    def __init__(
        self, watch_dir: Path, on_new_recording: Callable[[Path], Awaitable[None]]
    ):
        self.watch_dir = watch_dir
        self.on_new_recording = on_new_recording
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start watching."""
        self._task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        """Stop watching."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watch_loop(self) -> None:
        """Main watch loop."""
        async for changes in awatch(self.watch_dir, stop_event=self._stop_event):
            for change_type, path_str in changes:
                path = Path(path_str)
                if change_type == Change.added and path.suffix == ".json" and ".meta" in path.name:
                    try:
                        await self.on_new_recording(path)
                    except Exception:
                        # Log error but continue watching
                        pass

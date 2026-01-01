"""Retention cleanup scheduler."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from termrecord.models.config import Config
from termrecord.watcher.indexer import Indexer


class CleanupScheduler:
    """Handles retention cleanup."""

    def __init__(self, config: Config, indexer: Indexer):
        self.config = config
        self.indexer = indexer
        self.storage_dir = config.recording.storage_dir.expanduser()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start cleanup scheduler."""
        self._task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop cleanup scheduler."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self) -> None:
        """Main cleanup loop."""
        while not self._stop_event.is_set():
            try:
                await self.run_cleanup()
                # Sleep for cleanup interval
                interval_seconds = self.config.retention.cleanup_interval_hours * 3600
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(3600)  # Retry in an hour on error

    async def run_cleanup(self, dry_run: bool = False) -> dict:
        """Run cleanup now."""
        deleted_count = 0
        freed_bytes = 0

        # 1. Delete by age
        max_age_seconds = self.config.retention.max_age_days * 86400
        cutoff = time.time() - max_age_seconds

        async with self.indexer._db.execute(
            "SELECT id, meta_path FROM recordings WHERE timestamp < ?", (cutoff,)
        ) as cursor:
            async for row in cursor:
                recording_id, meta_path = row
                if not dry_run:
                    freed = await self._delete_recording_files(recording_id, meta_path)
                    freed_bytes += freed
                deleted_count += 1

        # 2. Delete by count (keep newest)
        max_count = self.config.retention.max_count
        async with self.indexer._db.execute(
            """
            SELECT id, meta_path FROM recordings
            ORDER BY timestamp DESC
            LIMIT -1 OFFSET ?
        """,
            (max_count,),
        ) as cursor:
            async for row in cursor:
                recording_id, meta_path = row
                if not dry_run:
                    freed = await self._delete_recording_files(recording_id, meta_path)
                    freed_bytes += freed
                deleted_count += 1

        # 3. Delete by size (oldest first until under limit)
        max_bytes = self.config.retention.max_size_gb * 1024 * 1024 * 1024
        current_size = await self._calculate_storage_size()

        if current_size > max_bytes:
            async with self.indexer._db.execute(
                "SELECT id, meta_path FROM recordings ORDER BY timestamp ASC"
            ) as cursor:
                async for row in cursor:
                    if current_size <= max_bytes:
                        break
                    recording_id, meta_path = row
                    if not dry_run:
                        freed = await self._delete_recording_files(
                            recording_id, meta_path
                        )
                        freed_bytes += freed
                        current_size -= freed
                    deleted_count += 1

        return {"deleted_count": deleted_count, "freed_bytes": freed_bytes}

    async def _delete_recording_files(
        self, recording_id: str, meta_path: str
    ) -> int:
        """Delete recording files and index entry."""
        freed = 0
        meta = Path(meta_path)

        if meta.exists():
            freed += meta.stat().st_size
            meta.unlink()

        # Delete associated files
        for suffix in [".cast", ".gif", ".png"]:
            associated = meta.with_suffix(suffix)
            if associated.exists():
                freed += associated.stat().st_size
                associated.unlink()

        await self.indexer.delete_recording(recording_id)
        return freed

    async def _calculate_storage_size(self) -> int:
        """Calculate total storage size."""
        recordings_dir = self.storage_dir / "recordings"
        total = 0
        for path in recordings_dir.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        return total

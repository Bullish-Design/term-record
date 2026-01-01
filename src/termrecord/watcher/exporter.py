"""Export queue processor."""

from __future__ import annotations

import asyncio
from pathlib import Path

from termrecord.models.config import Config
from termrecord.watcher.indexer import Indexer


class ExportQueue:
    """Processes export queue for GIF generation."""

    def __init__(self, config: Config, indexer: Indexer):
        self.config = config
        self.indexer = indexer
        self.storage_dir = config.recording.storage_dir.expanduser()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start processing queue."""
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        """Stop processing queue."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, recording_id: str, export_type: str) -> None:
        """Add export job to queue."""
        await self.indexer._db.execute(
            """
            INSERT INTO export_queue (recording_id, export_type, status)
            VALUES (?, ?, 'pending')
        """,
            (recording_id, export_type),
        )
        await self.indexer._db.commit()

    async def _process_loop(self) -> None:
        """Main processing loop."""
        while not self._stop_event.is_set():
            try:
                await self._process_next()
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

    async def _process_next(self) -> None:
        """Process next item in queue."""
        async with self.indexer._db.execute(
            """
            SELECT eq.id, eq.recording_id, eq.export_type, r.cast_path
            FROM export_queue eq
            JOIN recordings r ON eq.recording_id = r.id
            WHERE eq.status = 'pending'
            ORDER BY eq.created_at
            LIMIT 1
        """
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return

        queue_id, recording_id, export_type, cast_path = row

        await self.indexer._db.execute(
            "UPDATE export_queue SET status = 'processing' WHERE id = ?", (queue_id,)
        )
        await self.indexer._db.commit()

        try:
            if export_type == "gif":
                await self._generate_gif(recording_id, cast_path)

            await self.indexer._db.execute(
                """
                UPDATE export_queue
                SET status = 'done', completed_at = strftime('%s', 'now')
                WHERE id = ?
            """,
                (queue_id,),
            )
        except Exception as e:
            await self.indexer._db.execute(
                """
                UPDATE export_queue
                SET status = 'failed', error = ?
                WHERE id = ?
            """,
                (str(e), queue_id),
            )

        await self.indexer._db.commit()

    async def _generate_gif(self, recording_id: str, cast_path: str) -> None:
        """Generate GIF from cast file."""
        full_cast_path = self.storage_dir / "recordings" / cast_path
        gif_path = full_cast_path.with_suffix(".gif")

        # Use agg (asciinema gif generator)
        proc = await asyncio.create_subprocess_exec(
            "agg",
            str(full_cast_path),
            str(gif_path),
            "--speed",
            str(self.config.export.gif_speed),
            "--idle-time-limit",
            str(self.config.export.gif_max_idle),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"agg failed: {stderr.decode()}")

        # Update recording with gif path
        relative_gif = str(gif_path.relative_to(self.storage_dir / "recordings"))
        await self.indexer._db.execute(
            "UPDATE recordings SET gif_path = ? WHERE id = ?", (relative_gif, recording_id)
        )
        await self.indexer._db.commit()

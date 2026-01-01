"""SQLite indexer for recordings."""

from __future__ import annotations

import aiosqlite
from pathlib import Path
from typing import AsyncIterator

from termrecord.models.index import IndexedRecording
from termrecord.models.metadata import RecordingMetadata


class Indexer:
    """SQLite indexer."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize database connection and schema."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._create_schema()

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()

    async def _create_schema(self) -> None:
        """Create database schema."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,
                atuin_id TEXT UNIQUE,
                command TEXT NOT NULL,
                timestamp REAL NOT NULL,
                duration REAL,
                exit_code INTEGER,
                cwd TEXT NOT NULL,
                shell TEXT,
                user TEXT,
                hostname TEXT,
                cast_path TEXT,
                gif_path TEXT,
                screenshot_path TEXT,
                meta_path TEXT NOT NULL,
                indexed_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_atuin_id ON recordings(atuin_id);
            CREATE INDEX IF NOT EXISTS idx_timestamp ON recordings(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_exit_code ON recordings(exit_code);
            CREATE INDEX IF NOT EXISTS idx_cwd ON recordings(cwd);

            CREATE TABLE IF NOT EXISTS export_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id TEXT NOT NULL,
                export_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                completed_at INTEGER,
                error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_queue_status ON export_queue(status);

            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );
        """)
        await self._db.commit()

    async def index_recording(self, meta_path: Path) -> None:
        """Index a recording from its metadata file."""
        content = meta_path.read_text()
        meta = RecordingMetadata.model_validate_json(content)

        await self._db.execute(
            """
            INSERT OR REPLACE INTO recordings (
                id, atuin_id, command, timestamp, duration, exit_code,
                cwd, shell, user, hostname, cast_path, gif_path,
                screenshot_path, meta_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                meta.id,
                meta.atuin_id,
                meta.command,
                meta.timestamp,
                meta.duration,
                meta.exit_code,
                meta.cwd,
                meta.shell,
                meta.user,
                meta.hostname,
                meta.files.cast,
                meta.files.gif,
                meta.files.screenshot,
                str(meta_path),
            ),
        )
        await self._db.commit()

    async def get_by_atuin_id(self, atuin_id: str) -> IndexedRecording | None:
        """Get recording by atuin ID."""
        async with self._db.execute(
            "SELECT * FROM recordings WHERE atuin_id = ?", (atuin_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return IndexedRecording.from_row(dict(row))
            return None

    async def get_by_id(self, recording_id: str) -> IndexedRecording | None:
        """Get recording by ID."""
        async with self._db.execute(
            "SELECT * FROM recordings WHERE id = ?", (recording_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return IndexedRecording.from_row(dict(row))
            return None

    async def list_recordings(
        self,
        limit: int = 50,
        offset: int = 0,
        failed_only: bool = False,
        cwd: str | None = None,
    ) -> AsyncIterator[IndexedRecording]:
        """List recordings with filters."""
        query = "SELECT * FROM recordings WHERE 1=1"
        params = []

        if failed_only:
            query += " AND exit_code != 0"
        if cwd:
            query += " AND cwd LIKE ?"
            params.append(f"{cwd}%")

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with self._db.execute(query, params) as cursor:
            async for row in cursor:
                yield IndexedRecording.from_row(dict(row))

    async def get_stats(self) -> dict:
        """Get recording statistics."""
        stats = {}

        async with self._db.execute("SELECT COUNT(*) FROM recordings") as cursor:
            stats["total_count"] = (await cursor.fetchone())[0]

        async with self._db.execute(
            "SELECT COUNT(*) FROM recordings WHERE exit_code != 0"
        ) as cursor:
            stats["failed_count"] = (await cursor.fetchone())[0]

        return stats

    async def delete_recording(self, recording_id: str) -> bool:
        """Delete a recording from index."""
        result = await self._db.execute(
            "DELETE FROM recordings WHERE id = ?", (recording_id,)
        )
        await self._db.commit()
        return result.rowcount > 0

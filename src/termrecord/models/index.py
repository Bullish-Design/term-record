"""Database index models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class IndexedRecording(BaseModel):
    """Indexed recording from database."""

    id: str
    atuin_id: str | None
    command: str
    timestamp: float
    duration: float | None
    exit_code: int | None
    cwd: str
    shell: str | None
    user: str | None
    hostname: str | None
    cast_path: str | None
    gif_path: str | None
    screenshot_path: str | None
    meta_path: str
    indexed_at: int

    @classmethod
    def from_row(cls, row: Any) -> IndexedRecording:
        """Create from database row."""
        # Handle both dict and tuple rows
        if isinstance(row, dict):
            return cls(**row)

        # Assume tuple from sqlite3.Row or similar
        return cls(
            id=row[0],
            atuin_id=row[1],
            command=row[2],
            timestamp=row[3],
            duration=row[4],
            exit_code=row[5],
            cwd=row[6],
            shell=row[7],
            user=row[8],
            hostname=row[9],
            cast_path=row[10],
            gif_path=row[11],
            screenshot_path=row[12],
            meta_path=row[13],
            indexed_at=row[14],
        )

"""Recording metadata models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TerminalInfo(BaseModel):
    """Terminal information."""

    width: int
    height: int
    term: str


class RecordingFiles(BaseModel):
    """Recording file paths."""

    cast: str | None = None
    gif: str | None = None
    screenshot: str | None = None


class RecordingMetadata(BaseModel):
    """Recording metadata."""

    id: str
    atuin_id: str | None = None
    command: str
    timestamp: float
    duration: float | None = None
    exit_code: int | None = None
    cwd: str
    shell: str
    user: str
    hostname: str
    terminal: TerminalInfo
    files: RecordingFiles = Field(default_factory=RecordingFiles)

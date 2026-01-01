"""Configuration models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class PathRule(BaseModel):
    """Path-based recording rule."""

    path: str
    enabled: bool = True
    format: Literal["cast", "gif", "both"] | None = None


class RecordingConfig(BaseModel):
    """Recording configuration."""

    enabled: bool = True
    storage_dir: Path = Path("~/.local/share/termrecord")
    format: Literal["cast", "gif", "both"] = "cast"
    rules: list[PathRule] = Field(default_factory=list)


class RetentionConfig(BaseModel):
    """Retention policy configuration."""

    max_age_days: int = 30
    max_size_gb: float = 10.0
    max_count: int = 10000
    cleanup_interval_hours: int = 24


class ExportConfig(BaseModel):
    """Export configuration."""

    gif_enabled: bool = False
    gif_speed: float = 1.0
    gif_max_idle: float = 2.0
    screenshot_on_error: bool = True


class TerminalConfig(BaseModel):
    """Terminal configuration."""

    width: int = 120
    height: int = 40


class WatcherConfig(BaseModel):
    """Watcher service configuration."""

    socket_path: Path = Path("~/.local/share/termrecord/watcher.sock")
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_file: Path = Path("~/.local/share/termrecord/watcher.log")


class Config(BaseModel):
    """Main configuration."""

    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    terminal: TerminalConfig = Field(default_factory=TerminalConfig)
    watcher: WatcherConfig = Field(default_factory=WatcherConfig)

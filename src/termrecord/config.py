"""Configuration loading and path checking."""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from termrecord.models.config import Config


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from file."""
    if config_path is None:
        config_path = Path("~/.config/termrecord/config.toml").expanduser()
    else:
        config_path = Path(config_path).expanduser()

    if not config_path.exists():
        return Config()

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    return Config.model_validate(data)


def find_dotfile(start_dir: Path) -> Path | None:
    """Find .termrecord.toml walking up from start_dir."""
    current = start_dir.resolve()

    while True:
        dotfile = current / ".termrecord.toml"
        if dotfile.exists():
            return dotfile

        parent = current.parent
        if parent == current:  # Reached root
            break
        current = parent

    return None


def is_recording_enabled_dotfile(dotfile_path: Path) -> bool:
    """Check if recording is enabled in dotfile."""
    with open(dotfile_path, "rb") as f:
        data = tomllib.load(f)

    return data.get("enabled", True)


def is_recording_enabled_rules(config: Config, directory: Path) -> bool | None:
    """Check path rules. Returns None if no rule matches."""
    dir_str = str(directory.expanduser().resolve())

    for rule in config.recording.rules:
        pattern = str(Path(rule.path).expanduser())

        # Handle glob patterns
        if fnmatch.fnmatch(dir_str, pattern):
            return rule.enabled

    return None


def is_recording_enabled(config: Config, directory: Path) -> bool:
    """Check if recording is enabled for directory."""
    directory = Path(directory).expanduser().resolve()

    # 1. Check for dotfile
    dotfile = find_dotfile(directory)
    if dotfile:
        return is_recording_enabled_dotfile(dotfile)

    # 2. Check path rules
    rule_result = is_recording_enabled_rules(config, directory)
    if rule_result is not None:
        return rule_result

    # 3. Global default
    return config.recording.enabled


def check_path_cli() -> None:
    """CLI entry point for checking path (used by hooks)."""
    if len(sys.argv) < 2:
        sys.exit(1)

    directory = Path(sys.argv[1])
    config = load_config()

    if is_recording_enabled(config, directory):
        sys.exit(0)
    else:
        sys.exit(1)

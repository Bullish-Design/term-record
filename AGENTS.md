# AGENTS.md - Claude Code Implementation Guide

## Project Overview

RecordTerm is a NixOS flake that provides automatic terminal recording linked to atuin shell history. This guide provides implementation instructions for Claude Code.

## Critical Design Decisions

### What This Is NOT

The original design tried to run commands in a daemon-managed tmux session and record that. **This doesn't work** because it records a replay, not the actual terminal.

### What This IS

Shell hooks wrap command execution with `script` or `asciinema rec`, producing `.cast` files. A background watcher indexes recordings and processes exports. This records what actually happens.

## File Structure

```
recordterm/
├── flake.nix
├── flake.lock
├── pyproject.toml
├── README.md
│
├── modules/
│   └── home-manager.nix             # Primary user module (zsh only)
│
├── src/
│   └── recordterm/
│       ├── __init__.py
│       ├── config.py                # Config loading, path checking
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   ├── config.py            # Pydantic config models
│       │   ├── metadata.py          # Recording metadata models
│       │   └── index.py             # Index row models
│       │
│       ├── watcher/
│       │   ├── __init__.py
│       │   ├── main.py              # Watcher entry point
│       │   ├── file_watcher.py      # inotify watcher
│       │   ├── indexer.py           # SQLite operations
│       │   ├── exporter.py          # GIF export queue
│       │   ├── cleanup.py           # Retention scheduler
│       │   └── server.py            # Status socket server
│       │
│       └── cli/
│           ├── __init__.py
│           ├── main.py              # Click CLI
│           └── client.py            # Socket client
│
└── scripts/
    └── hooks.zsh                    # Zsh integration (only shell supported)
```

## Implementation Order

### Phase 1: Core Models

Start with Pydantic models. These define the data contracts.

#### 1.1 `src/recordterm/models/config.py`

```python
# src/recordterm/models/config.py
```

Key types:
- `PathRule`: path pattern + enabled flag
- `RecordingConfig`: global settings + rules list
- `RetentionConfig`: age/size/count limits
- `ExportConfig`: GIF settings
- `Config`: root config combining all sections

All paths should be `Path` type with `expanduser()` called at usage time, not in the model.

#### 1.2 `src/recordterm/models/metadata.py`

```python
# src/recordterm/models/metadata.py
```

Key types:
- `TerminalInfo`: width, height, term
- `RecordingFiles`: cast, gif, screenshot paths (all optional str)
- `RecordingMetadata`: full recording metadata

#### 1.3 `src/recordterm/models/index.py`

```python
# src/recordterm/models/index.py
```

Key types:
- `IndexedRecording`: row from SQLite, with `from_row()` classmethod

### Phase 2: Configuration

#### 2.1 `src/recordterm/config.py`

Functions:
- `load_config(path: Path | None) -> Config`: Load TOML, return Config
- `find_config() -> Path | None`: Look in standard locations
- `is_recording_enabled(config: Config, directory: Path) -> bool`: Check dotfiles + rules
- `check_path_cli()`: Entry point for `recordterm-check-path` command

Path checking logic:
1. Walk from `directory` toward `/` looking for `.recordterm.toml`
2. If found with `enabled = false`, return False
3. If found with `enabled = true` (or no enabled key), return True
4. Check config.recording.rules in order, return first match
5. Return config.recording.enabled as default

### Phase 3: Shell Hooks (zsh only)

#### 3.1 `scripts/hooks.zsh`

Uses ZLE widget to intercept command execution:

```zsh
# Key mechanism: override accept-line widget
_recordterm_accept_line() {
    if [[ -n "$BUFFER" ]] && _recordterm_should_record; then
        # Check for builtins that can't be wrapped
        case "${${(z)BUFFER}[1]}" in
            cd|pushd|popd|export|unset|source|.|eval|exec|...)
                # Skip wrapping - record metadata only
                _recordterm_setup_recording "$BUFFER"
                _RECORDTERM_SKIP_WRAP=1
                ;;
            *)
                # Wrap with asciinema rec
                if _recordterm_setup_recording "$BUFFER"; then
                    BUFFER="asciinema rec --quiet --overwrite -c ${(q)BUFFER} ${(q)_RECORDTERM_CAST_FILE}"
                fi
                ;;
        esac
    fi
    zle .accept-line
}
zle -N accept-line _recordterm_accept_line
```

Critical requirements:
- **Fast**: <20ms total
- **Fail-safe**: Errors mustn't break shell
- **Cache dotfile lookups**: Use associative array `typeset -gA`
- Use `jq` for JSON (available in Nix)

#### ZLE Widget Flow

1. User types `ls -la`, presses Enter
2. `accept-line` widget intercepts
3. `_recordterm_setup_recording` creates `.pending` file for `ls -la`
4. Buffer rewritten to: `asciinema rec --quiet --overwrite -c 'ls -la' /path/to.cast`
5. Command executes
6. `precmd` hook finalizes `.pending` → `.meta.json`
7. Atuin sees original `ls -la` (it hooks `preexec`, before ZLE modification)

#### Builtins That Can't Be Wrapped

These modify current shell state and must run in the current process:
```
cd, pushd, popd, export, unset, source, ., eval, exec, 
builtin, command, alias, unalias, hash, rehash
```

For these, we create `.pending` but set `_RECORDTERM_SKIP_WRAP=1`. In `precmd`, if skip flag is set, delete `.pending` (no `.cast` was created).

### Phase 4: Watcher Service

#### 4.1 `src/recordterm/watcher/main.py`

Entry point that:
1. Loads config
2. Creates storage directories
3. Initializes indexer (SQLite)
4. Starts file watcher (inotify on recordings dir)
5. Starts export queue processor
6. Starts cleanup scheduler
7. Starts status socket server
8. Handles SIGTERM/SIGINT gracefully

Use `asyncio` throughout.

#### 4.2 `src/recordterm/watcher/file_watcher.py`

Use `watchfiles` library (pure Python, works on Linux):

```python
from watchfiles import awatch, Change

async for changes in awatch(directory, stop_event=stop):
    for change_type, path in changes:
        if change_type == Change.added and path.endswith(".meta.json"):
            await on_new_recording(Path(path))
```

#### 4.3 `src/recordterm/watcher/indexer.py`

SQLite operations using `aiosqlite`:
- `initialize()`: Create tables/indexes
- `index_recording(meta_path)`: Parse JSON, INSERT
- `get_by_atuin_id(id)`: Lookup
- `get_by_id(id)`: Lookup
- `list_recordings(limit, offset, failed_only, cwd)`: Query
- `get_stats()`: Counts
- `delete_recording(id)`: Remove from index

#### 4.4 `src/recordterm/watcher/exporter.py`

Background queue processor:
- Polls `export_queue` table for pending jobs
- Runs `agg` (asciinema-agg) subprocess
- Updates recording with gif_path
- Marks job complete or failed

#### 4.5 `src/recordterm/watcher/cleanup.py`

Runs on schedule (default: every 24 hours):
1. Delete recordings older than max_age_days
2. Delete recordings over max_count (oldest first)
3. Delete recordings until under max_size_gb (oldest first)

Each deletion removes files AND index entry.

#### 4.6 `src/recordterm/watcher/server.py`

Unix socket server for CLI communication:
- Accept JSON-line messages
- Dispatch to appropriate handler
- Return JSON-line responses

Actions: `status`, `list`, `get`, `cleanup`, `export`

### Phase 5: CLI

#### 5.1 `src/recordterm/cli/main.py`

Click-based CLI. Commands:
- `status`: Query watcher socket
- `list`: Query watcher socket with filters
- `show <id>`: Get recording, run `asciinema play`
- `export <id>`: Get recording, run export tool
- `cleanup`: Trigger cleanup via socket
- `stats`: Calculate storage stats (can run without watcher)
- `check-path <dir>`: Check if recording enabled
- `init-hooks`: Print shell source commands

#### 5.2 `src/recordterm/cli/client.py`

Simple socket client:
- Connect to Unix socket
- Send JSON + newline
- Read response until newline
- Parse JSON
- Handle connection errors gracefully

### Phase 6: Nix Integration

#### 6.1 `pyproject.toml`

```toml
[project]
name = "recordterm"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "click>=8.0",
    "pydantic>=2.0",
    "tomli>=2.0",
    "aiosqlite>=0.19",
    "watchfiles>=0.21",
]

[project.scripts]
recordterm = "recordterm.cli.main:main"
recordterm-watcher = "recordterm.watcher.main:main"
recordterm-check-path = "recordterm.config:check_path_cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

#### 6.2 `flake.nix`

Key outputs:
- `packages.${system}.default`: The Python package
- `packages.${system}.hooks`: Shell hook scripts
- `homeManagerModules.default`: Home Manager module

The Python package should:
- Include scripts/ in `$out/share/recordterm/`
- Expose three binaries via `project.scripts`

#### 6.3 `modules/home-manager.nix`

Options structure mirrors config.toml structure.

Key features:
- Generate `~/.config/recordterm/config.toml` via `xdg.configFile`
- Add shell init to zsh via `programs.zsh.initExtra`
- Create systemd user service for watcher
- Add runtime dependencies: `asciinema`, `agg`, `jq`

## Coding Standards

### Python

1. **First line of every file**: `from __future__ import annotations`
2. **Second line**: `# src/recordterm/path/to/file.py` (filepath comment)
3. **Imports**: All at top, no inline imports except inside functions where absolutely necessary
4. **Type hints**: No quotes around types (use `from __future__ import annotations`)
5. **Models**: Use Pydantic `BaseModel` for all data classes
6. **Line length**: Max 120 characters
7. **Async**: Use `asyncio` for all I/O in watcher
8. **Errors**: Let errors propagate with context, don't silently swallow

### Shell (zsh only)

1. **First line**: `#!/usr/bin/env zsh`
2. **Shellcheck**: Use `shellcheck -s bash` (closest approximation for zsh)
3. **Quote variables**: Always `"$var"` not `$var`
4. **Error handling**: Wrap risky operations to prevent shell hangs
5. **Performance**: Cache lookups, minimize subprocess calls
6. **ZLE widgets**: Use `.accept-line` (with dot) to call original widget

### Nix

1. Use `lib` functions from nixpkgs
2. Use `mkOption` with full type annotations
3. Use `pkgs.formats.toml` for config generation
4. Proper module options structure with `options` and `config` separation

## Testing Strategy

### Unit Tests

- `tests/test_models/`: Pydantic model validation
- `tests/test_config/`: Config loading, path checking
- `tests/test_indexer/`: SQLite operations (use temp db)

### Integration Tests

- `tests/integration/test_hooks.py`: Run hooks in subprocess, verify file creation
- `tests/integration/test_watcher.py`: Start watcher, create files, verify indexing

### Manual Testing

1. Build flake: `nix build`
2. Enter devshell: `nix develop`
3. Source hooks manually
4. Run commands, verify `.cast` and `.meta.json` created
5. Start watcher, verify indexing
6. Test CLI commands

## Common Pitfalls

### 1. Path Expansion

Always call `.expanduser()` when actually using paths, not in Pydantic models:

```python
# Wrong
class Config(BaseModel):
    storage_dir: Path = Path("~/.local/share/recordterm").expanduser()

# Right
class Config(BaseModel):
    storage_dir: Path = Path("~/.local/share/recordterm")

# At usage
storage = config.storage_dir.expanduser()
```

### 2. Async Context

The watcher is async, but cleanup/export operations run in tasks. Be careful with shared state:

```python
# Wrong - db access from multiple tasks without coordination
async def _process_next(self):
    await self.indexer._db.execute(...)  # Direct access

# Right - indexer methods handle their own transactions
async def _process_next(self):
    await self.indexer.update_export_status(...)
```

### 3. Hook Performance

Hooks run on every command. Profile them:

```bash
time (for i in {1..100}; do _recordterm_should_record; done)
```

Target: <1ms per call (100 calls in <100ms).

### 4. JSON in Shell

Use `jq` for JSON creation, not string interpolation:

```bash
# Wrong - breaks on special characters
echo '{"command": "'$cmd'"}'

# Right
printf '%s' "$cmd" | jq -Rs '{command: .}'
```

### 5. Atuin ID Timing

The atuin ID isn't available until atuin's precmd runs. Our precmd must run after atuin's. In practice, this means sourcing recordterm hooks AFTER atuin init in shell rc.

## Dependencies Reference

### Python (via UV/pip)

| Package | Purpose |
|---------|---------|
| click | CLI framework |
| pydantic | Data validation |
| tomli | TOML parsing |
| aiosqlite | Async SQLite |
| watchfiles | File watching |

### System (via Nix)

| Package | Purpose |
|---------|---------|
| asciinema | Recording playback |
| asciinema-agg (agg) | GIF generation |
| jq | JSON processing in hooks |
| util-linux (script) | Command wrapping |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `RECORDTERM_ENABLED` | Override: `0` disables, `1` enables |
| `RECORDTERM_STORAGE` | Override storage directory |
| `RECORDTERM_CONFIG` | Override config file path |
| `RECORDTERM_CAST_FILE` | Set by preexec, path for recording |
| `RECORDTERM_RECORDING_ID` | Set by preexec, current recording ID |

## Socket Protocol

Request/response over Unix socket, newline-delimited JSON.

### Status

```json
{"action": "status"}
→ {"status": "ok", "stats": {"total_count": 100, "failed_count": 5}}
```

### List

```json
{"action": "list", "limit": 20, "failed_only": false, "cwd": null}
→ {"status": "ok", "recordings": [...]}
```

### Get

```json
{"action": "get", "id": "rec_123_abc"}
→ {"status": "ok", "recording": {...}}
```

Also accepts atuin_id:
```json
{"action": "get", "atuin_id": "0abc123"}
→ {"status": "ok", "recording": {...}}
```

### Cleanup

```json
{"action": "cleanup", "dry_run": false}
→ {"status": "ok", "deleted_count": 10, "freed_bytes": 1048576}
```

### Error Response

```json
{"status": "error", "error": "not_found", "message": "Recording not found"}
```

## Quick Start Implementation

If starting from scratch, implement in this order:

1. `src/recordterm/models/config.py` - Config models
2. `src/recordterm/models/metadata.py` - Metadata models  
3. `src/recordterm/config.py` - Config loading
4. `scripts/hooks.zsh` - ZLE widget + precmd hook
5. `src/recordterm/watcher/indexer.py` - SQLite layer
6. `src/recordterm/watcher/file_watcher.py` - inotify
7. `src/recordterm/watcher/main.py` - Minimal watcher
8. `src/recordterm/cli/main.py` - Basic CLI
9. `pyproject.toml` - Package definition
10. `flake.nix` - Nix packaging
11. `modules/home-manager.nix` - Integration

Add remaining features incrementally:
- Export queue
- Cleanup scheduler
- Status socket
- Full CLI commands

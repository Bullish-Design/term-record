# TermRecord

Automatic terminal recording linked to [atuin](https://github.com/atuinsh/atuin) shell history.

## Overview

TermRecord automatically records your terminal sessions using [asciinema](https://asciinema.org/) and links them to your atuin shell history entries. Recordings are stored as `.cast` files with optional GIF export.

### Features

- **Automatic recording** - Wraps commands transparently via zsh hooks
- **Atuin integration** - Links recordings to atuin history entries
- **Per-directory control** - Use `.termrecord.toml` to disable recording in sensitive directories
- **Path rules** - Configure recording behavior based on directory patterns
- **SQLite indexing** - Fast queries and filtering
- **GIF export** - Convert recordings to animated GIFs
- **Retention policies** - Automatic cleanup based on age, size, or count
- **Non-blocking** - Recording failures never block command execution

## Installation

### NixOS with Home Manager

```nix
{
  inputs.termrecord.url = "github:Bullish-Design/term-record";

  # In your home-manager configuration:
  imports = [ inputs.termrecord.homeManagerModules.default ];

  programs.termrecord = {
    enable = true;

    recording = {
      enable = true;
      format = "cast"; # or "gif" or "both"

      rules = [
        { path = "~/.password-store"; enabled = false; }
        { path = "~/projects/**"; enabled = true; }
      ];
    };

    retention = {
      max_age_days = 30;
      max_size_gb = 10.0;
    };
  };
}
```

## Usage

### CLI Commands

```bash
# Show status
termrecord status

# List recent recordings
termrecord list
termrecord list --failed        # Only failed commands
termrecord list --cwd ~/project # Filter by directory

# Play a recording
termrecord show <id>
termrecord show <id> --speed 2.0

# Export recording
termrecord export <id> -o output.gif --format gif
termrecord export <id> -o output.cast --format cast

# Search recordings
termrecord search "cargo build"

# Storage statistics
termrecord stats

# Manual cleanup
termrecord cleanup
termrecord cleanup --dry-run
```

### Per-Directory Control

Create `.termrecord.toml` in any directory:

```toml
# Disable recording in this directory tree
enabled = false
```

Or with custom settings:

```toml
enabled = true

[recording]
format = "both"  # Generate both .cast and .gif
```

### Environment Variable Override

```bash
# Disable for a single command
TERMRECORD_ENABLED=0 secret-command

# Disable for entire session
export TERMRECORD_ENABLED=0
```

## Architecture

- **Shell hooks** - Zsh hooks intercept commands and wrap with asciinema
- **Watcher service** - Background service indexes recordings and processes exports
- **SQLite index** - Fast querying and metadata storage
- **File-first** - Recordings exist as files immediately; indexing is async

## Development

```bash
# Enter development shell
nix develop

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
```

## License

MIT

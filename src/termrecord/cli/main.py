"""CLI commands."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from termrecord.cli.client import WatcherClient
from termrecord.config import load_config


@click.group()
@click.option("--config", "-c", type=Path, help="Config file path")
@click.pass_context
def cli(ctx: click.Context, config: Path | None) -> None:
    """Termrecord - Automatic terminal recording linked to atuin."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show watcher status and recording stats."""
    config = ctx.obj["config"]
    client = WatcherClient(config.watcher.socket_path)

    try:
        result = client.send({"action": "status"})
        click.echo(f"Watcher: running")
        click.echo(f"Total recordings: {result['stats']['total_count']}")
        click.echo(f"Failed recordings: {result['stats']['failed_count']}")
    except ConnectionError:
        click.echo("Watcher: not running", err=True)
        sys.exit(1)


@cli.command("list")
@click.option("--limit", "-n", default=20, help="Number of recordings to show")
@click.option("--failed", is_flag=True, help="Show only failed commands")
@click.option("--cwd", type=str, help="Filter by directory prefix")
@click.pass_context
def list_recordings(
    ctx: click.Context, limit: int, failed: bool, cwd: str | None
) -> None:
    """List recent recordings."""
    config = ctx.obj["config"]
    client = WatcherClient(config.watcher.socket_path)

    result = client.send(
        {"action": "list", "limit": limit, "failed_only": failed, "cwd": cwd}
    )

    for rec in result["recordings"]:
        status_icon = "✗" if rec["exit_code"] != 0 else "✓"
        duration = f"{rec['duration']:.1f}s" if rec["duration"] else "?"
        click.echo(f"{status_icon} [{rec['id'][:20]}] {duration} {rec['command'][:60]}")


@cli.command()
@click.argument("recording_id")
@click.option("--speed", "-s", default=1.0, help="Playback speed")
@click.pass_context
def show(ctx: click.Context, recording_id: str, speed: float) -> None:
    """Play a recording."""
    config = ctx.obj["config"]
    client = WatcherClient(config.watcher.socket_path)

    result = client.send({"action": "get", "id": recording_id})

    if not result.get("recording"):
        click.echo(f"Recording not found: {recording_id}", err=True)
        sys.exit(1)

    cast_path = (
        config.recording.storage_dir.expanduser()
        / "recordings"
        / result["recording"]["cast_path"]
    )

    subprocess.run(["asciinema", "play", "-s", str(speed), str(cast_path)])


@cli.command()
@click.argument("recording_id")
@click.option("-o", "--output", required=True, type=Path, help="Output path")
@click.option(
    "--format",
    "fmt",
    default="gif",
    type=click.Choice(["gif", "png", "cast"]),
)
@click.option("--speed", default=1.0, help="GIF playback speed")
@click.pass_context
def export(
    ctx: click.Context, recording_id: str, output: Path, fmt: str, speed: float
) -> None:
    """Export a recording."""
    config = ctx.obj["config"]
    client = WatcherClient(config.watcher.socket_path)

    result = client.send({"action": "get", "id": recording_id})

    if not result.get("recording"):
        click.echo(f"Recording not found: {recording_id}", err=True)
        sys.exit(1)

    cast_path = (
        config.recording.storage_dir.expanduser()
        / "recordings"
        / result["recording"]["cast_path"]
    )

    if fmt == "cast":
        import shutil

        shutil.copy(cast_path, output)
    elif fmt == "gif":
        subprocess.run(
            [
                "agg",
                str(cast_path),
                str(output),
                "--speed",
                str(speed),
            ],
            check=True,
        )
    elif fmt == "png":
        # Use asciinema's screenshot capability or agg
        subprocess.run(
            ["agg", str(cast_path), str(output), "--last-frame"], check=True
        )

    click.echo(f"Exported to: {output}")


@cli.command()
@click.argument("directory", type=Path)
@click.pass_context
def check_path(ctx: click.Context, directory: Path) -> None:
    """Check if recording is enabled for a directory."""
    from termrecord.config import is_recording_enabled

    config = ctx.obj["config"]
    enabled = is_recording_enabled(config, directory)

    if enabled:
        click.echo("Recording: enabled")
        sys.exit(0)
    else:
        click.echo("Recording: disabled")
        sys.exit(1)


@cli.command()
def init_hooks() -> None:
    """Print shell hook initialization commands for zsh."""
    click.echo('source "${TERMRECORD_HOOKS:-@hooks@/hooks.zsh}"')


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
@click.pass_context
def cleanup(ctx: click.Context, dry_run: bool) -> None:
    """Run retention cleanup."""
    config = ctx.obj["config"]
    client = WatcherClient(config.watcher.socket_path)

    result = client.send({"action": "cleanup", "dry_run": dry_run})

    prefix = "[dry-run] " if dry_run else ""
    click.echo(f"{prefix}Deleted: {result['deleted_count']} recordings")
    click.echo(f"{prefix}Freed: {result['freed_bytes'] / 1024 / 1024:.1f} MB")


@cli.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show storage statistics."""
    config = ctx.obj["config"]
    storage_dir = config.recording.storage_dir.expanduser()
    recordings_dir = storage_dir / "recordings"

    total_size = 0
    total_count = 0
    cast_size = 0
    gif_size = 0

    if recordings_dir.exists():
        for path in recordings_dir.rglob("*"):
            if path.is_file():
                size = path.stat().st_size
                total_size += size
                if path.suffix == ".cast":
                    cast_size += size
                    total_count += 1
                elif path.suffix == ".gif":
                    gif_size += size

    click.echo(f"Storage directory: {storage_dir}")
    click.echo(f"Total recordings: {total_count}")
    click.echo(f"Total size: {total_size / 1024 / 1024:.1f} MB")
    click.echo(f"  Cast files: {cast_size / 1024 / 1024:.1f} MB")
    click.echo(f"  GIF files: {gif_size / 1024 / 1024:.1f} MB")


@cli.command()
@click.argument("query")
@click.pass_context
def search(ctx: click.Context, query: str) -> None:
    """Search recordings by command text."""
    config = ctx.obj["config"]
    storage_dir = config.recording.storage_dir.expanduser()
    recordings_dir = storage_dir / "recordings"

    if not recordings_dir.exists():
        click.echo("No recordings found")
        return

    matches = []
    for meta_file in recordings_dir.rglob("*.meta.json"):
        import json

        with open(meta_file) as f:
            meta = json.load(f)
            if query.lower() in meta.get("command", "").lower():
                matches.append(meta)

    matches.sort(key=lambda x: x["timestamp"], reverse=True)

    for meta in matches[:20]:
        status_icon = "✗" if meta.get("exit_code", 0) != 0 else "✓"
        duration = (
            f"{meta['duration']:.1f}s" if meta.get("duration") else "?"
        )
        click.echo(
            f"{status_icon} [{meta['id'][:20]}] {duration} {meta['command'][:60]}"
        )


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()

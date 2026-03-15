"""CLI command: spectral catalog search."""

from __future__ import annotations

import click
from rich.table import Table

from cli.commands.catalog.types import CatalogEntry
from cli.helpers.console import console


@click.command()
@click.argument("query")
def search(query: str) -> None:
    """Search the community catalog for tool collections."""
    from cli.helpers.catalog_api import search as api_search
    from cli.helpers.storage import app_dir

    _send_stats_best_effort()

    try:
        results = api_search(query)
    except Exception as exc:
        raise click.ClickException(f"Search failed: {exc}") from exc

    if not results:
        console.print("[dim]No results found.[/dim]")
        return

    entries = [_parse_entry(r, app_dir) for r in results]

    table = Table(title="Catalog Results")
    table.add_column("Collection", style="bold")
    table.add_column("Description")
    table.add_column("Tools", justify="right")
    table.add_column("Success", justify="right")
    table.add_column("Usage", justify="right")
    table.add_column("", justify="center")  # installed badge

    for entry in entries:
        table.add_row(
            f"{entry.username}/{entry.app_name}",
            entry.description,
            str(entry.tool_count),
            f"{entry.success_rate:.0%}" if entry.total_calls > 0 else "-",
            str(entry.total_calls) if entry.total_calls > 0 else "-",
            "[green]Installed[/green]" if entry.installed else "",
        )

    console.print(table)


def _parse_entry(
    raw: dict[str, object], app_dir: object
) -> CatalogEntry:
    """Convert a raw API response dict into a CatalogEntry."""
    from pathlib import Path
    from typing import Any, Callable, cast

    _app_dir = cast(Callable[[str], Path], app_dir)
    username = str(raw.get("username", ""))
    app_name = str(raw.get("app_name", ""))
    local_name = f"{username}__{app_name}"
    stats = cast(dict[str, Any], raw.get("stats", {}))

    return CatalogEntry(
        username=username,
        app_name=app_name,
        display_name=str(raw.get("display_name", "")),
        description=str(raw.get("description", "")),
        tool_count=int(cast(int, raw.get("tool_count", 0))),
        published_at=str(raw.get("published_at", "")),
        total_calls=int(stats.get("total_calls", 0)),
        success_rate=float(stats.get("success_rate", 0)),
        unique_users=int(stats.get("unique_users", 0)),
        installed=(_app_dir(local_name) / "app.json").is_file(),
    )


def _send_stats_best_effort() -> None:
    """Send local stats to the backend in a best-effort manner."""
    import hashlib
    import platform

    from cli.helpers.catalog_api import report_stats
    from cli.helpers.storage import list_apps, load_stats

    # Generate anonymous user hash
    user_hash = hashlib.sha256(platform.node().encode()).hexdigest()[:16]

    all_stats: list[dict[str, object]] = []
    for app_meta in list_apps():
        name = app_meta.name
        if "__" not in name:
            continue
        # Only report stats for catalog-installed apps
        stats = load_stats(name)
        if not stats.root:
            continue
        parts = name.split("__", 1)
        if len(parts) != 2:
            continue
        collection_ref = f"{parts[0]}/{parts[1]}"
        for tool_name, tool_stats in stats.root.items():
            all_stats.append({
                "collection_ref": collection_ref,
                "tool_name": tool_name,
                "call_count": tool_stats.call_count,
                "success_count": tool_stats.success_count,
                "error_count": tool_stats.error_count,
            })

    if all_stats:
        report_stats(user_hash, all_stats)

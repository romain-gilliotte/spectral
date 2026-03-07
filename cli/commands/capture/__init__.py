"""Capture command group — registration only."""

from __future__ import annotations

import click

from cli.commands.capture.discover import discover
from cli.commands.capture.inspect import inspect_cmd
from cli.commands.capture.list import list_cmd
from cli.commands.capture.proxy import proxy_cmd
from cli.commands.capture.show import show


@click.group()
def capture() -> None:
    """Capture tools: import bundles, inspect, run MITM proxy."""


capture.add_command(list_cmd)
capture.add_command(show)
capture.add_command(inspect_cmd)
capture.add_command(proxy_cmd, "proxy")
capture.add_command(discover)

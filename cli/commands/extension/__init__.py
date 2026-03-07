"""Extension command group — registration only."""

from __future__ import annotations

import click

from cli.commands.extension.host import listen
from cli.commands.extension.manifest import install


@click.group()
def extension() -> None:
    """Chrome extension integration: native messaging host."""


extension.add_command(listen)
extension.add_command(install)

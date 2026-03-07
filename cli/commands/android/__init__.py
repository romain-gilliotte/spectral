"""Android command group — registration only."""

from __future__ import annotations

import click

from cli.commands.android.cert import cert
from cli.commands.android.install import install
from cli.commands.android.list import list_cmd
from cli.commands.android.patch import patch_cmd
from cli.commands.android.pull import pull


@click.group()
def android() -> None:
    """Android APK tools (pull, patch, install, cert)."""


android.add_command(list_cmd)
android.add_command(pull)
android.add_command(patch_cmd, "patch")
android.add_command(install)
android.add_command(cert)

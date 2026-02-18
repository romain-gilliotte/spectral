"""Shell command runner with uniform error handling."""

from __future__ import annotations

import subprocess


def run_cmd(
    cmd: list[str], description: str, *, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command, raising RuntimeError on failure.

    Args:
        cmd: Command and arguments.
        description: Human-readable label for error messages.
        timeout: Maximum seconds to wait (default 120).

    Returns:
        The CompletedProcess on success.

    Raises:
        RuntimeError: If the process exits with a non-zero code.
    """
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"{description} (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result

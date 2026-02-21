"""Catch-all branch that logs traces with unsupported protocols."""

from __future__ import annotations

from collections import Counter

from cli.commands.analyze.protocol import PROTOCOL_DISPLAY_NAMES, detect_trace_protocol
from cli.commands.analyze.steps.base import ProtocolBranch
from cli.commands.analyze.steps.types import BranchContext, BranchOutput
from cli.commands.capture.types import Trace


class UnsupportedBranch(ProtocolBranch):
    """Catch-all branch for protocols the pipeline cannot produce specs for.

    Receives all traces not claimed by a specific-protocol branch,
    logs a summary of what was skipped, and returns None (no output).
    """

    protocol = "_unsupported"
    file_extension = ""
    label = "Unsupported protocols"
    catch_all = True

    async def run(
        self, traces: list[Trace], ctx: BranchContext
    ) -> BranchOutput | None:
        if not traces:
            return None

        counts = Counter(detect_trace_protocol(t) for t in traces)
        parts: list[str] = []
        for protocol, count in counts.most_common():
            display = PROTOCOL_DISPLAY_NAMES.get(protocol, protocol)
            parts.append(f"{count} {display}")

        summary = ", ".join(parts)
        ctx.on_progress(f"  Skipped: {summary} (unsupported protocols)")

        return None

"""Time-window correlation: UI action -> API calls."""

from cli.analyze.steps.types import Correlation
from cli.capture.types import CaptureBundle, Trace, WsMessage

DEFAULT_WINDOW_MS = 2000


def correlate(
    bundle: CaptureBundle, window_ms: int = DEFAULT_WINDOW_MS
) -> list[Correlation]:
    """Correlate UI contexts with API traces using a time window.

    For each context event, finds all traces and WS messages that occurred
    within `window_ms` milliseconds after the context event.
    """
    # Sort contexts by timestamp
    sorted_contexts = sorted(bundle.contexts, key=lambda c: c.meta.timestamp)
    # Sort traces by timestamp
    sorted_traces = sorted(bundle.traces, key=lambda t: t.meta.timestamp)
    # Collect all WS messages with timestamps
    all_ws_messages: list[WsMessage] = []
    for ws_conn in bundle.ws_connections:
        all_ws_messages.extend(ws_conn.messages)
    all_ws_messages.sort(key=lambda m: m.meta.timestamp)

    correlations: list[Correlation] = []

    for i, ctx in enumerate(sorted_contexts):
        start_ts = ctx.meta.timestamp
        # Window ends at either window_ms after context, or at the next context
        end_ts = start_ts + window_ms
        if i + 1 < len(sorted_contexts):
            next_ctx_ts = sorted_contexts[i + 1].meta.timestamp
            end_ts = min(end_ts, next_ctx_ts)

        # Find traces in window
        matched_traces = [
            t for t in sorted_traces if start_ts <= t.meta.timestamp < end_ts
        ]

        # Find WS messages in window
        matched_ws = [
            m for m in all_ws_messages if start_ts <= m.meta.timestamp < end_ts
        ]

        correlations.append(
            Correlation(
                context=ctx,
                traces=matched_traces,
                ws_messages=matched_ws,
            )
        )

    return correlations


def find_uncorrelated_traces(
    bundle: CaptureBundle, correlations: list[Correlation]
) -> list[Trace]:
    """Find traces that were not correlated with any context."""
    correlated_ids: set[str] = set()
    for corr in correlations:
        for t in corr.traces:
            correlated_ids.add(t.meta.id)
    return [t for t in bundle.traces if t.meta.id not in correlated_ids]

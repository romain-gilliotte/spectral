"""Tests for time-window correlator."""

from cli.analyze.correlator import correlate, find_uncorrelated_traces
from cli.capture.models import CaptureBundle, Context, Trace, WsConnection
from cli.formats.capture_bundle import (
    AppInfo,
    BrowserInfo,
    CaptureManifest,
    CaptureStats,
    Timeline,
)
from tests.conftest import make_context, make_trace, make_ws_connection, make_ws_message


def _make_bundle(
    traces: list[Trace] | None = None,
    contexts: list[Context] | None = None,
    ws_connections: list[WsConnection] | None = None,
) -> CaptureBundle:
    """Helper to make a minimal bundle for testing correlator."""
    return CaptureBundle(
        manifest=CaptureManifest(
            capture_id="test",
            created_at="2026-01-01T00:00:00Z",
            app=AppInfo(name="T", base_url="http://localhost", title="T"),
            browser=BrowserInfo(name="Chrome", version="1.0"),
            duration_ms=10000,
            stats=CaptureStats(),
        ),
        traces=traces or [],
        contexts=contexts or [],
        ws_connections=ws_connections or [],
        timeline=Timeline(),
    )


class TestCorrelate:
    def test_basic_correlation(self):
        """Traces within 2s window after context should be correlated."""
        ctx = make_context("c_0001", timestamp=1000)
        trace1 = make_trace("t_0001", "GET", "http://localhost/a", 200, timestamp=1500)
        trace2 = make_trace("t_0002", "GET", "http://localhost/b", 200, timestamp=2500)

        bundle = _make_bundle(traces=[trace1, trace2], contexts=[ctx])
        correlations = correlate(bundle)

        assert len(correlations) == 1
        assert correlations[0].context.meta.id == "c_0001"
        assert len(correlations[0].traces) == 2

    def test_window_cutoff(self):
        """Traces beyond 2s window should not be correlated."""
        ctx = make_context("c_0001", timestamp=1000)
        trace_in = make_trace(
            "t_0001", "GET", "http://localhost/a", 200, timestamp=2500
        )
        trace_out = make_trace(
            "t_0002", "GET", "http://localhost/b", 200, timestamp=3500
        )

        bundle = _make_bundle(traces=[trace_in, trace_out], contexts=[ctx])
        correlations = correlate(bundle)

        assert len(correlations) == 1
        assert len(correlations[0].traces) == 1
        assert correlations[0].traces[0].meta.id == "t_0001"

    def test_multiple_contexts(self):
        """Each context gets its own correlation window."""
        ctx1 = make_context("c_0001", timestamp=1000)
        ctx2 = make_context("c_0002", timestamp=3000)
        trace1 = make_trace("t_0001", "GET", "http://localhost/a", 200, timestamp=1500)
        trace2 = make_trace("t_0002", "GET", "http://localhost/b", 200, timestamp=3500)

        bundle = _make_bundle(traces=[trace1, trace2], contexts=[ctx1, ctx2])
        correlations = correlate(bundle)

        assert len(correlations) == 2
        assert len(correlations[0].traces) == 1
        assert correlations[0].traces[0].meta.id == "t_0001"
        assert len(correlations[1].traces) == 1
        assert correlations[1].traces[0].meta.id == "t_0002"

    def test_context_window_bounded_by_next_context(self):
        """Window should be bounded by the next context timestamp."""
        ctx1 = make_context("c_0001", timestamp=1000)
        ctx2 = make_context("c_0002", timestamp=1500)
        trace = make_trace("t_0001", "GET", "http://localhost/a", 200, timestamp=1200)
        trace_after = make_trace(
            "t_0002", "GET", "http://localhost/b", 200, timestamp=1600
        )

        bundle = _make_bundle(traces=[trace, trace_after], contexts=[ctx1, ctx2])
        correlations = correlate(bundle)

        # ctx1's window ends at ctx2 (1500), so only trace at 1200 matches ctx1
        assert len(correlations[0].traces) == 1
        assert correlations[0].traces[0].meta.id == "t_0001"
        # ctx2's window: 1500..3500, trace at 1600 matches
        assert len(correlations[1].traces) == 1
        assert correlations[1].traces[0].meta.id == "t_0002"

    def test_no_contexts(self):
        """Bundle with no contexts returns empty correlations."""
        trace = make_trace("t_0001", "GET", "http://localhost/a", 200, timestamp=1000)
        bundle = _make_bundle(traces=[trace])
        correlations = correlate(bundle)
        assert len(correlations) == 0

    def test_no_traces(self):
        """Bundle with no traces still creates correlations for contexts."""
        ctx = make_context("c_0001", timestamp=1000)
        bundle = _make_bundle(contexts=[ctx])
        correlations = correlate(bundle)
        assert len(correlations) == 1
        assert len(correlations[0].traces) == 0

    def test_ws_message_correlation(self):
        """WebSocket messages should also be correlated."""
        ctx = make_context("c_0001", timestamp=1000)
        msg = make_ws_message("ws_0001_m001", "ws_0001", 1500, "send", b'{"test":1}')
        ws_conn = make_ws_connection(
            "ws_0001", "wss://example.com/ws", 900, messages=[msg]
        )

        bundle = _make_bundle(contexts=[ctx], ws_connections=[ws_conn])
        correlations = correlate(bundle)

        assert len(correlations) == 1
        assert len(correlations[0].ws_messages) == 1

    def test_custom_window(self):
        """Custom window size should be respected."""
        ctx = make_context("c_0001", timestamp=1000)
        trace_close = make_trace(
            "t_0001", "GET", "http://localhost/a", 200, timestamp=1200
        )
        trace_far = make_trace(
            "t_0002", "GET", "http://localhost/b", 200, timestamp=1600
        )

        bundle = _make_bundle(traces=[trace_close, trace_far], contexts=[ctx])
        correlations = correlate(bundle, window_ms=500)

        assert len(correlations[0].traces) == 1
        assert correlations[0].traces[0].meta.id == "t_0001"

    def test_trace_before_context_not_correlated(self):
        """Traces before a context timestamp should not be correlated."""
        ctx = make_context("c_0001", timestamp=2000)
        trace = make_trace("t_0001", "GET", "http://localhost/a", 200, timestamp=1000)

        bundle = _make_bundle(traces=[trace], contexts=[ctx])
        correlations = correlate(bundle)

        assert len(correlations[0].traces) == 0


class TestFindUncorrelated:
    def test_finds_uncorrelated_traces(self):
        ctx = make_context("c_0001", timestamp=1000)
        trace1 = make_trace("t_0001", "GET", "http://localhost/a", 200, timestamp=1500)
        trace2 = make_trace("t_0002", "GET", "http://localhost/b", 200, timestamp=5000)

        bundle = _make_bundle(traces=[trace1, trace2], contexts=[ctx])
        correlations = correlate(bundle)
        uncorrelated = find_uncorrelated_traces(bundle, correlations)

        assert len(uncorrelated) == 1
        assert uncorrelated[0].meta.id == "t_0002"

    def test_all_correlated(self):
        ctx = make_context("c_0001", timestamp=1000)
        trace = make_trace("t_0001", "GET", "http://localhost/a", 200, timestamp=1500)

        bundle = _make_bundle(traces=[trace], contexts=[ctx])
        correlations = correlate(bundle)
        uncorrelated = find_uncorrelated_traces(bundle, correlations)

        assert len(uncorrelated) == 0

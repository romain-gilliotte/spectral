# pyright: reportPrivateUsage=false
"""Tests for extraction helpers in cli.helpers.auth._extract."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from cli.commands.auth.extract import (
    _extract_auth_from_traces,
    extract,
)
from cli.commands.capture.types import CaptureBundle, Trace
from cli.formats.capture_bundle import Header
from cli.helpers.auth._extract import (
    extract_headers_by_name,
    filter_traces_by_base_url,
    find_authorization_header,
)
from tests.conftest import make_trace

BASE_URL = "https://api.example.com"
CMD_MODULE = "cli.commands.auth.extract"


def _bearer_trace(trace_id: str, timestamp: int, token: str = "tok") -> Trace:
    return make_trace(
        trace_id,
        "GET",
        f"{BASE_URL}/data",
        200,
        timestamp=timestamp,
        request_headers=[Header(name="Authorization", value=f"Bearer {token}")],
    )


def _plain_trace(trace_id: str, url: str, timestamp: int) -> Trace:
    return make_trace(
        trace_id,
        "GET",
        url,
        200,
        timestamp=timestamp,
        request_headers=[Header(name="Accept", value="application/json")],
    )


# ------------------------------------------------------------------
# filter_traces_by_base_url
# ------------------------------------------------------------------


class TestFilterTracesByBaseUrl:
    def test_filters_matching_traces(self) -> None:
        matching = _plain_trace("t1", f"{BASE_URL}/users", 100)
        other = _plain_trace("t2", "https://cdn.other.com/img.png", 200)
        also_matching = _plain_trace("t3", f"{BASE_URL}/orders", 300)

        result = filter_traces_by_base_url([matching, other, also_matching], BASE_URL)

        ids = [t.meta.id for t in result]
        assert ids == ["t3", "t1"]
        assert "t2" not in ids

    def test_sorts_by_timestamp_descending(self) -> None:
        t_early = _plain_trace("t1", f"{BASE_URL}/a", 100)
        t_mid = _plain_trace("t2", f"{BASE_URL}/b", 200)
        t_late = _plain_trace("t3", f"{BASE_URL}/c", 300)

        result = filter_traces_by_base_url([t_mid, t_early, t_late], BASE_URL)

        timestamps = [t.meta.timestamp for t in result]
        assert timestamps == [300, 200, 100]


# ------------------------------------------------------------------
# find_authorization_header
# ------------------------------------------------------------------


class TestFindAuthorizationHeader:
    def test_found_in_first_trace(self) -> None:
        traces = [_bearer_trace("t1", 100, "secret")]

        result = find_authorization_header(traces)

        assert result == {"Authorization": "Bearer secret"}

    def test_not_found(self) -> None:
        traces = [
            _plain_trace("t1", f"{BASE_URL}/a", 100),
            _plain_trace("t2", f"{BASE_URL}/b", 200),
        ]

        result = find_authorization_header(traces)

        assert result is None

    def test_picks_most_recent(self) -> None:
        """First trace in the (already sorted) list wins."""
        recent = _bearer_trace("t1", 300, "new-token")
        older = _bearer_trace("t2", 100, "old-token")

        result = find_authorization_header([recent, older])

        assert result == {"Authorization": "Bearer new-token"}


# ------------------------------------------------------------------
# extract_headers_by_name
# ------------------------------------------------------------------


class TestExtractHeadersByName:
    def test_extracts_named_headers(self) -> None:
        trace = make_trace(
            "t1",
            "GET",
            f"{BASE_URL}/resource",
            200,
            timestamp=100,
            request_headers=[
                Header(name="X-Api-Key", value="key-abc"),
                Header(name="Accept", value="application/json"),
            ],
        )

        result = extract_headers_by_name([trace], BASE_URL, ["X-Api-Key"])

        assert result == {"X-Api-Key": "key-abc"}

    def test_case_insensitive(self) -> None:
        trace = make_trace(
            "t1",
            "GET",
            f"{BASE_URL}/resource",
            200,
            timestamp=100,
            request_headers=[
                Header(name="Authorization", value="Bearer xyz"),
            ],
        )

        result = extract_headers_by_name([trace], BASE_URL, ["authorization"])

        assert result == {"Authorization": "Bearer xyz"}

    def test_returns_none_when_absent(self) -> None:
        trace = make_trace(
            "t1",
            "GET",
            f"{BASE_URL}/resource",
            200,
            timestamp=100,
            request_headers=[Header(name="Accept", value="text/html")],
        )

        result = extract_headers_by_name([trace], BASE_URL, ["X-Secret"])

        assert result is None


# ------------------------------------------------------------------
# _extract_auth_from_traces
# ------------------------------------------------------------------


def _bundle_with_traces(traces: list[Trace]) -> CaptureBundle:
    bundle = MagicMock(spec=CaptureBundle)
    bundle.traces = traces

    def _filter(pred: object) -> MagicMock:
        return MagicMock(
            spec=CaptureBundle, traces=[t for t in traces if pred(t)]  # type: ignore[operator]
        )

    bundle.filter_traces = _filter
    return bundle


class TestExtractAuthFromTraces:
    @patch("cli.helpers.detect_base_url.detect_base_urls", return_value=[BASE_URL])
    def test_fast_path_authorization_header(self, _mock_detect: object) -> None:
        traces = [_bearer_trace("t1", 200, "my-secret")]
        bundle = _bundle_with_traces(traces)

        result = _extract_auth_from_traces(bundle, "myapp")

        assert result is not None
        assert result.headers == {"Authorization": "Bearer my-secret"}

    @patch("cli.helpers.detect_base_url.detect_base_urls", return_value=[BASE_URL])
    def test_fast_path_picks_most_recent(self, _mock_detect: object) -> None:
        traces = [
            _bearer_trace("t1", 100, "old"),
            _bearer_trace("t2", 300, "new"),
        ]
        bundle = _bundle_with_traces(traces)

        result = _extract_auth_from_traces(bundle, "myapp")

        assert result is not None
        assert result.headers == {"Authorization": "Bearer new"}

    @patch("cli.helpers.detect_base_url.detect_base_urls", return_value=[BASE_URL])
    def test_no_matching_traces_returns_none(self, _mock_detect: object) -> None:
        traces = [_plain_trace("t1", "https://other.com/x", 100)]
        bundle = _bundle_with_traces(traces)

        result = _extract_auth_from_traces(bundle, "myapp")

        assert result is None

    @patch(f"{CMD_MODULE}._llm_identify_auth_headers", return_value=["X-Api-Key"])
    @patch("cli.helpers.detect_base_url.detect_base_urls", return_value=[BASE_URL])
    def test_llm_fallback_identifies_custom_header(
        self, _mock_detect: object, _mock_llm: object
    ) -> None:
        trace = make_trace(
            "t1",
            "GET",
            f"{BASE_URL}/data",
            200,
            timestamp=100,
            request_headers=[
                Header(name="X-Api-Key", value="key-123"),
                Header(name="Accept", value="application/json"),
            ],
        )
        bundle = _bundle_with_traces([trace])

        result = _extract_auth_from_traces(bundle, "myapp")

        assert result is not None
        assert result.headers == {"X-Api-Key": "key-123"}

    @patch(f"{CMD_MODULE}._llm_identify_auth_headers", return_value=[])
    @patch("cli.helpers.detect_base_url.detect_base_urls", return_value=[BASE_URL])
    def test_llm_finds_no_auth_headers(
        self, _mock_detect: object, _mock_llm: object
    ) -> None:
        traces = [_plain_trace("t1", f"{BASE_URL}/public", 100)]
        bundle = _bundle_with_traces(traces)

        result = _extract_auth_from_traces(bundle, "myapp")

        assert result is None

    @patch(f"{CMD_MODULE}._llm_identify_auth_headers", return_value=["X-Secret"])
    @patch("cli.helpers.detect_base_url.detect_base_urls", return_value=[BASE_URL])
    def test_llm_identifies_header_absent_from_traces(
        self, _mock_detect: object, _mock_llm: object
    ) -> None:
        """LLM says X-Secret, but no trace in base_url has it."""
        traces = [_plain_trace("t1", f"{BASE_URL}/data", 100)]
        bundle = _bundle_with_traces(traces)

        result = _extract_auth_from_traces(bundle, "myapp")

        assert result is None


# ------------------------------------------------------------------
# extract command
# ------------------------------------------------------------------


_DETECT_PATCH = "cli.helpers.detect_base_url.detect_base_urls"


class TestExtractCommand:
    def test_token_saved(self) -> None:
        bundle = _bundle_with_traces([_bearer_trace("t1", 100, "tok")])

        with (
            patch(f"{CMD_MODULE}.resolve_app"),
            patch(f"{CMD_MODULE}.load_app_bundle", return_value=bundle),
            patch(_DETECT_PATCH, return_value=[BASE_URL]),
            patch(f"{CMD_MODULE}.write_token") as mock_write,
        ):
            result = CliRunner().invoke(extract, ["myapp"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Token saved" in result.output
        mock_write.assert_called_once()
        token = mock_write.call_args[0][1]
        assert token.headers == {"Authorization": "Bearer tok"}

    def test_no_auth_found(self) -> None:
        bundle = _bundle_with_traces(
            [_plain_trace("t1", "https://other.com/x", 100)]
        )

        with (
            patch(f"{CMD_MODULE}.resolve_app"),
            patch(f"{CMD_MODULE}.load_app_bundle", return_value=bundle),
            patch(_DETECT_PATCH, return_value=[BASE_URL]),
            patch(f"{CMD_MODULE}.write_token") as mock_write,
        ):
            result = CliRunner().invoke(extract, ["myapp"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No auth headers found" in result.output
        mock_write.assert_not_called()

"""Tests for HAR import/export."""

import json
import tempfile
from pathlib import Path

from cli.capture.loader import write_bundle_bytes, load_bundle_bytes
from cli.har import bundle_to_har, har_to_bundle


def _make_sample_har() -> dict:
    """Create a sample HAR for testing."""
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "Chrome", "version": "133.0"},
            "browser": {"name": "Chrome", "version": "133.0"},
            "pages": [{"title": "Test Page"}],
            "entries": [
                {
                    "startedDateTime": "2026-02-13T15:30:00.000Z",
                    "time": 150,
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/users",
                        "httpVersion": "HTTP/1.1",
                        "headers": [
                            {"name": "Authorization", "value": "Bearer token123"},
                            {"name": "Accept", "value": "application/json"},
                        ],
                        "queryString": [],
                        "cookies": [],
                        "headersSize": -1,
                        "bodySize": 0,
                    },
                    "response": {
                        "status": 200,
                        "statusText": "OK",
                        "httpVersion": "HTTP/1.1",
                        "headers": [
                            {"name": "Content-Type", "value": "application/json"},
                        ],
                        "cookies": [],
                        "content": {
                            "size": 50,
                            "mimeType": "application/json",
                            "text": '[{"id": 1, "name": "Alice"}]',
                        },
                        "redirectURL": "",
                        "headersSize": -1,
                        "bodySize": 50,
                    },
                    "cache": {},
                    "timings": {
                        "dns": 2,
                        "connect": 10,
                        "ssl": 5,
                        "send": 1,
                        "wait": 120,
                        "receive": 12,
                    },
                },
                {
                    "startedDateTime": "2026-02-13T15:30:01.000Z",
                    "time": 200,
                    "request": {
                        "method": "POST",
                        "url": "https://api.example.com/users",
                        "httpVersion": "HTTP/1.1",
                        "headers": [
                            {"name": "Content-Type", "value": "application/json"},
                        ],
                        "queryString": [],
                        "cookies": [],
                        "headersSize": -1,
                        "bodySize": 20,
                        "postData": {
                            "mimeType": "application/json",
                            "text": '{"name": "Bob"}',
                        },
                    },
                    "response": {
                        "status": 201,
                        "statusText": "Created",
                        "httpVersion": "HTTP/1.1",
                        "headers": [],
                        "cookies": [],
                        "content": {
                            "size": 30,
                            "mimeType": "application/json",
                            "text": '{"id": 2, "name": "Bob"}',
                        },
                        "redirectURL": "",
                        "headersSize": -1,
                        "bodySize": 30,
                    },
                    "cache": {},
                    "timings": {
                        "dns": 0,
                        "connect": 0,
                        "ssl": 0,
                        "send": 2,
                        "wait": 180,
                        "receive": 18,
                    },
                },
            ],
        }
    }


class TestHarImport:
    def test_basic_import(self, tmp_path):
        har = _make_sample_har()
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        bundle = har_to_bundle(har_path)

        assert bundle.manifest.app.base_url == "https://api.example.com"
        assert len(bundle.traces) == 2

    def test_trace_methods(self, tmp_path):
        har = _make_sample_har()
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        bundle = har_to_bundle(har_path)

        assert bundle.traces[0].meta.request.method == "GET"
        assert bundle.traces[1].meta.request.method == "POST"

    def test_response_status(self, tmp_path):
        har = _make_sample_har()
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        bundle = har_to_bundle(har_path)

        assert bundle.traces[0].meta.response.status == 200
        assert bundle.traces[1].meta.response.status == 201

    def test_request_headers_imported(self, tmp_path):
        har = _make_sample_har()
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        bundle = har_to_bundle(har_path)

        headers = {h.name: h.value for h in bundle.traces[0].meta.request.headers}
        assert headers["Authorization"] == "Bearer token123"

    def test_response_body_imported(self, tmp_path):
        har = _make_sample_har()
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        bundle = har_to_bundle(har_path)

        body = json.loads(bundle.traces[0].response_body)
        assert body == [{"id": 1, "name": "Alice"}]

    def test_request_body_imported(self, tmp_path):
        har = _make_sample_har()
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        bundle = har_to_bundle(har_path)

        body = json.loads(bundle.traces[1].request_body)
        assert body == {"name": "Bob"}

    def test_timing_imported(self, tmp_path):
        har = _make_sample_har()
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        bundle = har_to_bundle(har_path)

        timing = bundle.traces[0].meta.timing
        assert timing.dns_ms == 2
        assert timing.wait_ms == 120
        assert timing.total_ms == 150

    def test_timeline_created(self, tmp_path):
        har = _make_sample_har()
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        bundle = har_to_bundle(har_path)

        assert len(bundle.timeline.events) == 2
        assert all(e.type == "trace" for e in bundle.timeline.events)

    def test_base64_response(self, tmp_path):
        """Test importing base64-encoded response body."""
        import base64
        har = _make_sample_har()
        # Modify second entry to have base64 body
        har["log"]["entries"][1]["response"]["content"]["text"] = base64.b64encode(b"binary data").decode()
        har["log"]["entries"][1]["response"]["content"]["encoding"] = "base64"

        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(har))

        bundle = har_to_bundle(har_path)
        assert bundle.traces[1].response_body == b"binary data"


class TestHarExport:
    def test_basic_export(self, sample_bundle):
        har = bundle_to_har(sample_bundle)

        assert har["log"]["version"] == "1.2"
        assert har["log"]["creator"]["name"] == "api-discover"
        assert len(har["log"]["entries"]) == len(sample_bundle.traces)

    def test_request_preserved(self, sample_bundle):
        har = bundle_to_har(sample_bundle)

        entry = har["log"]["entries"][0]
        assert entry["request"]["method"] == "GET"
        assert "https://api.example.com/api/users" in entry["request"]["url"]

    def test_response_preserved(self, sample_bundle):
        har = bundle_to_har(sample_bundle)

        entry = har["log"]["entries"][0]
        assert entry["response"]["status"] == 200

    def test_browser_info(self, sample_bundle):
        har = bundle_to_har(sample_bundle)

        assert har["log"]["browser"]["name"] == "Chrome"
        assert har["log"]["browser"]["version"] == "133.0"

    def test_headers_preserved(self, sample_bundle):
        har = bundle_to_har(sample_bundle)

        entry = har["log"]["entries"][0]
        header_names = [h["name"] for h in entry["request"]["headers"]]
        assert "Authorization" in header_names


class TestHarRoundtrip:
    def test_har_to_bundle_to_har(self, tmp_path):
        """Test that HAR -> Bundle -> HAR preserves core data."""
        original_har = _make_sample_har()
        har_path = tmp_path / "test.har"
        har_path.write_text(json.dumps(original_har))

        # HAR -> Bundle
        bundle = har_to_bundle(har_path)

        # Bundle -> HAR
        exported_har = bundle_to_har(bundle)

        # Compare core data
        orig_entries = original_har["log"]["entries"]
        exp_entries = exported_har["log"]["entries"]

        assert len(orig_entries) == len(exp_entries)
        for orig, exp in zip(orig_entries, exp_entries):
            assert orig["request"]["method"] == exp["request"]["method"]
            assert orig["request"]["url"] == exp["request"]["url"]
            assert orig["response"]["status"] == exp["response"]["status"]

    def test_bundle_to_har_to_bundle(self, sample_bundle):
        """Test that Bundle -> HAR -> Bundle preserves core data."""
        # Bundle -> HAR
        har = bundle_to_har(sample_bundle)

        # HAR -> Bundle (write to temp file)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".har", mode="w", delete=False) as f:
            json.dump(har, f)
            har_path = Path(f.name)

        bundle = har_to_bundle(har_path)
        har_path.unlink()

        assert len(bundle.traces) == len(sample_bundle.traces)
        for orig, loaded in zip(sample_bundle.traces, bundle.traces):
            assert orig.meta.request.method == loaded.meta.request.method
            assert orig.meta.request.url == loaded.meta.request.url
            assert orig.meta.response.status == loaded.meta.response.status

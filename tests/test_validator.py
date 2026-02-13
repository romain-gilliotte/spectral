"""Tests for the mechanical validator."""

import json

from cli.analyze.validator import (
    ValidationError,
    _check_auth_coherence,
    _check_coverage,
    _check_pattern_match,
    _check_schema_consistency,
    _pattern_to_regex,
    validate_spec,
)
from cli.formats.api_spec import (
    ApiSpec,
    AuthInfo,
    EndpointSpec,
    Protocols,
    RequestSpec,
    ResponseSpec,
    RestProtocol,
)
from cli.formats.capture_bundle import Header
from tests.conftest import make_trace


class TestPatternToRegex:
    def test_simple_path(self):
        regex = _pattern_to_regex("/api/users")
        assert regex.match("/api/users")
        assert not regex.match("/api/users/123")

    def test_path_with_param(self):
        regex = _pattern_to_regex("/api/users/{user_id}")
        assert regex.match("/api/users/123")
        assert regex.match("/api/users/abc-def")
        assert not regex.match("/api/users/123/orders")

    def test_path_with_multiple_params(self):
        regex = _pattern_to_regex("/api/users/{user_id}/orders/{order_id}")
        assert regex.match("/api/users/123/orders/456")
        assert not regex.match("/api/users/123/orders")

    def test_root_path(self):
        regex = _pattern_to_regex("/")
        assert regex.match("/")
        assert not regex.match("/api")


class TestCheckCoverage:
    def test_all_traces_covered(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000),
            make_trace("t_0002", "POST", "https://api.example.com/users", 201, 2000),
        ]
        endpoints = [
            EndpointSpec(
                id="get_users",
                path="/users",
                method="GET",
                source_trace_refs=["t_0001"],
            ),
            EndpointSpec(
                id="post_users",
                path="/users",
                method="POST",
                source_trace_refs=["t_0002"],
            ),
        ]
        errors = _check_coverage(endpoints, traces)
        assert len(errors) == 0

    def test_uncovered_trace(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/orphan", 200, 2000),
        ]
        endpoints = [
            EndpointSpec(
                id="get_users",
                path="/users",
                method="GET",
                source_trace_refs=["t_0001"],
            ),
        ]
        errors = _check_coverage(endpoints, traces)
        assert len(errors) == 1
        assert errors[0].type == "uncovered_trace"
        assert errors[0].trace_id == "t_0002"


class TestCheckPatternMatch:
    def test_matching_pattern(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users/123", 200, 1000),
            make_trace("t_0002", "GET", "https://api.example.com/users/456", 200, 2000),
        ]
        endpoints = [
            EndpointSpec(
                id="get_user",
                path="/users/{user_id}",
                method="GET",
                source_trace_refs=["t_0001", "t_0002"],
            ),
        ]
        errors = _check_pattern_match(endpoints, traces)
        assert len(errors) == 0

    def test_mismatched_pattern(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users/123/orders", 200, 1000),
        ]
        endpoints = [
            EndpointSpec(
                id="get_user",
                path="/users/{user_id}",
                method="GET",
                source_trace_refs=["t_0001"],
            ),
        ]
        errors = _check_pattern_match(endpoints, traces)
        assert len(errors) == 1
        assert errors[0].type == "pattern_mismatch"


class TestCheckSchemaConsistency:
    def test_consistent_schema(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/users", 200, 1000,
                response_body=json.dumps({"name": "Alice", "age": 30}).encode(),
            ),
        ]
        endpoints = [
            EndpointSpec(
                id="get_users",
                path="/users",
                method="GET",
                source_trace_refs=["t_0001"],
                responses=[
                    ResponseSpec(
                        status=200,
                        schema={
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "age": {"type": "integer"},
                            },
                            "required": ["name", "age"],
                        },
                    ),
                ],
            ),
        ]
        errors = _check_schema_consistency(endpoints, traces)
        assert len(errors) == 0

    def test_missing_required_key(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/users", 200, 1000,
                response_body=json.dumps({"name": "Alice"}).encode(),
            ),
        ]
        endpoints = [
            EndpointSpec(
                id="get_users",
                path="/users",
                method="GET",
                source_trace_refs=["t_0001"],
                responses=[
                    ResponseSpec(
                        status=200,
                        schema={
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "age": {"type": "integer"},
                            },
                            "required": ["name", "age"],
                        },
                    ),
                ],
            ),
        ]
        errors = _check_schema_consistency(endpoints, traces)
        assert any(e.type == "schema_mismatch" and "missing required" in e.message.lower() for e in errors)

    def test_extra_keys_in_body(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/users", 200, 1000,
                response_body=json.dumps({"name": "Alice", "age": 30, "email": "a@b.com"}).encode(),
            ),
        ]
        endpoints = [
            EndpointSpec(
                id="get_users",
                path="/users",
                method="GET",
                source_trace_refs=["t_0001"],
                responses=[
                    ResponseSpec(
                        status=200,
                        schema={
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "age": {"type": "integer"},
                            },
                            "required": ["name", "age"],
                        },
                    ),
                ],
            ),
        ]
        errors = _check_schema_consistency(endpoints, traces)
        assert any(e.type == "schema_mismatch" and "not in schema" in e.message.lower() for e in errors)


class TestCheckAuthCoherence:
    def test_auth_detected(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/users", 200, 1000,
                request_headers=[Header(name="Authorization", value="Bearer token123")],
            ),
        ]
        spec = ApiSpec(auth=AuthInfo(type="bearer_token"))
        errors = _check_auth_coherence(spec, traces)
        assert len(errors) == 0

    def test_auth_missing(self):
        traces = [
            make_trace(
                "t_0001", "GET", "https://api.example.com/users", 200, 1000,
                request_headers=[Header(name="Authorization", value="Bearer token123")],
            ),
        ]
        spec = ApiSpec(auth=AuthInfo(type=""))
        errors = _check_auth_coherence(spec, traces)
        assert len(errors) == 1
        assert errors[0].type == "auth_mismatch"

    def test_no_auth_no_error(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000),
        ]
        spec = ApiSpec(auth=AuthInfo(type=""))
        errors = _check_auth_coherence(spec, traces)
        assert len(errors) == 0


class TestValidateSpec:
    def test_valid_spec(self):
        traces = [
            make_trace("t_0001", "GET", "https://api.example.com/users", 200, 1000),
        ]
        spec = ApiSpec(
            protocols=Protocols(
                rest=RestProtocol(
                    base_url="https://api.example.com",
                    endpoints=[
                        EndpointSpec(
                            id="get_users",
                            path="/users",
                            method="GET",
                            source_trace_refs=["t_0001"],
                        ),
                    ],
                ),
            ),
        )
        errors = validate_spec(spec, traces)
        assert len(errors) == 0

    def test_to_dict(self):
        error = ValidationError(
            type="uncovered_trace",
            message="Trace t_0001 not covered",
            trace_id="t_0001",
            details={"url": "https://example.com"},
        )
        d = error.to_dict()
        assert d["type"] == "uncovered_trace"
        assert d["trace_id"] == "t_0001"
        assert "url" in d["details"]

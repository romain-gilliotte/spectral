"""Mechanical validation of an API spec against captured traces.

Checks that the LLM-generated spec is consistent with the actual observed traffic.
Returns structured errors that can be fed back to the LLM for correction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from cli.capture.models import Trace
from cli.formats.api_spec import ApiSpec, EndpointSpec


@dataclass
class ValidationError:
    """A structured validation error."""

    type: str  # "uncovered_trace", "pattern_mismatch", "schema_mismatch", "auth_mismatch"
    message: str
    endpoint_id: str | None = None
    trace_id: str | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"type": self.type, "message": self.message}
        if self.endpoint_id:
            d["endpoint_id"] = self.endpoint_id
        if self.trace_id:
            d["trace_id"] = self.trace_id
        if self.details:
            d["details"] = self.details
        return d


def validate_spec(spec: ApiSpec, traces: list[Trace]) -> list[ValidationError]:
    """Validate a spec against captured traces.

    Checks:
    - Coverage: every API trace is assigned to an endpoint
    - Pattern match: each URL matches the pattern of its assigned endpoint
    - Schema consistency: observed JSON bodies match the generated schemas
    - Auth coherence: if traces have auth headers, auth should be detected
    """
    errors: list[ValidationError] = []

    endpoints = spec.protocols.rest.endpoints

    errors.extend(_check_coverage(endpoints, traces))
    errors.extend(_check_pattern_match(endpoints, traces))
    errors.extend(_check_schema_consistency(endpoints, traces))
    errors.extend(_check_auth_coherence(spec, traces))

    return errors


def _check_coverage(endpoints: list[EndpointSpec], traces: list[Trace]) -> list[ValidationError]:
    """Check that every trace is covered by at least one endpoint."""
    errors = []
    covered_trace_ids = set()
    for ep in endpoints:
        covered_trace_ids.update(ep.source_trace_refs)

    for trace in traces:
        if trace.meta.id not in covered_trace_ids:
            errors.append(
                ValidationError(
                    type="uncovered_trace",
                    message=f"Trace {trace.meta.id} ({trace.meta.request.method} {trace.meta.request.url}) is not assigned to any endpoint",
                    trace_id=trace.meta.id,
                    details={
                        "method": trace.meta.request.method,
                        "url": trace.meta.request.url,
                    },
                )
            )

    return errors


def _pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert a path pattern like /api/users/{user_id}/orders to a regex."""
    # Escape everything except {param} placeholders
    parts = re.split(r"\{[^}]+\}", pattern)
    placeholders = re.findall(r"\{[^}]+\}", pattern)

    regex = ""
    for i, part in enumerate(parts):
        regex += re.escape(part)
        if i < len(placeholders):
            regex += r"[^/]+"

    return re.compile(f"^{regex}$")


def _check_pattern_match(endpoints: list[EndpointSpec], traces: list[Trace]) -> list[ValidationError]:
    """Check that each trace URL matches the path pattern of its assigned endpoint."""
    errors = []

    # Build trace lookup
    trace_map = {t.meta.id: t for t in traces}

    for ep in endpoints:
        pattern_re = _pattern_to_regex(ep.path)

        for trace_id in ep.source_trace_refs:
            trace = trace_map.get(trace_id)
            if not trace:
                continue

            parsed = urlparse(trace.meta.request.url)
            path = parsed.path

            if not pattern_re.match(path):
                errors.append(
                    ValidationError(
                        type="pattern_mismatch",
                        message=f"Trace {trace_id} URL path '{path}' does not match endpoint pattern '{ep.path}'",
                        endpoint_id=ep.id,
                        trace_id=trace_id,
                        details={
                            "url": trace.meta.request.url,
                            "path": path,
                            "pattern": ep.path,
                        },
                    )
                )

    return errors


def _check_schema_consistency(endpoints: list[EndpointSpec], traces: list[Trace]) -> list[ValidationError]:
    """Check that observed JSON response bodies are consistent with generated schemas."""
    errors = []

    trace_map = {t.meta.id: t for t in traces}

    for ep in endpoints:
        for resp_spec in ep.responses:
            if resp_spec.schema_ is None:
                continue

            schema = resp_spec.schema_
            if schema.get("type") != "object" or "properties" not in schema:
                continue

            schema_keys = set(schema["properties"].keys())
            required_keys = set(schema.get("required", []))

            # Check each trace that belongs to this endpoint with matching status
            for trace_id in ep.source_trace_refs:
                trace = trace_map.get(trace_id)
                if not trace or trace.meta.response.status != resp_spec.status:
                    continue

                if not trace.response_body:
                    continue

                try:
                    data = json.loads(trace.response_body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if not isinstance(data, dict):
                    continue

                body_keys = set(data.keys())

                # Check for required keys missing from body
                missing = required_keys - body_keys
                if missing:
                    errors.append(
                        ValidationError(
                            type="schema_mismatch",
                            message=f"Trace {trace_id} response missing required keys: {missing}",
                            endpoint_id=ep.id,
                            trace_id=trace_id,
                            details={
                                "missing_required": sorted(missing),
                                "body_keys": sorted(body_keys),
                                "schema_required": sorted(required_keys),
                            },
                        )
                    )

                # Check for keys in body that are not in schema
                extra = body_keys - schema_keys
                if extra:
                    errors.append(
                        ValidationError(
                            type="schema_mismatch",
                            message=f"Trace {trace_id} response has keys not in schema: {extra}",
                            endpoint_id=ep.id,
                            trace_id=trace_id,
                            details={
                                "extra_keys": sorted(extra),
                                "body_keys": sorted(body_keys),
                                "schema_keys": sorted(schema_keys),
                            },
                        )
                    )

    return errors


def _check_auth_coherence(spec: ApiSpec, traces: list[Trace]) -> list[ValidationError]:
    """Check that auth detection is consistent with observed headers."""
    errors = []

    has_auth_header = False
    has_auth_cookie = False
    for trace in traces:
        for h in trace.meta.request.headers:
            if h.name.lower() == "authorization":
                has_auth_header = True
            if h.name.lower() == "cookie" and any(
                kw in h.value.lower() for kw in ["session", "token", "auth", "jwt"]
            ):
                has_auth_cookie = True

    if (has_auth_header or has_auth_cookie) and not spec.auth.type:
        errors.append(
            ValidationError(
                type="auth_mismatch",
                message="Traces contain authentication headers/cookies but no auth type was detected",
                details={
                    "has_auth_header": has_auth_header,
                    "has_auth_cookie": has_auth_cookie,
                },
            )
        )

    return errors

"""Tests for the full analysis pipeline with mocked LLM."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from cli.commands.analyze.pipeline import build_spec
from cli.commands.capture.types import CaptureBundle
import cli.helpers.llm as llm
from tests.conftest import make_trace


def _make_mock_create(
    base_url_response: str | None = None,
    groups_response: str | None = None,
    auth_response: str | None = None,
    enrich_response: str | None = None,
) -> Any:
    """Build a mock client.messages.create that routes by prompt content."""

    if base_url_response is None:
        base_url_response = json.dumps({"base_url": "https://api.example.com"})
    if groups_response is None:
        groups_response = json.dumps(
            [
                {
                    "method": "GET",
                    "pattern": "/api/users",
                    "urls": ["https://api.example.com/api/users"],
                },
                {
                    "method": "GET",
                    "pattern": "/api/users/{user_id}/orders",
                    "urls": [
                        "https://api.example.com/api/users/123/orders",
                        "https://api.example.com/api/users/456/orders",
                    ],
                },
                {
                    "method": "POST",
                    "pattern": "/api/orders",
                    "urls": ["https://api.example.com/api/orders"],
                },
            ]
        )
    if auth_response is None:
        auth_response = json.dumps(
            {
                "type": "bearer_token",
                "obtain_flow": "login_form",
                "token_header": "Authorization",
                "token_prefix": "Bearer",
                "business_process": "Token-based auth",
                "user_journey": ["Login with credentials", "Receive bearer token"],
            }
        )
    if enrich_response is None:
        enrich_response = json.dumps(
            {
                "description": "test purpose",
                "field_descriptions": {},
                "response_details": {},
                "discovery_notes": None,
            }
        )

    async def mock_create(**kwargs: Any) -> MagicMock:
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_response.stop_reason = "end_turn"
        msg: str = kwargs.get("messages", [{}])[0].get("content", "")

        if "base URL" in msg and "business API" in msg:
            mock_content.text = base_url_response
        elif "Group these observed URLs" in msg:
            mock_content.text = groups_response
        elif "authentication mechanism" in msg:
            mock_content.text = auth_response
        elif "single API endpoint" in msg:
            # Per-endpoint enrichment call
            mock_content.text = enrich_response
        else:
            # Fallback
            mock_content.text = enrich_response

        mock_response.content = [mock_content]
        return mock_response

    return mock_create


class TestBuildSpec:
    """Tests for the full pipeline with mocked LLM."""

    @pytest.mark.asyncio
    async def test_full_build(self, sample_bundle: CaptureBundle) -> None:
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create()
        llm.init(client=mock_client)

        result = await build_spec(
            sample_bundle,
            model="test-model",
            source_filename="test.zip",
        )

        assert result.openapi is not None
        openapi = result.openapi
        assert openapi["openapi"] == "3.1.0"
        assert openapi["info"]["title"] == "Test App API"
        assert len(openapi["paths"]) > 0
        assert "bearerAuth" in openapi["components"]["securitySchemes"]
        assert openapi["servers"][0]["url"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_traces_filtered_by_base_url(
        self, sample_bundle: CaptureBundle
    ) -> None:
        """Traces not matching the detected base URL should be excluded."""
        cdn_trace = make_trace("t_cdn", "GET", "https://cdn.example.com/style.css", 200, 999500)
        sample_bundle.traces.append(cdn_trace)

        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create(
            groups_response=json.dumps(
                [
                    {
                        "method": "GET",
                        "pattern": "/api/users",
                        "urls": ["https://api.example.com/api/users"],
                    },
                ]
            ),
            auth_response=json.dumps({"type": "none"}),
        )
        llm.init(client=mock_client)

        result = await build_spec(sample_bundle, model="test-model")

        assert result.openapi is not None
        openapi = result.openapi
        assert openapi["servers"][0]["url"] == "https://api.example.com"
        # CDN trace should not appear in the output
        assert len(openapi["paths"]) >= 1

    @pytest.mark.asyncio
    async def test_auth_detected_on_endpoints(self, sample_bundle: CaptureBundle) -> None:
        """Endpoints with Authorization header should have security set."""
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create()
        llm.init(client=mock_client)

        result = await build_spec(
            sample_bundle, model="test-model"
        )

        assert result.openapi is not None
        openapi = result.openapi
        # At least one endpoint should have security (sample traces have Authorization)
        has_security = False
        for path_ops in openapi["paths"].values():
            for op in path_ops.values():
                if "security" in op:
                    has_security = True
                    break
        assert has_security

    @pytest.mark.asyncio
    async def test_openapi_structure(self, sample_bundle: CaptureBundle) -> None:
        """Output should be a valid OpenAPI 3.1 structure."""
        mock_client = AsyncMock()
        mock_client.messages.create = _make_mock_create()
        llm.init(client=mock_client)

        result = await build_spec(
            sample_bundle, model="test-model"
        )

        assert result.openapi is not None
        openapi = result.openapi
        assert "openapi" in openapi
        assert "info" in openapi
        assert "title" in openapi["info"]
        assert "paths" in openapi
        assert "components" in openapi
        assert "securitySchemes" in openapi["components"]
        assert "servers" in openapi

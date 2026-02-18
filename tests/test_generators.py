"""Tests for output generators."""

from pathlib import Path

import yaml

from cli.formats.api_spec import (
    ApiSpec,
    AuthInfo,
    BusinessContext,
    EndpointSpec,
    LoginEndpointConfig,
    ParameterSpec,
    Protocols,
    RefreshEndpointConfig,
    RequestSpec,
    ResponseSpec,
    RestProtocol,
    UiTrigger,
    WebSocketProtocol,
    WsConnectionSpec,
    WsMessageSpec,
)
from cli.generate.curl_scripts import (
    build_all_curl_script,
    build_curl_script,
    generate_curl_scripts,
)
from cli.generate.markdown_docs import (
    build_auth_markdown,
    build_endpoint_markdown,
    build_index_markdown,
    generate_markdown_docs,
)
from cli.generate.mcp_server import build_mcp_server, generate_mcp_server
from cli.generate.openapi import build_openapi_dict, generate_openapi
from cli.generate.python_client import build_python_client, generate_python_client


def _make_sample_spec() -> ApiSpec:
    """Create a sample API spec for generator testing."""
    return ApiSpec(
        name="Pet Store API",
        discovery_date="2026-02-13T15:30:00Z",
        business_context=BusinessContext(
            domain="E-commerce", description="Pet store management API"
        ),
        auth=AuthInfo(
            type="bearer_token", token_header="Authorization", token_prefix="Bearer"
        ),
        protocols=Protocols(
            rest=RestProtocol(
                base_url="https://api.petstore.com",
                endpoints=[
                    EndpointSpec(
                        id="get_pets",
                        path="/api/pets",
                        method="GET",
                        business_purpose="List all pets",
                        user_story="As a customer, I want to browse available pets",
                        requires_auth=True,
                        observed_count=5,
                        request=RequestSpec(
                            content_type="application/json",
                            parameters=[
                                ParameterSpec(
                                    name="category",
                                    location="query",
                                    type="string",
                                    example="dogs",
                                ),
                                ParameterSpec(
                                    name="limit",
                                    location="query",
                                    type="integer",
                                    example="10",
                                ),
                            ],
                        ),
                        responses=[
                            ResponseSpec(
                                status=200,
                                content_type="application/json",
                                business_meaning="List of pets returned",
                                schema={"type": "array", "items": {"type": "object"}},
                                example_body=[{"id": 1, "name": "Rex", "type": "dog"}],
                            ),
                        ],
                        ui_triggers=[
                            UiTrigger(
                                action="click",
                                element_selector="nav#pets",
                                element_text="Pets",
                                page_url="/home",
                            ),
                        ],
                    ),
                    EndpointSpec(
                        id="get_pet_by_id",
                        path="/api/pets/{pet_id}",
                        method="GET",
                        business_purpose="Get a specific pet",
                        requires_auth=True,
                        observed_count=3,
                        request=RequestSpec(
                            parameters=[
                                ParameterSpec(
                                    name="pet_id",
                                    location="path",
                                    type="string",
                                    required=True,
                                ),
                            ],
                        ),
                        responses=[
                            ResponseSpec(status=200, content_type="application/json"),
                            ResponseSpec(status=404, business_meaning="Pet not found"),
                        ],
                    ),
                    EndpointSpec(
                        id="post_pets",
                        path="/api/pets",
                        method="POST",
                        business_purpose="Create a new pet",
                        requires_auth=True,
                        observed_count=2,
                        request=RequestSpec(
                            content_type="application/json",
                            parameters=[
                                ParameterSpec(
                                    name="name",
                                    location="body",
                                    type="string",
                                    required=True,
                                    business_meaning="Pet's name",
                                ),
                                ParameterSpec(
                                    name="type",
                                    location="body",
                                    type="string",
                                    required=True,
                                ),
                                ParameterSpec(
                                    name="age",
                                    location="body",
                                    type="integer",
                                    required=False,
                                ),
                            ],
                        ),
                        responses=[
                            ResponseSpec(status=201, content_type="application/json"),
                        ],
                    ),
                ],
            ),
            websocket=WebSocketProtocol(
                connections=[
                    WsConnectionSpec(
                        id="ws_updates",
                        url="wss://api.petstore.com/ws",
                        subprotocol="plain-json",
                        messages=[
                            WsMessageSpec(direction="receive", label="pet_update"),
                        ],
                    ),
                ],
            ),
        ),
        business_glossary={"pet": "An animal available for adoption"},
    )


class TestOpenApiGenerator:
    def test_basic_structure(self):
        spec = _make_sample_spec()
        openapi = build_openapi_dict(spec)

        assert openapi["openapi"] == "3.1.0"
        assert openapi["info"]["title"] == "Pet Store API"
        assert len(openapi["servers"]) == 1
        assert openapi["servers"][0]["url"] == "https://api.petstore.com"

    def test_paths_generated(self):
        spec = _make_sample_spec()
        openapi = build_openapi_dict(spec)

        assert "/api/pets" in openapi["paths"]
        assert "/api/pets/{pet_id}" in openapi["paths"]
        assert "get" in openapi["paths"]["/api/pets"]
        assert "post" in openapi["paths"]["/api/pets"]

    def test_security_scheme(self):
        spec = _make_sample_spec()
        openapi = build_openapi_dict(spec)

        assert "bearerAuth" in openapi["components"]["securitySchemes"]

    def test_parameters_on_get(self):
        spec = _make_sample_spec()
        openapi = build_openapi_dict(spec)

        get_pets = openapi["paths"]["/api/pets"]["get"]
        assert "parameters" in get_pets
        param_names = [p["name"] for p in get_pets["parameters"]]
        assert "category" in param_names
        assert "limit" in param_names

    def test_request_body_on_post(self):
        spec = _make_sample_spec()
        openapi = build_openapi_dict(spec)

        post_pets = openapi["paths"]["/api/pets"]["post"]
        assert "requestBody" in post_pets
        body = post_pets["requestBody"]
        assert "application/json" in body["content"]
        schema = body["content"]["application/json"]["schema"]
        assert "name" in schema["properties"]
        assert "name" in schema["required"]

    def test_path_parameters(self):
        spec = _make_sample_spec()
        openapi = build_openapi_dict(spec)

        get_pet = openapi["paths"]["/api/pets/{pet_id}"]["get"]
        path_params = [p for p in get_pet.get("parameters", []) if p["in"] == "path"]
        assert len(path_params) == 1
        assert path_params[0]["name"] == "pet_id"

    def test_response_codes(self):
        spec = _make_sample_spec()
        openapi = build_openapi_dict(spec)

        get_pet = openapi["paths"]["/api/pets/{pet_id}"]["get"]
        assert "200" in get_pet["responses"]
        assert "404" in get_pet["responses"]

    def test_write_to_file(self, tmp_path: Path) -> None:
        spec = _make_sample_spec()
        out = tmp_path / "openapi.yaml"
        generate_openapi(spec, out)

        assert out.exists()
        loaded = yaml.safe_load(out.read_text())
        assert loaded["openapi"] == "3.1.0"

    def test_security_on_protected_endpoints(self):
        spec = _make_sample_spec()
        openapi = build_openapi_dict(spec)

        get_pets = openapi["paths"]["/api/pets"]["get"]
        assert "security" in get_pets
        assert {"bearerAuth": []} in get_pets["security"]


class TestPythonClientGenerator:
    def test_class_name(self):
        spec = _make_sample_spec()
        code = build_python_client(spec)
        assert "class PetStoreApiClient:" in code

    def test_methods_generated(self):
        spec = _make_sample_spec()
        code = build_python_client(spec)
        assert "def get_pets(" in code
        assert "def get_pet_by_id(" in code
        assert "def post_pets(" in code

    def test_auth_header(self):
        spec = _make_sample_spec()
        code = build_python_client(spec)
        assert "Bearer" in code

    def test_path_param_in_method(self):
        spec = _make_sample_spec()
        code = build_python_client(spec)
        # get_pet_by_id should take pet_id as parameter
        assert "pet_id: str" in code

    def test_body_params_in_post(self):
        spec = _make_sample_spec()
        code = build_python_client(spec)
        assert "name: str" in code
        assert "json_body" in code

    def test_write_to_file(self, tmp_path: Path) -> None:
        spec = _make_sample_spec()
        out = tmp_path / "client.py"
        generate_python_client(spec, out)

        assert out.exists()
        content = out.read_text()
        assert "class PetStoreApiClient:" in content

    def test_docstrings(self):
        spec = _make_sample_spec()
        code = build_python_client(spec)
        assert '"""List all pets"""' in code
        assert '"""Get a specific pet"""' in code

    def test_query_params(self):
        spec = _make_sample_spec()
        code = build_python_client(spec)
        assert "category:" in code
        assert "limit:" in code


class TestMarkdownDocsGenerator:
    def test_index_contains_endpoints(self):
        spec = _make_sample_spec()
        index = build_index_markdown(spec)

        assert "# Pet Store API" in index
        assert "| `GET` | `/api/pets`" in index
        assert "| `POST` | `/api/pets`" in index
        assert "E-commerce" in index

    def test_index_contains_glossary(self):
        spec = _make_sample_spec()
        index = build_index_markdown(spec)
        assert "**pet**:" in index

    def test_index_contains_websocket(self):
        spec = _make_sample_spec()
        index = build_index_markdown(spec)
        assert "wss://api.petstore.com/ws" in index

    def test_endpoint_doc(self):
        spec = _make_sample_spec()
        ep = spec.protocols.rest.endpoints[0]
        doc = build_endpoint_markdown(ep, spec)

        assert "# GET /api/pets" in doc
        assert "List all pets" in doc
        assert "category" in doc
        assert "## Responses" in doc

    def test_auth_doc(self):
        spec = _make_sample_spec()
        doc = build_auth_markdown(spec)
        assert "# Authentication" in doc
        assert "bearer_token" in doc

    def test_write_to_directory(self, tmp_path: Path) -> None:
        spec = _make_sample_spec()
        out = tmp_path / "docs"
        generate_markdown_docs(spec, out)

        assert (out / "index.md").exists()
        assert (out / "get_pets.md").exists()
        assert (out / "post_pets.md").exists()
        assert (out / "authentication.md").exists()


class TestCurlScriptsGenerator:
    def test_basic_curl(self):
        spec = _make_sample_spec()
        ep = spec.protocols.rest.endpoints[0]
        script = build_curl_script(ep, spec)

        assert "curl" in script
        assert "https://api.petstore.com/api/pets" in script
        assert "Bearer" in script

    def test_post_curl_has_body(self):
        spec = _make_sample_spec()
        post_ep = spec.protocols.rest.endpoints[2]
        script = build_curl_script(post_ep, spec)

        assert "-X POST" in script
        assert "-d " in script
        assert "Content-Type" in script

    def test_path_param_replaced(self):
        spec = _make_sample_spec()
        ep = spec.protocols.rest.endpoints[1]  # get_pet_by_id
        script = build_curl_script(ep, spec)
        assert "{pet_id}" not in script

    def test_all_script(self):
        spec = _make_sample_spec()
        script = build_all_curl_script(spec)

        assert "#!/usr/bin/env bash" in script
        assert "TOKEN" in script
        assert "get_pets" in script
        assert "post_pets" in script

    def test_write_to_directory(self, tmp_path: Path) -> None:
        spec = _make_sample_spec()
        out = tmp_path / "scripts"
        generate_curl_scripts(spec, out)

        assert (out / "get_pets.sh").exists()
        assert (out / "post_pets.sh").exists()
        assert (out / "all_requests.sh").exists()

    def test_query_params_in_url(self):
        spec = _make_sample_spec()
        ep = spec.protocols.rest.endpoints[0]
        script = build_curl_script(ep, spec)
        assert "category=" in script


class TestMcpServerGenerator:
    def test_server_code_structure(self):
        spec = _make_sample_spec()
        code = build_mcp_server(spec)

        assert "from mcp.server.fastmcp import FastMCP" in code
        assert 'mcp = FastMCP("Pet Store API")' in code
        assert "@mcp.tool()" in code
        assert 'if __name__ == "__main__":' in code

    def test_tools_generated(self):
        spec = _make_sample_spec()
        code = build_mcp_server(spec)

        assert "def get_pets(" in code
        assert "def get_pet_by_id(" in code
        assert "def post_pets(" in code

    def test_auth_headers(self):
        spec = _make_sample_spec()
        code = build_mcp_server(spec)
        assert "Bearer" in code
        assert "AUTH_TOKEN" in code

    def test_write_to_directory(self, tmp_path: Path) -> None:
        spec = _make_sample_spec()
        out = tmp_path / "mcp-server"
        generate_mcp_server(spec, out)

        assert (out / "server.py").exists()
        assert (out / "requirements.txt").exists()
        assert (out / "README.md").exists()

    def test_requirements(self, tmp_path: Path) -> None:
        spec = _make_sample_spec()
        out = tmp_path / "mcp-server"
        generate_mcp_server(spec, out)

        reqs = (out / "requirements.txt").read_text()
        assert "mcp" in reqs
        assert "requests" in reqs

    def test_readme_lists_tools(self, tmp_path: Path) -> None:
        spec = _make_sample_spec()
        out = tmp_path / "mcp-server"
        generate_mcp_server(spec, out)

        readme = (out / "README.md").read_text()
        assert "get_pets" in readme
        assert "Pet Store API" in readme


def _make_api_key_spec() -> ApiSpec:
    """Create a spec with api_key auth for testing custom auth headers."""
    return ApiSpec(
        name="Key Auth API",
        auth=AuthInfo(type="api_key", token_header="X-API-Key"),
        protocols=Protocols(
            rest=RestProtocol(
                base_url="https://api.example.com",
                endpoints=[
                    EndpointSpec(
                        id="get_data",
                        path="/api/data",
                        method="GET",
                        business_purpose="Get data",
                        requires_auth=True,
                        observed_count=1,
                    ),
                ],
            ),
        ),
    )


class TestApiKeyAuthGenerators:
    def test_openapi_api_key_scheme(self):
        spec = _make_api_key_spec()
        openapi = build_openapi_dict(spec)
        assert "apiKeyAuth" in openapi["components"]["securitySchemes"]
        scheme = openapi["components"]["securitySchemes"]["apiKeyAuth"]
        assert scheme["type"] == "apiKey"
        assert scheme["in"] == "header"
        assert scheme["name"] == "X-API-Key"

    def test_openapi_api_key_on_endpoint(self):
        spec = _make_api_key_spec()
        openapi = build_openapi_dict(spec)
        get_data = openapi["paths"]["/api/data"]["get"]
        assert "security" in get_data
        assert {"apiKeyAuth": []} in get_data["security"]

    def test_python_client_custom_header(self):
        spec = _make_api_key_spec()
        code = build_python_client(spec)
        assert "X-API-Key" in code

    def test_mcp_server_custom_header(self):
        spec = _make_api_key_spec()
        code = build_mcp_server(spec)
        assert "X-API-Key" in code

    def test_curl_custom_header(self):
        spec = _make_api_key_spec()
        ep = spec.protocols.rest.endpoints[0]
        script = build_curl_script(ep, spec)
        assert "X-API-Key" in script

    def test_markdown_login_config(self):
        spec = ApiSpec(
            name="Auth API",
            auth=AuthInfo(
                type="bearer_token",
                token_header="Authorization",
                token_prefix="Bearer",
                login_config=LoginEndpointConfig(
                    url="/auth/login",
                    credential_fields={"email": "email", "password": "password"},
                ),
                refresh_config=RefreshEndpointConfig(
                    url="/auth/refresh",
                    token_field="refresh_token",
                ),
            ),
        )
        doc = build_auth_markdown(spec)
        assert "Login Endpoint" in doc
        assert "/auth/login" in doc
        assert "Refresh Endpoint" in doc
        assert "/auth/refresh" in doc

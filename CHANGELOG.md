# CHANGELOG


## v0.11.0 (2026-03-27)

### Features

- **auth**: Overhaul auth script generation and validation pipeline
  ([`b6deb4a`](https://github.com/spectral-mcp/spectral/commit/b6deb4aca27a0cf4a0a6da3fd50884294f3bc36f))

- Move fix loop from login into analyze: scripts are validated at generation time with a unified
  generate+extract+test retry loop. Login now simply runs the script or directs to re-run analyze. -
  Rename helpers/auth modules to private with curated __init__.py public API, matching helpers/json
  and helpers/llm patterns. - Persist token obtained during analyze (no separate login needed). -
  Cache credential prompts (email/password) across fix iterations; OTP codes are never cached. -
  Switch to questionary for auth prompts (asterisk feedback). - Replace inspect_trace with
  query_traces (jq) for auth analysis. Add response_headers field and non-JSON body fallback to
  query_traces tool. Improve tool docstring with usage examples. - Stop redacting auth headers so
  LLM sees full token structure. - Filter script tracebacks to exclude spectral internals while
  keeping stdlib frames. Move formatting to Jinja filter. - Improve prompts: require trace
  inspection, enforce headless scripts, encourage CookieJar, directive debug() guidance in fix loop.
  - Update shell completions (remove --debug from auth login).


## v0.10.1 (2026-03-27)

### Bug Fixes

- **install**: Point Chrome extension step to Web Store docs
  ([`d179e0b`](https://github.com/spectral-mcp/spectral/commit/d179e0b02976252b918423d5f45984fc5051872f))


## v0.10.0 (2026-03-27)

### Chores

- **deps**: Move apk-mitm-python to spectral-mcp org
  ([`def605f`](https://github.com/spectral-mcp/spectral/commit/def605fda31079a82e218a200d6f16e5a8111c11))

### Features

- **mcp**: Filter out non-JSON traces before analysis
  ([`b3de557`](https://github.com/spectral-mcp/spectral/commit/b3de557f82c5fbee9e8926e60c00c3e892e45525))

Skip traces that don't have a JSON content-type in either request or response headers, reducing
  noise and LLM token usage on binary/HTML traffic.

### Refactoring

- **mcp**: Simplify analysis pipeline into single-pass tool generation
  ([`e57b6c2`](https://github.com/spectral-mcp/spectral/commit/e57b6c22df9d38fe542c77e650b603a2aececfe6))

Remove the separate identify and build-tool steps in favor of a unified analysis pass. Drop
  migrate.py, build_tool.py and identify.py modules, consolidate logic in analyze.py, and update
  prompts to markdown templates. Clean up corresponding tests and mocks.


## v0.9.0 (2026-03-22)

### Bug Fixes

- **android**: Pass missing is_app_bundle option to apk-mitm-python
  ([`6866fb0`](https://github.com/spectral-mcp/spectral/commit/6866fb083d92783d6bd61d08b90c62635e71ee0e))

- **mcp**: Use absolute URLs in tool definitions, fix auth cookie instructions
  ([`5e40c79`](https://github.com/spectral-mcp/spectral/commit/5e40c792bc5e3aa24b2faffaebde7638835ab734))

- Remove urljoin-based URL relativization in analyze.py — LLM now produces absolute URLs directly
  from captured traces - Add Field(pattern=r"^https?://") on ToolRequest.url to enforce absolute
  URLs at the schema level - Update mcp-build-tool-instructions.j2 to request absolute URLs - Update
  auth-instructions.j2 to explicitly document cookie-based auth: cookies must be returned as a
  Cookie header, not in a cookie jar - Update all test fixtures to use absolute URLs

### Features

- **android**: Replace homegrown APK patching with apk-mitm-python
  ([`9a52b38`](https://github.com/spectral-mcp/spectral/commit/9a52b388532c2d52f8ba90173c126d1816dccd64))

Delegate all APK patching to apk-mitm-python which handles network security config, smali-level cert
  pinning bypass (javax, OkHttp), and certificate embedding — instead of only modifying the XML
  config.

- Add apk-mitm-python git dependency - Rewrite patch.py as a thin wrapper around apk-mitm-python -
  Pull split APKs as .apks zip bundles instead of directories - Install handles .apks bundles
  transparently - Remove cert command (cert is now embedded in patched APKs) - Remove homegrown
  apktool/uber-signer/bootstrap wrappers - Simplify replace flow (no more split vs single branching)

- **capture**: Add domain exclusion (-e/--exclude) to proxy command
  ([`e4834d4`](https://github.com/spectral-mcp/spectral/commit/e4834d46fe4e97dede9d2afe9e4da5a6f85ca5d0))

Leverage mitmproxy's native ignore_hosts to let users exclude domains from MITM interception (e.g.
  Google SSO domains that reject our CA).

- **capture**: Add WireGuard VPN mode to MITM proxy
  ([`5d82a00`](https://github.com/spectral-mcp/spectral/commit/5d82a005399d7ce6c580284f7c230f22b851019f))

Add --wireguard/--wg flag to `spectral capture proxy` for capturing traffic from apps that bypass
  the system proxy (e.g. Flutter apps).

- Add `mode` and `block_quic` params to `run_mitmproxy()` - Generate/reuse WireGuard keys stored in
  $SPECTRAL_HOME/wireguard.conf - Display client config with optional QR code (segno dependency) -
  Block QUIC (UDP:443) in non-regular modes to force HTTP/2 fallback - Update shell completions for
  --wireguard/--wg - Add tests for WireGuard config generation, display, and key reuse

- **capture**: Auto-detect foreground Android app and per-app capture storage
  ([`055ded8`](https://github.com/spectral-mcp/spectral/commit/055ded82769179eb6a65ad22ce5664e211454b03))

- Add --autodetect-app flag to proxy command: polls ADB for the foreground app and groups captured
  traces into separate bundles per detected package (replaces -a when used) - Introduce AppProvider
  abstraction (FixedAppProvider / ForegroundAppPoller) and add app_package field to TraceMeta -
  Extract WireGuard helpers into _wireguard.py module (shared by proxy and discover) and add
  --wireguard flag to discover command - Simplify QUIC blocking: use mitmproxy native http3 option
  instead of custom _BlockQuicAddon - Remove WebSocket capture support from CaptureAddon - Add
  adb.get_foreground_package() to query the resumed activity - Update shell completions, tests, and
  return types accordingly


## v0.8.0 (2026-03-19)

### Features

- **android**: Add uninstall and replace commands
  ([`25d2c55`](https://github.com/spectral-mcp/spectral/commit/25d2c5572c54dce182617754fa5a02238e4b7ca0))

Add `spectral android uninstall <package>` to remove a package from a connected device, and
  `spectral android replace <package>` to chain pull → patch → uninstall → install in a temporary
  directory.


## v0.7.0 (2026-03-19)

### Bug Fixes

- **debug**: Write tool results and improve auth prompt
  ([`74429d0`](https://github.com/spectral-mcp/spectral/commit/74429d0c935d5b61e06d6fe191a37193a2d1b27f))

Debug: - Fix tool results never appearing (calls and returns were in different batches, matching by
  tool_call_id always missed) - Write ToolReturnPart explicitly with args summary in header - Record
  on every graph node for incremental output - Add tools summary header at top of debug files

Auth prompt: - Inspect only auth-related traces + 1-2 API calls, not everything - Allow full stdlib
  (not just a hardcoded list), forbid filesystem - No module-level side effects, no extraneous
  requests - No commentary in output, just the code block

- **mcp**: Strip response headers from MCP tool output
  ([`cc5de8e`](https://github.com/spectral-mcp/spectral/commit/cc5de8eafc79f9296f8eb46f75825bbb25533dbc))

Response headers are noise that consumes tokens without providing useful information to the AI
  agent. The status code and body are sufficient.

- **types**: Resolve pyright errors in search, ui, and test files
  ([`d7ddd87`](https://github.com/spectral-mcp/spectral/commit/d7ddd870f585e8c648940db64380cc4e900624a2))

### Chores

- **scripts**: Add seed script for demo-api test app
  ([`946b487`](https://github.com/spectral-mcp/spectral/commit/946b48722485cfb2722807576ec9b32a0ef1b2da))

Creates scripts/seed_demo_app.py that populates managed storage with a realistic e-commerce capture
  bundle (7 REST traces + UI contexts) for testing the analysis pipeline without real captures or
  LLM costs.

### Features

- **catalog**: Support auth script in publish and install flows
  ([`2c7ee2c`](https://github.com/spectral-mcp/spectral/commit/2c7ee2c5920d7b96ef75f61d2886fe66d3d00d29))

- **storage**: Strict app name validation to prevent path traversal and naming conflicts
  ([`fc37f9f`](https://github.com/spectral-mcp/spectral/commit/fc37f9f38207c119043385ce5900c070403edb33))

Centralizes app name validation in storage.py with APP_NAME_RE (lowercase alphanum + single
  hyphens). Validates in app_dir() and ensure_app() to cover all read/write paths. Adds interactive
  validation loop in proxy command and validates extension native messaging input.

### Refactoring

- Remove unnecessary async/await from analysis pipeline
  ([`2087ae3`](https://github.com/spectral-mcp/spectral/commit/2087ae36e78ea672382eaa6ea60734ccf4c92dd3))

Replace agent.iter() with agent.run_sync() wrapped in asyncio.run() inside Conversation._run(),
  making ask_text/ask_json synchronous. Remove async/await from all callers bottom-up (17 source
  files, 9 test files). Replace asyncio.gather with sequential loops in enrichment. Remove
  asyncio.run() wrappers from CLI entry points. MCP server stays async as required by the mcp
  library.

- **auth**: Split auth_runtime into focused modules and rewrite tests
  ([`f1166aa`](https://github.com/spectral-mcp/spectral/commit/f1166aa628ef5af680ac70690593a3b1a947bc0d))

Split cli/helpers/auth_runtime.py into cli/helpers/auth/ package: - errors.py: AuthError,
  AuthScriptInvalid, AuthScriptError, AuthScriptNotFound - generation.py: extract_script,
  get_auth_instructions (with exec validation) - runtime.py: call_auth_module with output capture
  via partial - usage.py: get_auth, acquire_auth, refresh_auth cascade

Simplify auth analyze/login to use build_timeline instead of build_shared_context (removes base URL
  detection from auth pipeline). Unify fix templates into a single auth-fix.j2. Limit fix loop to 5
  attempts. Restore refresh failure warning in get_auth. Move imports to top level per project
  conventions.

Rewrite all auth tests as focused unit tests with proper mocking.


## v0.6.1 (2026-03-17)

### Bug Fixes

- Omit system_prompt when empty to avoid Anthropic API rejection
  ([#4](https://github.com/spectral-mcp/spectral/pull/4),
  [`a2bafff`](https://github.com/spectral-mcp/spectral/commit/a2bafffe00b65f432986f6ac8107d2c6398d4bda))

Anthropic's API rejects messages with `{'role': 'system', 'content': ''}`. When no system prompt is
  provided, the code was passing `system_prompt=""` to PydanticAI Agent, which translated to an
  empty system message.

This caused all LLM calls without an explicit system prompt (e.g. `detect_base_urls`) to fail with a
  400 error when routed through LiteLLM to any Anthropic model (claude-opus, claude-sonnet,
  claude-haiku).

The fix omits the `system_prompt` kwarg entirely when there is no system prompt, so PydanticAI never
  generates a system message.

Co-authored-by: Charles-Henri ROBICHE <charleshenri.robiche@loreal.com>

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Documentation

- Update demo gif
  ([`420e014`](https://github.com/spectral-mcp/spectral/commit/420e014df6ad06f703919ff3f0dc45398739349e))


## v0.6.0 (2026-03-16)

### Documentation

- Update install script and CLAUDE.md for multi-provider LLM support
  ([`467fe86`](https://github.com/spectral-mcp/spectral/commit/467fe86f1494c0daa51e6d6f52c0b19bc333e563))

- **readme**: Fix GitHub links and update pitch
  ([`809e579`](https://github.com/spectral-mcp/spectral/commit/809e5792b3640cbb60ad5d7a1efad40200dbd477))

- Update all GitHub URLs from romain-gilliotte/spectral to spectral-mcp/spectral - Update
  documentation links to new URL - Refresh tagline copy

- **roadmap**: Add auth extract with refresh token discovery idea
  ([`f54a52f`](https://github.com/spectral-mcp/spectral/commit/f54a52f4f501fdc4ee82a913d203c601d75f42f6))

### Features

- Add multi-provider LLM support (OpenRouter, OpenAI, Ollama)
  ([`25c28d0`](https://github.com/spectral-mcp/spectral/commit/25c28d096f16e942059ef62da21fdbba9a557a18))

Support multiple LLM providers beyond Anthropic. Add provider selection in `spectral config`, model
  browsing for OpenRouter, and a minimal public API for the llm module (current_model,
  create_config_interactive).


## v0.5.0 (2026-03-15)

### Chores

- Disable per-call stats recording and default extension ID to store
  ([`d28b563`](https://github.com/spectral-mcp/spectral/commit/d28b563e6fb4a9e27343071b59e1d4722c276e96))

- Disable stats recording in MCP server (too heavy per-call, will batch later) - Disable stats
  reporting in catalog search - Default --extension-id to published Chrome Web Store ID - Show
  Chrome Web Store URL after native host install

### Features

- Rename CLI command 'spectral catalog' to 'spectral community'
  ([`b33f21a`](https://github.com/spectral-mcp/spectral/commit/b33f21a476d838c2191b3bfdc43433a31b82728d))


## v0.4.0 (2026-03-15)

### Documentation

- Add PyPI, Python, CI and license badges to README
  ([`556044d`](https://github.com/spectral-mcp/spectral/commit/556044d2e55650975ed2924813b6b900d65a7322))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- **catalog**: Add community tool catalog with login, publish, search, and install
  ([`c31e965`](https://github.com/spectral-mcp/spectral/commit/c31e96502202319cc54d190fe4baeed46225aee8))

Introduces the catalog subsystem for sharing and discovering MCP tools: - GitHub Device Flow
  authentication (login/logout) - Publish tools to the catalog backend with PR-based review workflow
  - Search the catalog and display results with usage stats - Install tool collections from GitHub -
  Track per-tool execution stats (call count, success rate, latency) - Shell completions for all new
  commands

### Refactoring

- **ci**: Use native semantic-release GitHub Actions outputs
  ([`b067a96`](https://github.com/spectral-mcp/spectral/commit/b067a9608f0903e9b4dd234ac1578363f00f11cd))

python-semantic-release v9 writes released/tag outputs to $GITHUB_OUTPUT natively, removing the need
  for manual tag comparison.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.3.1 (2026-03-12)

### Bug Fixes

- **ci**: Detect no-op releases by comparing tags before and after
  ([`0098a78`](https://github.com/spectral-mcp/spectral/commit/0098a783a79e0e57eb619bf18b3cb5e33c29c177))

semantic-release --print-tag outputs the current version even when no release is needed, causing the
  publish job to re-upload an existing version to PyPI (400 Bad Request). Compare git tags
  before/after to reliably detect whether a new release was actually created.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Chores

- Remove GitHub Pages docs, mkdocs config, and demo assets
  ([`73294dd`](https://github.com/spectral-mcp/spectral/commit/73294dd20d706562f18c5f487c5d2f865180baf9))

Documentation is now hosted on https://www.getspectral.sh/

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Documentation

- Update README with landing page links and tagline
  ([`6a56475`](https://github.com/spectral-mcp/spectral/commit/6a5647527a4b4a62e99e6e9d58ee9914f63c137a))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.3.0 (2026-03-12)

### Bug Fixes

- **capture**: Filter out OPTIONS requests in extension and proxy
  ([`96e8650`](https://github.com/spectral-mcp/spectral/commit/96e86500e1eb7f31f33ce22d2831c68ee66c9010))

CORS preflight requests carry no business semantics and add noise to the LLM timeline. Drop them
  early in both capture sources.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **ci**: Run semantic-release on runner instead of Docker container
  ([`a0afba6`](https://github.com/spectral-mcp/spectral/commit/a0afba69137c896b7af2709c26a3145795a73aa7))

The Docker-based GitHub Action didn't have access to uv, causing build_command to fail with exit
  code 127. Install python-semantic-release as a dev dependency and run it directly on the runner
  where uv is available.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **mcp**: Add resilient tool loading and migration command
  ([`95556b2`](https://github.com/spectral-mcp/spectral/commit/95556b2e4f96ac592f64f6c6d6409e7ef64eb588))

list_tools() now skips invalid tool files with a warning instead of crashing. New `spectral mcp
  migrate` command fixes stale on-disk tools (path→url, unused params) and old app.json
  (base_url→base_urls).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **mcp**: Reject tool definitions with unused parameters
  ([`faab31d`](https://github.com/spectral-mcp/spectral/commit/faab31d680821b89c834de9d4c1a735d294150d3))

The validator only checked that $param references pointed to declared parameters, but not the
  reverse. An LLM could declare parameters never wired into the request template (e.g. Algolia
  single-string body) and validation would silently pass, producing a broken tool at runtime.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Chores

- Update uv.lock automatically during semantic-release
  ([`ddef397`](https://github.com/spectral-mcp/spectral/commit/ddef39760580b0d232184db042c8b48cfee039d3))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update uv.lock version reference
  ([`c5ddb0b`](https://github.com/spectral-mcp/spectral/commit/c5ddb0b4dbdc465fdc3b70d70ffa06fca7855d72))

https://claude.ai/code/session_01RGxzsrBQAQbQPgk59ZoxXh

### Documentation

- Add roadmap and prioritize install script in README
  ([`3d66d17`](https://github.com/spectral-mcp/spectral/commit/3d66d17a45c14d8c08ace7d95def56a0018d8734))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- **auth**: Support body-param authentication for POST-based APIs
  ([`643c900`](https://github.com/spectral-mcp/spectral/commit/643c9000503d72e6d40748e0ffd1a973a1e28dfe))

Add body_params to TokenState so APIs that pass credentials in the request body (Firebase auth,
  POST-based APIs) are injected transparently at runtime alongside header-based auth. End-to-end:
  `auth set -b`, auth scripts, MCP server request builder, prompts, docs, completions.

Also harden LLM tools (decode_base64, decode_jwt, query_traces) to return error strings instead of
  raising exceptions, and allow BuildToolResponse.tool to be None so the pipeline can skip traces
  the LLM deems not useful.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Refactoring

- Make DEFAULT_MODEL private and enforce import conventions
  ([`8171d30`](https://github.com/spectral-mcp/spectral/commit/8171d30187ef0b6d178fdd64a090260aa9b682fe))

Move DEFAULT_MODEL to _DEFAULT_MODEL, access default model via Config.model_fields instead. Expose
  get_or_create_config in llm public API so commands display the actual configured model. Move lazy
  imports to top-level in openapi/analyze_cmd.py per import convention. Update tests to provide
  config before running analyze commands.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Make internal helper functions private with leading underscore
  ([`ba4b393`](https://github.com/spectral-mcp/spectral/commit/ba4b393d6bd3dc973a82f58b327e80fb316d061c))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Prefix internal module functions with _ to clarify public API
  ([`2764dbf`](https://github.com/spectral-mcp/spectral/commit/2764dbf44e4df9c2901446d245bd76af7ef65d09))

Prefix functions that are only used within their own module or package with _ to make each module's
  public interface immediately obvious.

Functions privatized across: - cli/helpers/context.py: _build_timeline_text, _trace_timeline_line,
  _format_size - cli/helpers/llm/_cost.py: _estimate_cost, _record_usage -
  cli/helpers/correlator.py: _find_uncorrelated_traces - cli/commands/mcp/server.py:
  _apply_defaults, _coerce_arguments, _create_server - cli/commands/mcp/request.py: _resolve_url,
  _resolve_query, _resolve_body - cli/commands/openapi/analyze/extraction.py: _pattern_to_regex,
  _match_traces_by_pattern - cli/commands/auth/analyze.py: _get_auth_instructions,
  _generate_auth_script, _validate_script, _extract_script - cli/commands/auth/extract.py:
  _extract_auth_from_traces - cli/commands/capture/proxy.py: _run_proxy_to_storage -
  cli/commands/capture/discover.py: _run_discover - cli/commands/capture/inspect.py:
  _inspect_summary - cli/commands/capture/_mitmproxy.py: _domain_to_regex -
  cli/commands/extension/manifest.py: _wrapper_script_path, _write_wrapper_script,
  _write_wrapper_script_python

Also removes dead code: has_auth_header_or_cookie (never called). Adds private function convention
  to CLAUDE.md style preferences.

https://claude.ai/code/session_01RGxzsrBQAQbQPgk59ZoxXh

- **llm**: Stream debug messages during agent iteration
  ([`c1563a7`](https://github.com/spectral-mcp/spectral/commit/c1563a75d2b7f238ecdda08b65c3ee7c46ed4e09))

Switch from agent.run() to agent.iter() so debug messages are flushed after each tool call instead
  of only at the end.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **mcp**: Support multiple base URLs and store absolute URLs in tools
  ([`67f5776`](https://github.com/spectral-mcp/spectral/commit/67f57762039fc853e6b559722d25fc1fe088cd8f))

Detect multiple business API base URLs per app (e.g. own backend + Algolia, Mapbox). The MCP
  pipeline now iterates over all detected URLs and builds tools for each. Tool requests store
  absolute URLs instead of relative paths, removing the need for base_url lookup at call time. Param
  validation moves into ToolDefinition as a Pydantic model_validator for earlier, cleaner error
  handling.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.2.0 (2026-03-12)

### Bug Fixes

- **debug**: Include system prompt in debug logs
  ([`af93d75`](https://github.com/spectral-mcp/spectral/commit/af93d75882674e65bd2c204cc912b0998ba52f9c))

SystemPromptPart was not handled in record_messages, so debug files never showed the system prompt
  sent to the LLM.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **llm**: Update haiku pricing to claude-haiku-4-5-20251001
  ([`c22cf3e`](https://github.com/spectral-mcp/spectral/commit/c22cf3e2f81bb0821a23ca322d2c0d5328c290d1))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- Replace --model flag and api_key file with config.json
  ([`3af0d56`](https://github.com/spectral-mcp/spectral/commit/3af0d569dcfa26f9c5a24467e83094824a04f290))

Consolidate LLM model selection and API key storage into a single config.json file managed by the
  new `spectral config` command. This removes the --model flag from all 6 analyze commands and
  replaces the plain-text api_key file with structured configuration.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Replace Anthropic SDK with PydanticAI framework
  ([`b26cbe8`](https://github.com/spectral-mcp/spectral/commit/b26cbe8e7e75594ca840610ec5671eba6ef90cdb))

Switch the LLM layer from direct Anthropic client calls to PydanticAI Agent, which handles
  structured output, tool calling, retries, and rate limiting.

Key changes: - Conversation._run creates a PydanticAI Agent per call with output_type - Tools use
  PydanticAI Tool with RunContext[ToolDeps] for stateful tools - DebugSession simplified to single
  record_messages() parsing PydanticAI messages - Remove dead code: extract_json, _utils.py,
  RootModel types, EndpointGroupItem - All tests rewritten with PydanticAI FunctionModel

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Refactoring

- Extract nested functions to module level and remove on_progress callbacks
  ([`9715df6`](https://github.com/spectral-mcp/spectral/commit/9715df65bbb083f12eea0d0622c08d1079a54ca1))

Replace the on_progress callback pattern with direct console.print calls across all analysis
  pipelines (MCP, OpenAPI, GraphQL, auth). Extract nested async helpers (_enrich_type, _enrich_enum,
  _enrich_one, _run, _capture_debug) to module-level functions with explicit parameters.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Move data formatting from Python to Jinja templates
  ([`2594c27`](https://github.com/spectral-mcp/spectral/commit/2594c271c35b2b0b286ff9d378e5120ff5fba5b5))

Register minified, truncate_json, sanitize_headers, headers_to_dict, dict_join, and is_auth_trace as
  Jinja filters. Pass raw data objects to templates instead of pre-formatted strings, letting
  templates own the formatting. Remove format_request_details and prepare_trace_list which are now
  replaced by template logic.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **llm**: Replace ensure_config/load_model with get_or_create_config
  ([`06720aa`](https://github.com/spectral-mcp/spectral/commit/06720aa17df330b8a0d6c8afd80e7448f10aed6b))

Single function returns Config (api_key + model) from disk or interactive prompt. API key is passed
  explicitly to AnthropicProvider instead of going through os.environ. ANTHROPIC_API_KEY env var is
  no longer supported.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **mcp**: Remove wrapper types from pipeline
  ([`406d339`](https://github.com/spectral-mcp/spectral/commit/406d3391e37772db7724bd9df89659088a423504))

Replace IdentifyInput, ToolBuildInput, ToolBuildResult, and McpPipelineResult with direct function
  arguments and a tuple return. Also remove unused skip_enrich parameter from analyze_cmd.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.4 (2026-03-10)

### Chores

- Add source hint in install script and document conventional commits
  ([`74dc719`](https://github.com/spectral-mcp/spectral/commit/74dc7190acc963fa28bb4364ead23f1238f02c0f))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Performance Improvements

- Lazy-import heavy libs to speed up CLI startup
  ([`28bd884`](https://github.com/spectral-mcp/spectral/commit/28bd884ed0d5c338a2c1aec6f1ab77a33dbf6f16))

Move anthropic, mcp, graphql, requests, and jsonschema imports from top-level to inside the
  functions that use them. Reduces `spectral --help` startup from ~1.7s to ~0.6s.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.3 (2026-03-10)

### Bug Fixes

- Checkout release tag in publish job
  ([`4590615`](https://github.com/spectral-mcp/spectral/commit/459061530adf56a4918bd577b1037f2a7121a2b3))

The publish job was checking out the triggering commit instead of the commit created by
  semantic-release, causing it to build the previous version. Checkout the tag output by
  semantic-release instead.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.2 (2026-03-10)

### Bug Fixes

- Use absolute URLs for images in README
  ([`e9cf62f`](https://github.com/spectral-mcp/spectral/commit/e9cf62f41562d195c6efe13e199e4e4cf43d763f))

PyPI cannot resolve relative image paths — use raw.githubusercontent.com URLs so images render on
  both GitHub and PyPI.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.1 (2026-03-10)

### Bug Fixes

- Merge publish job into release workflow
  ([`cbe9b59`](https://github.com/spectral-mcp/spectral/commit/cbe9b596b1a3b32abc1cbb257c6d6331521ae2a7))

The separate publish-pypi.yml workflow never triggered because GitHub Actions anti-loop protection
  ignores events emitted by GITHUB_TOKEN. Merge publishing as a conditional second job in
  release.yml.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>


## v0.1.0 (2026-03-09)

### Bug Fixes

- Add CORS headers to synthetic APQ rejection responses
  ([`dcf391e`](https://github.com/spectral-mcp/spectral/commit/dcf391e2f69aa845d6ddc472c6f024c65998e051))

Cross-origin GraphQL requests (e.g. open.spotify.com → api-partner.spotify.com) were blocked by the
  browser because the synthetic PersistedQueryNotFound response lacked Access-Control-Allow-Origin.
  Now mirrors the request Origin header back in the response along with
  Access-Control-Allow-Credentials.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add pypi environment to publish workflow
  ([`fc9c79e`](https://github.com/spectral-mcp/spectral/commit/fc9c79e271c41be1f0d75eacc55150a0452ce0e5))

Required by PyPI trusted publisher OIDC configuration.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add strict type annotations and fix all linting issues
  ([`2f2b7d6`](https://github.com/spectral-mcp/spectral/commit/2f2b7d66ff7acc281e9c92125bab999d9be8118d))

Add pyright (strict mode) and ruff as dev dependencies. Fix all 800+ pyright strict errors and 46
  ruff errors across 27 source files and 11 test files. Rename 18 internal functions from private to
  public API (remove underscore prefix) since they are used across module boundaries.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add strict type annotations to test files
  ([`9dec4df`](https://github.com/spectral-mcp/spectral/commit/9dec4df22b4348e02d37c9fa64c8ae6f6fd9beca))

Extend pyright strict mode to tests/. Fix 631 errors across 11 test files by adding parameter types,
  return types, and generic type args. Also make a few remaining private members public in client.py
  and tools.py to eliminate reportPrivateUsage suppressions.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Address 6 bugs found during code review
  ([`e7da6ca`](https://github.com/spectral-mcp/spectral/commit/e7da6ca48ec59e68f26418ad5e85ccd023320bd7))

- naming.py: use keyword.iskeyword() instead of incomplete frozenset - mcp/auth.py: log token
  refresh failures to stderr instead of swallowing - extension/manifest.py: shlex.quote() paths in
  wrapper scripts - adb.py: use context manager for socket to prevent leak on exception -
  auth/login.py: mkdir before write_text to avoid crash on missing dir - mcp/request.py: raise
  ValueError on unresolved $param markers

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Apply default parameter values in MCP server
  ([`b6a8d4d`](https://github.com/spectral-mcp/spectral/commit/b6a8d4d937f83f03defa7952cda950d70b6119b1))

When a tool has optional parameters with defaults in the JSON schema, calling the tool without those
  params no longer crashes. Defaults are injected after validation via apply_defaults(), and
  _resolve_value() gracefully omits $param markers referencing absent optional params.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Cache base_url in detect_base_url after LLM detection
  ([`725ef9e`](https://github.com/spectral-mcp/spectral/commit/725ef9ed586007fe8938f5790e22c576a77004b0))

detect_base_url read the cache but never wrote it, leaving caching to callers — 3 of 6 forgot. Move
  the update_app_meta call into detect_base_url itself and remove the now-redundant calls from the
  three callers that had it.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Capture HTTP redirect responses in Chrome Extension
  ([`5eb9ac6`](https://github.com/spectral-mcp/spectral/commit/5eb9ac6a54d6261f2850b50f55ceca2673102d62))

When a 302/301/3xx redirect occurs, Chrome DevTools Protocol reuses the same requestId and fires
  requestWillBeSent again with a redirectResponse field. Previously this was ignored, losing the
  intermediate response (headers, status, Location). Now finalizeRedirectTrace() creates a trace
  from the pending request + redirect response before overwriting the pending entry with the
  follow-up request.

Fixes OAuth flow capture where login domain redirects to app domain.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Coerce MCP string arguments to declared schema types
  ([`1633859`](https://github.com/spectral-mcp/spectral/commit/16338598f6d3ab0600b8e9be9f16abc33cd9aaed))

MCP clients (including LLMs) sometimes send number/integer arguments as strings, causing jsonschema
  validation to reject them. Disable automatic validation, coerce strings to the declared types,
  then validate manually.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Compact_url no longer produces `:///path` on relative URLs
  ([`d61d971`](https://github.com/spectral-mcp/spectral/commit/d61d9717f05a9c7f96ae4c0456295652cdf9a413))

When given a relative path (no scheme/netloc), urlparse returns empty strings, causing the
  reconstructed URL to start with `:///`. Now returns just the compacted path when no scheme is
  present.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Convert Chrome monotonic timestamps to epoch ms
  ([`fbe11c4`](https://github.com/spectral-mcp/spectral/commit/fbe11c4bf42ad8da145d7237048359e8f8e14e42))

DevTools Protocol provides monotonic timestamps (seconds since browser start), while content.js uses
  Date.now() (epoch ms). This made trace and context timestamps incomparable, breaking time-window
  correlation.

Use wallTime from the first requestWillBeSent event to compute an offset, then apply it via
  toEpochMs() to all Chrome timestamps.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Convert glob-style domain patterns to valid regex for mitmproxy
  ([`0175ae0`](https://github.com/spectral-mcp/spectral/commit/0175ae026386f9210c376694b647ac0b459265bd))

Patterns like `*.leboncoin.fr` passed via `-d` caused `re.PatternError` because `*` at position 0 is
  invalid regex. Now converts to `.*\.leboncoin\.fr`.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Detect GraphQL by request body only, support persisted queries and batches
  ([`b02b63c`](https://github.com/spectral-mcp/spectral/commit/b02b63c368f24cb4b21476e754b92930c2330845))

Protocol detection now relies on JSON body inspection rather than URL patterns or query parameters.
  This correctly identifies persisted queries (extensions.persistedQuery without a query field),
  batch requests (JSON arrays), and shorthand queries ({ ... }). GET requests and URL-based
  heuristics are removed as they produced false positives.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Exclude auth endpoints from MCP tool identification
  ([`13e6c01`](https://github.com/spectral-mcp/spectral/commit/13e6c01fd99ee30ed9dbaf8e70099f53424a38be))

Auth endpoints (OAuth token exchanges, login flows, token refresh) should not be exposed as MCP
  tools for security reasons — authentication is handled separately by the auth framework.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Filter traces by HTTP method in _find_traces_for_group
  ([`5074e8b`](https://github.com/spectral-mcp/spectral/commit/5074e8ba21cbf812aca2c86409ae8c11c23b08c1))

When GET and PUT share the same URL (e.g. /api/project/{id}), the first-pass exact URL match was
  returning traces from both methods. This caused the LLM to receive GET samples when enriching a
  PUT endpoint, producing incoherent descriptions.

Add method check to the first pass (URL set match), consistent with the fallback regex pass which
  already filtered by method.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Fixed palette and shell bg padding in demo GIF chrome
  ([`05cfb27`](https://github.com/spectral-mcp/spectral/commit/05cfb27469566c8593ca0f63fc5f8d2d65d487b9))

Build palette from known terminal colors + AA ramps instead of MEDIANCUT from first frame. Add 4px
  shell background (#282a36) padding between chrome border and content.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Harden Chrome extension for MV3 compatibility
  ([`bc5fd2e`](https://github.com/spectral-mcp/spectral/commit/bc5fd2eea66afbdfc056978be03b792c69d6286e))

- Remove "type": "module" from manifest (incompatible with importScripts) - Replace
  URL.createObjectURL with base64 data URL for ZIP export (unavailable in service workers) - Inject
  content script on-demand via chrome.scripting instead of on all pages - Remove overly broad
  host_permissions and unnecessary tabs permission - Wrap content.js in IIFE to allow safe
  re-injection - Add active flag to content script with start/stop messaging from background -
  Include domain name in exported capture filename

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Prevent cache_control pollution across LLM tool calls
  ([`77df4da`](https://github.com/spectral-mcp/spectral/commit/77df4da1c66fcad0ddfaa9ff4333ca1947588593))

_call_with_tools mutated the caller's tools list by adding cache_control to the last element. When
  INVESTIGATION_TOOLS was passed directly (e.g. from detect_base_url), the shared module-level list
  got permanently polluted, causing subsequent steps (build_tool) to exceed the 4-block
  cache_control limit with a 400 error.

Fix: defensively copy the tools list in _call_with_tools. Also add auth script rules to reproduce
  all request headers from traces and only use observed endpoints (no guessing URLs for uncaptured
  flows).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Readme
  ([`4a58bd5`](https://github.com/spectral-mcp/spectral/commit/4a58bd516d42bada00b013f7a7e560c75f2b893a))

- Remove build_command from semantic-release config
  ([`1995c6e`](https://github.com/spectral-mcp/spectral/commit/1995c6e0af45bf81f1e17d0ea7a8405011f5a95c))

The semantic-release Docker container doesn't have uv installed. Building is handled separately by
  the publish-pypi workflow.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove GraphQL type-name fallback from field names
  ([`1410302`](https://github.com/spectral-mcp/spectral/commit/1410302aae4ecc548cf7b1a18d7dd0280f1feb48))

When __typename is absent and no type condition exists, skip the object subtree instead of guessing
  a type name from the field name. The field-name fallback produced bogus types — two different
  types accessed via identically-named fields got merged, corrupting the schema.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove weak `required` heuristic from body/response/query schemas
  ([`d1e8a17`](https://github.com/spectral-mcp/spectral/commit/d1e8a17646b1ac59dccb664fc60b5a7b28cc3e9b))

With few traces the 100%-presence heuristic is unreliable and wastes LLM tokens. Path params remain
  required (structural guarantee). Query params no longer emit `required: false` since that is the
  OpenAPI default.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Restore transparent corners in demo GIF chrome
  ([`35d20b6`](https://github.com/spectral-mcp/spectral/commit/35d20b64f2b23cf92311280b6b5bb8c509156236))

Force transparent pixels to palette index 0 after quantization instead of relying on nearest-color
  mapping of TKEY.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Strip @null resource refs from manifest to survive apktool recompile
  ([`6229118`](https://github.com/spectral-mcp/spectral/commit/62291189fe243b1a18f28f977adb44dac20fa0ce))

<meta-data android:resource="@null"/> elements lose their value during the apktool
  decompile/recompile cycle, producing binary XML that Android rejects with
  INSTALL_PARSE_FAILED_MANIFEST_MALFORMED. Remove these elements since @null means "no resource"
  anyway.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Strip observed from intermediate schema nodes in LLM context only
  ([`7a6f0d5`](https://github.com/spectral-mcp/spectral/commit/7a6f0d5b866505dfec89c9a68db201b6b094a2c4))

Intermediate object/array nodes carried serialized dicts as observed values, wasting LLM context
  tokens. Replace _strip_root_observed (which only stripped root-level properties) with
  _strip_non_leaf_observed that recursively strips observed from all object/array nodes while
  keeping leaf scalar observed intact. The assembly path is unchanged — intermediate observed values
  still become OpenAPI examples.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update all test files to use setup_client() instead of patching sys.modules
  ([`a0633d1`](https://github.com/spectral-mcp/spectral/commit/a0633d191d42f1d3eaa83183373382b31ee75d4f))

Replace patch.dict("sys.modules", {"anthropic": ...}) with direct setup_client(mock_client) calls
  across all test files. Fix LLM mock patterns in enrich tests to use Conversation().ask_text()
  instead of the removed llm.ask(). Add missing type annotations and remove unused imports to
  satisfy pyright.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Use examples (array) instead of deprecated example in OpenAPI 3.1 output
  ([`bf7178e`](https://github.com/spectral-mcp/spectral/commit/bf7178efd117751b83abfd40fccade09fc8774d1))

OpenAPI 3.1 aligns with JSON Schema 2020-12 which deprecates the singular "example" keyword in favor
  of "examples" (array).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Chores

- Add .gitignore and remove cached bytecode files
  ([`bbd6d05`](https://github.com/spectral-mcp/spectral/commit/bbd6d05cb7240d8a860493f0691fe1a58d32813e))

https://claude.ai/code/session_01VKC5tYNK4YGHJxhqvTbEeE

- Update .gitignore with env, debug, and generated artifacts
  ([`10b5c87`](https://github.com/spectral-mcp/spectral/commit/10b5c8782b61a401b733a116abff9d25300e44c9))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Code Style

- Replace chafa braille logo with hand-crafted spectrum analyzer ASCII art
  ([`3d9b9b1`](https://github.com/spectral-mcp/spectral/commit/3d9b9b1be7b5a8ea48c235b9db66bed00654cd93))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Documentation

- Add anchor links and reorder README sections
  ([`647b2a3`](https://github.com/spectral-mcp/spectral/commit/647b2a3d392ada2e6886eb63d90d6036ee231f01))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add banner to README
  ([`d75090d`](https://github.com/spectral-mcp/spectral/commit/d75090da4df3ab4b1c606d0a7b469cc187b75fdd))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add claude.md
  ([`64a02c7`](https://github.com/spectral-mcp/spectral/commit/64a02c72e7e2f91dbd28d730e4979c28e78405b7))

- Add implementation status section to CLAUDE.md
  ([`4fc918e`](https://github.com/spectral-mcp/spectral/commit/4fc918ef3fff318a13e8cea4b08b0d96eae84d2f))

Tracks what's done (checkboxes) across all 5 phases, plus test coverage summary.

https://claude.ai/code/session_01VKC5tYNK4YGHJxhqvTbEeE

- Add MCP server design document
  ([`a3f652a`](https://github.com/spectral-mcp/spectral/commit/a3f652ab397e11f8ea5414ba46d2f2d60eb09cf8))

Describes the new MCP path as an alternative to OpenAPI/SDL output: tool definitions with request
  templates, auth script integration, greedy extraction pipeline with interleaved identify/build
  loop.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add MkDocs Material documentation site with GitHub Pages deployment
  ([`fb573f7`](https://github.com/spectral-mcp/spectral/commit/fb573f7d03346a6b2ce9f82f59dbf4ec3afbd099))

15 documentation pages covering getting-started, capture (extension, proxy, android, certificates),
  analyze (pipeline, REST, GraphQL, auth, debug), CLI reference, and bundle format. Deployed via
  GitHub Actions on push to main. Also switches debug conversation output from JSON to the same
  plain-text format used by single-turn calls.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add README and MIT license for public release
  ([`ac6df96`](https://github.com/spectral-mcp/spectral/commit/ac6df96326cec975835f0678faeefb40b015d2a4))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add target output format and analyze stage documentation
  ([`bcf2f99`](https://github.com/spectral-mcp/spectral/commit/bcf2f9931446f0232746258a8547a5ab03ddaba4))

Define the enriched API spec format aligned with GitBook's 7 documentation principles (clear,
  concise, contextual, complete, consistent, concrete, convenient). Documents all format sections —
  endpoints, authentication, errors/operations — with honest assessment of reverse engineering
  limits. Includes target designs for quickstart and resource groups.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add theme-aware banner for GitHub light/dark modes
  ([`6a6afae`](https://github.com/spectral-mcp/spectral/commit/6a6afae0ccdf6d3dd17bc95ee55b92ab5d0ab1dd))

Generate transparent variants of the banner and use <picture> with prefers-color-scheme so the right
  version shows automatically.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add window chrome, match real Claude Code output format
  ([`5f54536`](https://github.com/spectral-mcp/spectral/commit/5f545365649d844e4187b5a46fdeacf6f25aae1e))

- Window chrome with macOS traffic lights via Pillow post-processing - 831x495px fits GitHub's 830px
  content width exactly - Tool calls now show: ● spectral - tool_name (MCP)(params) → └ HTTP 200 -
  Responses use green ● prefix like real Claude Code - 96 cols, font-size 14, github-dark theme

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Convert feature highlights to bullet list in README
  ([`8454f98`](https://github.com/spectral-mcp/spectral/commit/8454f98c03b9b5f3ce2acd34083d2ba8a61d776c))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Document three GraphQL request patterns and detection logic
  ([`32f1d6e`](https://github.com/spectral-mcp/spectral/commit/32f1d6e6f0832bc4aff1110c9945f9e7c2aebb3b))

Describe the normal query, persisted query (hash), and named operation (Reddit-style) patterns
  recognized by both Python protocol detection and the Chrome extension. Document APQ rejection
  limitations (Spotify, Reddit) and the popup toggles for per-site control.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Fix README heading levels for MITM proxy sections
  ([`d6ede9c`](https://github.com/spectral-mcp/spectral/commit/d6ede9c733ccd025cc6f904630ea6411201521d2))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Fix stale references to old auth workflow and two-stage pipeline
  ([`62ea560`](https://github.com/spectral-mcp/spectral/commit/62ea56009e6f72e8dc2d7ffdebf6743e2e0f5c5a))

Documentation still described the pre-extraction workflow where `openapi analyze` generated auth
  scripts directly and tokens lived in `~/.cache/spectral/`. Updated all affected pages to reflect
  the current three-stage pipeline (Capture → Analyze → Use), the separate `auth analyze` command,
  managed storage auth commands, and MCP tools as a first-class output.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Lighter chrome, shorter analyze, more time on Claude section
  ([`56dea37`](https://github.com/spectral-mcp/spectral/commit/56dea3742ff7d3f729f82d55562586fad4fb2e3a))

- Title bar color #2d333b contrasts with GitHub dark bg #0d1117 - Trimmed analyze output (fewer
  traces, shorter tool list) - Longer pauses on Claude responses for readability - Gitignore
  demo.cast (generated file)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Lighter title bar #586069, crop agg corners, spacing between prompts
  ([`dbbc324`](https://github.com/spectral-mcp/spectral/commit/dbbc3246ab853093c941a385cfdbaa79fed221e6))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove _documentation/ superseded by CLAUDE.md
  ([`fe608cb`](https://github.com/spectral-mcp/spectral/commit/fe608cbace3a6e39cc41b26c734ef9ddf6173ca1))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Replace real product names with generic examples in documentation
  ([#2](https://github.com/spectral-mcp/spectral/pull/2),
  [`8c654c9`](https://github.com/spectral-mcp/spectral/commit/8c654c9466068318d00ba85f60453a9716f2b2bc))

Replace reverse engineering target mentions (EDF, Spotify, Reddit) with fictional/generic
  equivalents throughout docs, code comments, and tests. Technical product names (Apollo APQ, Auth0,
  etc.) are kept as-is.

https://claude.ai/code/session_019EumpP59pHVfo5vh6uXR4U

Co-authored-by: Claude <noreply@anthropic.com>

- Resize demo GIF to fit GitHub README width (789x455)
  ([`8de7838`](https://github.com/spectral-mcp/spectral/commit/8de783831f90ac00d3721e6e08c63b366e392f71))

Reduce terminal to 92x24, font-size 14, line-height 1.3, github-dark theme. Fits within GitHub's
  830px content area without downscaling.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Restructure documentation for user-facing clarity
  ([`92e64ea`](https://github.com/spectral-mcp/spectral/commit/92e64ea08b43a9d124eeb40af3e6e361ea33e5bc))

Reorganize generation pages (MCP tools, REST output, GraphQL output) to lead with usage and
  prerequisites, moving implementation details to a "how it works" section at the end. Sort CLI
  reference alphabetically and add missing mcp install entry. Add missing LLM-calling commands to
  debug mode reference.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Revamp README with demo GIF and feature highlights
  ([`7a6ce5c`](https://github.com/spectral-mcp/spectral/commit/7a6ce5c52e8b3cedce5133a79700239c2dcdad35))

New asciinema demo (scripted .cast → GIF) showing the full flow: capture list → mcp analyze → auth
  login → Claude using the tools. Rewritten README to better sell the project: why Spectral, works
  everywhere, self-healing tools, LLM at build time not runtime, faster than browser automation.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Round top corners of terminal window chrome
  ([`ee21cc4`](https://github.com/spectral-mcp/spectral/commit/ee21cc4d03b8e8bc963c7e9a1032b39bc29ca149))

Corners filled with #0d1117 (GitHub dark bg) for seamless look.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Streamline README, link to documentation site
  ([`04ff692`](https://github.com/spectral-mcp/spectral/commit/04ff692c5dae8369d403bd9d049bbb38380bc99d))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Sync CLAUDE.md with restructured test suite and current state
  ([`987f362`](https://github.com/spectral-mcp/spectral/commit/987f362431d10539f55f8565dee4fbd844be22ad))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Transparent rounded corners on terminal window chrome
  ([`59374f0`](https://github.com/spectral-mcp/spectral/commit/59374f09347b414bc05f1683facd7b438c91d1f0))

Corners are truly transparent instead of hardcoded dark color, works on both GitHub light and dark
  mode.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update CLAUDE.md with current architecture
  ([`7d27758`](https://github.com/spectral-mcp/spectral/commit/7d2775803882de6cd88f38bd09ee0320c19a5769))

Reflect actual implementation: LLM-first pipeline, validator, ExtraInfo capture, content script
  re-injection, page content extraction, selector strategy, and updated project structure.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update CLAUDE.md with GraphQL support and new project structure
  ([`3eee4c4`](https://github.com/spectral-mcp/spectral/commit/3eee4c47a93e971e9af71983e0e2b54bc4b883c4))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update dev environment instructions for uv and dotenv
  ([`347c9e5`](https://github.com/spectral-mcp/spectral/commit/347c9e5f083ded62807c53ce95e3f8745fdace33))

Replace manual venv activation with uv run commands and document .env file usage for
  ANTHROPIC_API_KEY.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update documentation for auth extract, login fix, and pipeline changes
  ([`6fba141`](https://github.com/spectral-mcp/spectral/commit/6fba141f3d331fddd00d5145c2b0df55faedc706))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update documentation to match current implementation
  ([`a15089b`](https://github.com/spectral-mcp/spectral/commit/a15089b927b324cb89f30764199f454b20d93ec3))

Align auth-detection, pipeline-overview, rest-output, bundle-format, capture, and getting-started
  docs with the actual codebase behavior.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update README and CLAUDE.md to reflect current codebase
  ([`1bfc4f1`](https://github.com/spectral-mcp/spectral/commit/1bfc4f112b0bdb4f0ec07a8e5f7798058430283f))

Remove references to deleted generate/client commands and custom API spec format. Document OpenAPI
  3.1 as the direct output of analyze, update project structure, pipeline description, dependencies,
  and test coverage (257 tests across 12 files).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update README and CLI reference for MCP tools and auth commands
  ([`5ba5af9`](https://github.com/spectral-mcp/spectral/commit/5ba5af967f246c550761ea3260a6166ae230bbe2))

README now describes the three-stage pipeline with MCP as the primary "Use" stage, and the quick
  start shows mcp analyze, auth analyze, auth login, and mcp stdio. CLI reference adds the missing
  auth subcommands (analyze, set, login, logout, refresh).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update README, CLAUDE.md, and documentation for managed storage
  ([`7555fbf`](https://github.com/spectral-mcp/spectral/commit/7555fbf62b47aa3225444a290b08153fe138b41e))

Reflect the new managed storage workflow across all documentation: - CLI commands now use app names
  instead of ZIP file paths - capture proxy uses -a/--app instead of -o/--output - analyze takes an
  app name and merges all its captures - New commands documented: capture add, capture list, capture
  show - CLAUDE.md updated with storage.py, app_meta.py, bundle merging, managed storage layout, and
  SPECTRAL_HOME env var

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Update README, refresh branding assets and extension icons
  ([`77e6429`](https://github.com/spectral-mcp/spectral/commit/77e6429b3d507ef898ebc2cb71b0b13282513f9c))

Add documentation links banner and guides table to README. Replace banner image, add new icons,
  rename extension to Spectral.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Features

- Add --skip-enrich flag and simplify .gitignore
  ([`135e5be`](https://github.com/spectral-mcp/spectral/commit/135e5bec0357ea3771bc149f6b6993126af069b2))

Wire the skip_enrich option through analyze/pipeline commands to allow skipping LLM business context
  enrichment. Simplify .gitignore to use a single workdir entry for generated artifacts.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add `auth set` command for manual token injection
  ([`145f7e0`](https://github.com/spectral-mcp/spectral/commit/145f7e0fb1d44b3fe0ba49b9dd04640826a09864))

Provides a fallback when the LLM-generated auth script fails: users can pass headers and/or cookies
  directly via CLI options, stored in token.json.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add `spectral mcp install` command
  ([`f3ae186`](https://github.com/spectral-mcp/spectral/commit/f3ae186dee415969f71277c5652f72a39b3d87ab))

Auto-registers the MCP server in Claude Desktop (config JSON) and Claude Code (`claude mcp add`).
  Resolves absolute path to the spectral executable so the server works regardless of shell PATH.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add Android APK capture pipeline (pull, patch, MITM proxy)
  ([`4ea317d`](https://github.com/spectral-mcp/spectral/commit/4ea317db1fefa33368480922e802a51296586d28))

New `api-discover android` command group with subcommands: list, pull, patch, install, and capture.
  Enables traffic capture from Android apps via mitmproxy with automatic bundle generation. Includes
  ADB helpers, APK network-security patching for MITM, and proxy-based capture with domain
  filtering. Adds mitmproxy dependency and makes CaptureManifest fields optional to support
  non-browser capture methods.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add auth grab flow via extension and native messaging
  ([`5ad17b1`](https://github.com/spectral-mcp/spectral/commit/5ad17b1426e861033810a16ba1085072aafe3726))

Add cookie and storage token extraction from the active tab (via chrome.cookies +
  scripting.executeScript). Send selected auth headers to the CLI through a new set_auth native
  message handler that persists them as TokenState. Refactor slugify/extractDomain into shared
  utils, add cookies permission to manifest, split popup into auth.js/capture.js modules, and add
  host handler tests.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add braille logo banner to CLI help output
  ([`685cb47`](https://github.com/spectral-mcp/spectral/commit/685cb47b3aa7b75e90a7b6d8d93cef1440726213))

Pre-rendered chafa braille banner (256 colors) displayed above the help text when stdout is a TTY.
  No runtime dependency on chafa.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add bundle merging and wire analyze command to managed storage
  ([`5570ebc`](https://github.com/spectral-mcp/spectral/commit/5570ebc53af49cdd439e1ab007a4031412a18eda))

The analyze command now takes an app name instead of a ZIP path, loading and merging all captures
  for that app via the managed storage layer. Bundle merging remaps all IDs (traces, contexts, WS
  connections and messages) with a capture-index prefix to avoid collisions, and preserves all
  cross-references including handshake_trace_ref.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add call command, structured auth configs, and flexible auth in generators
  ([`57ae5d4`](https://github.com/spectral-mcp/spectral/commit/57ae5d404866ae1c71b6460d528879df98f35dd9))

Add `api-discover call` command with ApiClient for calling API endpoints directly from enriched
  specs. Replace the simple `refresh_endpoint` string with structured `LoginEndpointConfig` and
  `RefreshEndpointConfig` models that capture credential fields, extra fields, and token response
  paths. Generators now use `token_header`/`token_prefix` from the spec instead of hardcoded
  bearer/basic values, with new api_key security scheme support in OpenAPI. Auth detection enhanced
  with custom header support (X-API-Key, X-Auth-Token) and login POST prioritization in LLM prompts.
  Also fixes base URL path prefix stripping to avoid double prefixes in endpoint patterns.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add GraphQL interception settings to popup UI
  ([`9ffca9c`](https://github.com/spectral-mcp/spectral/commit/9ffca9c311ee089d45a1dcaf496e582b7065a872))

Add toggles for __typename injection and persisted query blocking in the extension popup. Settings
  are persisted via chrome.storage.local and sent to the background via UPDATE_SETTINGS messages.
  Also widens the Fetch intercept pattern from *graphql* to * so GraphQL endpoints without "graphql"
  in their path (e.g. Spotify's /pathfinder/v1/query) are caught.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add GraphQL support and reorganize extension into subdirectories
  ([`8f0d0b2`](https://github.com/spectral-mcp/spectral/commit/8f0d0b2a8e987bb3bdefcd27f00fd651f21200f3))

- Add GraphQL capture (__typename injection in extension and CLI) and analysis pipeline (parsing,
  type extraction, LLM enrichment, SDL output) - Split analyze steps into rest/ and graphql/
  sub-packages - Reorganize extension/ into background/, content/, popup/ subdirectories - Change -o
  flag to accept a base name (produces .yaml and/or .graphql) - Add call frequency to
  detect_base_url prompt for better GraphQL detection - Update README with GraphQL support, MITM
  proxy docs, and Android prereqs

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add host_permissions for content script re-injection
  ([`d9ca709`](https://github.com/spectral-mcp/spectral/commit/d9ca70945aee641d384c90d5902a4e04e421eab5))

activeTab expires on full-page navigation, so host_permissions is needed for
  chrome.scripting.executeScript to work on subsequent pages.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add install script and update docs for uv tool install workflow
  ([`2135a88`](https://github.com/spectral-mcp/spectral/commit/2135a889d9798f7a990c7bedf034687a2f585a37))

Add install.sh that automates uv + spectral installation, handles upgrades, and configures shell
  completion. Update all documentation to use `spectral` directly instead of `uv run spectral`, with
  dev setup sections preserved for contributors.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add LLM investigation tools, URL compaction, and debug logging
  ([`1e1f7d3`](https://github.com/spectral-mcp/spectral/commit/1e1f7d3ca55aae9067eff8f46ab6b1f2c661fc6f))

- Add decode_base64, decode_url, decode_jwt tools for LLM tool_use during endpoint analysis, letting
  the LLM inspect opaque URL segments - Add _call_with_tools loop to handle multi-turn tool_use
  conversations - Compact long base64 URL segments before sending to LLM to save tokens, with
  reverse mapping to restore original URLs in the output - Add debug logging: save every LLM
  prompt/response to debug/<timestamp>/ - Add per-endpoint progress reporting during analysis -
  Update test mocks for tool_use response format (stop_reason, type)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add managed storage layer and capture CLI commands
  ([`6c3feac`](https://github.com/spectral-mcp/spectral/commit/6c3feac8eb1db3d6286ade4726706629a243067f))

Introduces ~/.local/share/spectral/ storage layout with per-app directories and flat-file capture
  bundles. Adds CLI commands: capture add, capture list, capture show. Updates inspect and proxy to
  operate on managed storage instead of raw ZIP files.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add MCP pipeline, server, query commands, and tool/auth storage
  ([`4741a67`](https://github.com/spectral-mcp/spectral/commit/4741a676987fc798d6691c1a0c0f29e739bd56fe))

Implements the full MCP path from the design document: - MCP analysis pipeline (identify
  capabilities, build tool definitions, trace cleanup loop) with greedy extraction - MCP server with
  stdio transport, tool namespacing, request construction, and auth cascade (valid token →
  auto-refresh → error) - Query CLI commands (login, refresh) for interactive auth flows - Tool and
  auth storage in managed storage (tools/*.json, auth_acquire.py, token.json) - ToolDefinition and
  TokenState Pydantic models - AppMeta extended with base_url field - Improved truncate_json with
  depth limiting and noise header stripping

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add python-dotenv support and API client retry
  ([`8dbf09a`](https://github.com/spectral-mcp/spectral/commit/8dbf09aa61a556c19a3d76568ae4df00141bd849))

Load .env file at startup for ANTHROPIC_API_KEY. Add max_retries=3 to AsyncAnthropic client for
  transient error resilience.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add requires_auth field to ToolDefinition and gate auth in MCP server
  ([`eb9d84b`](https://github.com/spectral-mcp/spectral/commit/eb9d84b2f8523f17940ddecf2a25e6a6ed979b07))

Tools now declare whether they need authentication. The server skips auth lookup for public
  endpoints and returns an actionable error when auth is required but missing. Also preserves
  user-agent header in sanitized headers for WAF/API compatibility.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add shell completion for bash and zsh
  ([`423040e`](https://github.com/spectral-mcp/spectral/commit/423040eacbcf2578d906b422dc222c8cc2e5e89c))

Add tab-completion for commands, options, and app names via Click's built-in shell_complete
  mechanism. A new `spectral completion bash|zsh` command generates the script to source in the
  user's shell profile.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add system parameter to llm.ask() for prompt caching
  ([`fcf984c`](https://github.com/spectral-mcp/spectral/commit/fcf984c7fec6d7476ca1d3ac5e94276b5109d448))

Add system: str | list[str] | None parameter to ask() that builds cached system blocks with
  cache_control: ephemeral. Each string becomes a separate text block, enabling multi-breakpoint
  caching where shared context is cached across calls.

Also includes cache token tracking (get_cache_usage), per-call cost logging with cache pricing, and
  response_model retry support.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add tell_user, wait_user_confirmation, and debug helpers to auth scripts
  ([`203fbbe`](https://github.com/spectral-mcp/spectral/commit/203fbbec39e9c8cf02ca1149049236b5ae35f662))

Expand the injected helpers available to generated auth scripts: tell_user for displaying messages,
  wait_user_confirmation for OAuth-style flows, and debug (renamed from print) for troubleshooting
  output. Simplify prompt helpers to use click.prompt directly.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Capture ExtraInfo headers and re-inject content script on navigation
  ([`cbf0afd`](https://github.com/spectral-mcp/spectral/commit/cbf0afd41e4ba7bf03bc20babbd73006ecaf86f7))

- Add handlers for requestWillBeSentExtraInfo and responseReceivedExtraInfo to capture wire-level
  headers (Cookie, Set-Cookie, browser-managed Auth) - Buffer ExtraInfo events that arrive before
  their base events - Re-inject content.js via chrome.tabs.onUpdated when a full-page navigation
  completes, so UI capture continues across non-SPA navigations

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Detect dynamic map keys in JSON schema inference
  ([`7ce51e6`](https://github.com/spectral-mcp/spectral/commit/7ce51e6ff3d4c4be0487a8f25973db01ab328e56))

Objects whose keys all match a pattern (dates, years, UUIDs, numeric IDs) are now represented with
  additionalProperties instead of enumerated properties, with x-key-pattern and x-key-examples
  extensions. The enrich and assemble steps propagate these schemas correctly through observed
  stripping, description application, and examples conversion.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Detect enum types from literal argument values in GraphQL queries
  ([`3a9ab5b`](https://github.com/spectral-mcp/spectral/commit/3a9ab5bf9c65c459af96992bffe93b7850ec3afa))

When a query uses a bare identifier like `items(status: ACTIVE)`, the extraction step now recognizes
  it as an enum value instead of misclassifying it as String. Inferred enums are named
  deterministically (e.g. InferredQueryItemsStatusEnum) and accumulate values across traces.
  Variable-resolved types still take precedence.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Detect named-operation GraphQL requests (Reddit-style)
  ([`c522219`](https://github.com/spectral-mcp/spectral/commit/c52221924408000ac3ecf7e47581dade39804a4d))

Add detection for GraphQL requests that send only an operation name and variables without query text
  or persisted query hash (e.g. Reddit's {"operation": "FetchUsers", "variables": {...}}). Supports
  both "operation" and "operationName" keys.

Both Python protocol detection and the Chrome extension's isGraphQLItem use the same three-shape
  check: normal query, persisted query hash, or named operation with variables. The extension also
  uses isGraphQLItem as an early filter in handleFetchRequestPaused to skip non-GraphQL POSTs
  quickly (needed since we intercept all URLs, not just *graphql*).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Display real-time LLM token usage during analysis
  ([`b30551f`](https://github.com/spectral-mcp/spectral/commit/b30551f0f22a30aec443953b7f841587e0bf1310))

Track input/output token counts from each API response and print a dim per-call summary line during
  analysis. Show a total usage recap after build_spec() completes. Also switch _readable_json to the
  compact-json library for reliable debug formatting.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Drop large response schemas from enrichment prompt to prevent truncation
  ([`a9c3199`](https://github.com/spectral-mcp/spectral/commit/a9c31995f3f9ce84213a036111fdbce30904d776))

Response schemas above 5,000 chars are omitted from the per-endpoint enrichment summary since
  callers primarily need to know how to *call* the API, not parse the response. This avoids output
  truncation on complex endpoints (e.g. journey-search with ~900 lines of response schema) without
  losing request-side enrichment quality.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract auth tokens from captured traces
  ([`133cdea`](https://github.com/spectral-mcp/spectral/commit/133cdea52f13bb46f5b1db725fbc1713e188e0d7))

Two-step strategy: fast-path picks Authorization header from the most recent matching trace, LLM
  fallback identifies non-standard auth headers (Cookie, X-Auth-Token, etc.) when Authorization is
  absent.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Filter traces by LLM-detected API base URL before analysis
  ([`d168f32`](https://github.com/spectral-mcp/spectral/commit/d168f321afb6ec3ebde863cbbe97e1ae50392db4))

Add detect_api_base_url() LLM call upstream in the pipeline to identify the business API base URL,
  then filter out non-API traces (CDN, analytics, tracking) before endpoint grouping. Also make
  --debug opt-in instead of hardcoded.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Generate Restish config and LLM-powered auth helper from analyze output
  ([`c64a165`](https://github.com/spectral-mcp/spectral/commit/c64a1657e0b03744a69765b4c5c0bfeea08a8b3c))

After producing an OpenAPI spec, `spectral analyze` now also generates: - A `.restish.json` config
  entry mapping AuthInfo to Restish profiles (api_key, basic, oauth2_cc, external-tool, or static
  placeholders) - An LLM-generated auth helper script for interactive auth flows (OTP, login forms,
  etc.) called by Restish's external-tool mechanism

The auth helper is generated by a new GenerateAuthScriptStep that gives the LLM access to trace
  inspection tools so it can understand the full auth flow and produce a self-contained stdlib-only
  Python script.

Also fixes pre-existing pyright errors (re.error, public API naming).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Implement api-discover CLI pipeline (Phases 1-4)
  ([`735c983`](https://github.com/spectral-mcp/spectral/commit/735c9839ecf11c01af6964df6a592d6d71fdb031))

Implements the full Python CLI for the api-discover project:

- Pydantic models for capture bundle format and enriched API spec - Bundle loader/writer with ZIP
  serialization (binary-safe) - Protocol detection (REST, GraphQL, gRPC, WebSocket sub-protocols) -
  Time-window correlator for UI action ↔ API call mapping - Mechanical spec builder (path parameter
  inference, schema inference, auth detection, endpoint grouping, response analysis) - LLM client
  skeleton for Anthropic API enrichment - 5 output generators: OpenAPI 3.1, Python client, Markdown
  docs, cURL scripts, MCP server scaffold - HAR import/export for compatibility - Full CLI with
  analyze, generate, pipeline, inspect, import-har, export-har commands - 157 tests covering all
  non-LLM/non-extension components

https://claude.ai/code/session_01VKC5tYNK4YGHJxhqvTbEeE

- Implement Chrome extension for network/UI capture
  ([`28063ff`](https://github.com/spectral-mcp/spectral/commit/28063ff2b16301fcc8825fd3fab0068bacaa0cb7))

- Add Chrome extension (Manifest V3) with debugger-based network capture - background.js: State
  machine, DevTools Protocol capture (HTTP + WebSocket) - content.js: DOM event capture with rich
  page context extraction - popup.html/css/js: Clean UI with live capture stats - Add PageContent
  model to CLI for rich page context (backward compatible) - Bundle export in ZIP format compatible
  with api-discover CLI

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>

- Improve extension UX, permissions, and store readiness
  ([`90c0f27`](https://github.com/spectral-mcp/spectral/commit/90c0f27f118d09d656e9284b5832d452672634d1))

Move native host connection check to background service worker (cached, non-blocking). Switch to
  optional_host_permissions and request origin access at capture start. Fix state reset on
  unexpected debugger detach. Hide popup container until fully initialized. Update manifest name and
  description for Chrome Web Store. Add promotional assets and demo script.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Interactive auth script fix on login failure
  ([`39389d2`](https://github.com/spectral-mcp/spectral/commit/39389d2afb15c9b25657b03ebd6d44cc2460f9ec))

When `spectral auth login` fails, catch the error and offer to call the LLM to fix the script. Uses
  the same conversation across retries so the LLM remembers previous attempts. Injects a captured
  print() into auth scripts so debug output is forwarded to the LLM on failure.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Migrate API key from .env to managed storage
  ([`b4525c6`](https://github.com/spectral-mcp/spectral/commit/b4525c685568b37d31ac27679b8c942137fd7f8f))

Store the Anthropic API key in ~/.local/share/spectral/api_key instead of requiring a .env file with
  python-dotenv. Key resolution order: env var > stored file > interactive prompt with format
  validation.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Populate previously-empty spec fields (format, rate_limit, discovery_notes, constraints, response
  details, api_name, WS enrichment)
  ([`45bee7a`](https://github.com/spectral-mcp/spectral/commit/45bee7aa0ab5e1385fce3b7c2f4f3994d97ecce9))

Close gaps between documented API spec format and actual pipeline output: - Wire up _detect_format
  for body and query params in mechanical extraction - Extract rate limit info from response headers
  (X-RateLimit-*, Retry-After) - Expand enrichment prompt with discovery_notes,
  parameter_constraints, rich response_details (example_scenario, user_impact, resolution), and
  api_name - Include observed_values in param summaries sent to LLM for constraint inference - Add
  WS connection summaries to enrichment prompt for business_purpose inference - Thread api_name
  through EnrichOutput → AssembleInput → ApiSpec.name - Update markdown docs generator to render all
  new fields - Update OpenAPI generator with constraints in descriptions and x-rate-limit - Bump
  enrichment max_tokens from 4096 to 6144 - Add 15 new tests (222 total)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Publish to PyPI as spectral-mcp with automated releases
  ([`aa4c388`](https://github.com/spectral-mcp/spectral/commit/aa4c3885e10275aa1ff666ea14c16562241d3448))

Rename package to spectral-mcp, add PyPI metadata and semantic-release config. Version is now read
  dynamically via importlib.metadata. Install script uses PyPI instead of git URL. CI workflows
  handle version bumps (semantic-release) and PyPI publishing (trusted publisher OIDC).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Reject persisted queries with PersistedQueryNotFound to force full query retry
  ([`6d41213`](https://github.com/spectral-mcp/spectral/commit/6d412136cd56066d204af69be24de047242759db))

Apollo APQ clients send a hash instead of the full query. By responding with PersistedQueryNotFound
  via Fetch.fulfillRequest, the client retries with the complete query text, which then flows
  through __typename injection normally. Handles both single and batch requests.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Replace Click shell_complete with static completion scripts
  ([`e831456`](https://github.com/spectral-mcp/spectral/commit/e831456a97d48e73b3ea7ead14dd6cc73ee07a78))

Static bash/zsh scripts in cli/completions/ provide zero-latency tab completion by hardcoding the
  command tree and resolving app names via ls. Remove cli/helpers/completions.py and all
  shell_complete= kwargs. Simplify cli/main.py by removing lazy group loading in favor of direct
  imports.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Replace find_traces with jq-powered query_traces tool
  ([`cdf8c41`](https://github.com/spectral-mcp/spectral/commit/cdf8c4152f3f88cde93dc0ff1c5de4bd9c2dde86))

The find_traces tool had path-only URL patterns broken (fnmatch ran against full URLs) and
  body_contains was too limited for structured searching. Replace with a single query_traces tool
  that exposes all trace data to a jq expression, covering URL filtering, status filtering, body
  field extraction, and cross-trace aggregation in one tool.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Replace ZIP export with Chrome Native Messaging
  ([`df87eae`](https://github.com/spectral-mcp/spectral/commit/df87eae7ca5879c5468c4472022b8a318176995a))

The extension now sends captures directly to the CLI via Chrome Native Messaging instead of
  exporting ZIP files for manual import. This removes the download-then-import friction — one click
  from the extension stores the capture in managed storage immediately.

New CLI commands: `spectral extension install` writes the native messaging host manifest, `spectral
  extension listen` is the host process Chrome spawns. The popup pings the host on open and blocks
  capture until the connection is established, showing the install command with a copy button.

Also: app name now derived from domain (e.g. leboncoin.fr) instead of page title, `capture add`
  command removed, JSZip dependency dropped.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Restructure MCP prompts for prompt caching with system blocks
  ([`27f9e8c`](https://github.com/spectral-mcp/spectral/commit/27f9e8cf94687f6c9cec9fde5da07a293917b864))

Move static content into cached system blocks to reduce per-call costs: - Extract
  IDENTIFY_INSTRUCTIONS and BUILD_TOOL_INSTRUCTIONS as constants - Pass system=[system_context,
  step_instructions] to llm.ask() - User message now only contains per-call data (target trace,
  existing tools)

Two cache breakpoints: block 1 (shared context) is reused across all identify + build_tool calls;
  block 2 (step instructions) is reused within each step type. ~80-90% savings on shared context
  tokens.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Performance Improvements

- Minify JSON in LLM input/output to reduce token usage
  ([`24dcd42`](https://github.com/spectral-mcp/spectral/commit/24dcd428bd3f819765e92445a1425e6276ebdd19))

Compact JSON (no whitespace) for all LLM-bound json.dumps calls saves input tokens; prompts now
  request compact JSON output to save output tokens. Debug readability is preserved via a
  semi-compact reformatter applied in _save_debug.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Use compact JSON in LLM prompts to reduce token usage
  ([`9a27be8`](https://github.com/spectral-mcp/spectral/commit/9a27be8b6e7127230f00f6286a7524a901d931a1))

Remove indent=2 from json.dumps calls in LLM prompts (saves ~30-40% whitespace tokens). Format list
  items one-per-line for debug readability. Limit endpoint enrichment to 10 in debug mode to save
  tokens during testing.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Refactoring

- Centralize pipeline intermediate types into steps/types.py
  ([`740075c`](https://github.com/spectral-mcp/spectral/commit/740075c0cd1f06ae8949aefb8650acb9e6e24112))

Scattered dataclasses (FilterInput, StripPrefixInput, MechanicalExtractionInput,
  EnrichInput/EnrichOutput, AssembleInput) and the opaque list[tuple[str, str]] are replaced by
  descriptively-named dataclasses in a single file, making the pipeline's data flow readable without
  opening each step module.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Collapse auth analysis into single script-generation step
  ([`acc3901`](https://github.com/spectral-mcp/spectral/commit/acc39018af25e80924034e4a3b697932d18653d0))

Remove the two-step flow (AnalyzeAuthStep → AuthInfo → GenerateMcpAuthScriptStep) and replace with a
  single GenerateAuthScriptStep that discovers auth from traces directly. The LLM now uses
  inspect_trace to find auth patterns and generates the script in one call. Returns NO_AUTH sentinel
  when no auth mechanism is found.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Consolidate LLM calls into single ask() entry point
  ([`3675bf5`](https://github.com/spectral-mcp/spectral/commit/3675bf577f811456f9ff9e3db01639ca0fd0014f))

Replace dual calling patterns (create()+save_debug() and call_with_tools()) with a unified ask()
  that takes a prompt, returns text, and handles debug logging internally. This fixes the missing
  debug save in GraphQL enum enrichment and removes boilerplate from all 7 call sites.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Consolidate schemas.py public interface to 2 functions
  ([`eb7a974`](https://github.com/spectral-mcp/spectral/commit/eb7a974401bbbe6b0ae9e3ba19349d948c81a6c4))

Reduce the public API surface of schemas.py from 7 functions to 2: - infer_schema (renamed from
  build_annotated_schema) — single schema inference function with observed values -
  extract_query_params — now returns enriched dicts with type/format/required

Removed redundant infer_json_schema and merge_schemas. Made helper functions private (_infer_type,
  _infer_type_from_values, _detect_format). Updated mechanical_extraction and build_ws_specs to use
  the consolidated interface, stripping observed values from output schemas.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Deduplicate helpers across llm, extraction, schemas, and loader
  ([`8821d50`](https://github.com/spectral-mcp/spectral/commit/8821d50f2b0581badaeef5ddb31adf64c42ae58b))

- Extract _extract_text() and _execute_tool() in llm.py to deduplicate text extraction (3x) and tool
  result construction (3x) in _call_with_tools - Extract _collect_json_bodies() in extraction.py to
  unify JSON body parsing loops in _build_request_spec and _build_response_specs - Extract
  _detect_map_candidate() in schemas.py to encapsulate structural similarity detection, making
  _infer_object_schema a clean 3-step flow - Extract _read_zip_entry() in loader.py to replace 3
  occurrences of the "read binary from ZIP or return b''" pattern - Unify trace-matching logic:
  extract match_traces_by_pattern() in extraction.py, reused by enrich.py's _find_endpoint_traces

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Dissolve shared analyze/ pipeline, each command owns its analysis
  ([`3027d99`](https://github.com/spectral-mcp/spectral/commit/3027d99ddecd78cba8594287c8290598a3cc94ed))

Remove the over-engineered Step[In, Out] / ProtocolBranch / registry architecture in
  cli/commands/analyze/. Each command now owns its analysis logic directly:

- cli/commands/openapi/analyze/ — REST pipeline (group, extract, enrich, assemble) -
  cli/commands/graphql/analyze/ — GraphQL pipeline (extract, enrich, assemble) - cli/commands/mcp/ —
  MCP tool pipeline (identify, build_tool, investigation) - cli/commands/auth/analyze.py — auth
  script generation

Shared utilities moved to cli/helpers/: - correlator.py, context.py, detect_base_url.py, schemas.py,
  llm_tools.py - http.py += sanitize_headers, compact_url - llm.py += truncate_json

All Step classes converted to plain async def functions. Deleted: ProtocolBranch,
  StepValidationError, BranchContext, BranchOutput, AnalysisResult, protocol.py fan-out, and the
  entire analyze/ directory.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract centralized LLM helper with rate-limit retry and concurrency control
  ([`7b3ee27`](https://github.com/spectral-mcp/spectral/commit/7b3ee2708e05d988e19c1537e7433e9b2796e6a1))

Move all LLM infrastructure out of the analyze pipeline into cli/helpers/llm.py: - Module-level
  client + semaphore with init()/reset() lifecycle - Rate-limit retry reading retry-after header
  (fallback exponential backoff) - Generic helpers (extract_json, save_debug, call_with_tools) moved
  from tools.py - Remove client parameter threading through pipeline, steps, and call_with_tools

Also fix all 21 pre-existing pyright errors and add verification checklist to CLAUDE.md.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract cli/helpers/schema/ package from json/ and schemas.py
  ([`f2f8b54`](https://github.com/spectral-mcp/spectral/commit/f2f8b544fd592c77cc6a2df4cb133043acc024b3))

Move schema inference and analysis into a dedicated package with clean module boundaries:
  _schema_inference, _schema_analysis, _scalars, _params, _query.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract external_tools package from android commands
  ([`e3df0be`](https://github.com/spectral-mcp/spectral/commit/e3df0be53e3d0d8fa1f4a4d2d6a105e1cd7f2c83))

Move adb.py into cli/commands/android/external_tools/ and extract bootstrap (jar download, java
  check), apktool (decompile, build), and uber_signer (sign, debug keystore) into dedicated modules.
  patch.py now only contains patching logic.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract generic JSON helpers into cli/helpers/json/
  ([`3289b95`](https://github.com/spectral-mcp/spectral/commit/3289b95d6ac0c7cba1ac9648a0908aa399a8dbb9))

Move serialization (minified, compact), simplification (truncate_json), and schema inference out of
  llm.py and schemas.py into a dedicated cli/helpers/json/ package with no domain dependencies.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract inline prompts into Jinja2 templates
  ([`fd1904c`](https://github.com/spectral-mcp/spectral/commit/fd1904ce062c0dd621ec0458536c367f25063a15))

Move all inline LLM prompt strings into cli/prompts/*.j2 templates, rendered via the new
  cli/helpers/prompt.py helper. Covers auth, GraphQL enrich, OpenAPI enrich/group, MCP
  build/identify, schema analysis, and base URL detection.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract inspect implementation from cmd.py into inspect.py
  ([`99a6122`](https://github.com/spectral-mcp/spectral/commit/99a6122d8715de5c806c8c31623387e564f307e0))

cmd.py now only contains Click command definitions. The inspect rendering logic (summary, trace
  detail, body printing) moves to its own module.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract shared helpers from command packages (naming, subprocess, http)
  ([`1012b47`](https://github.com/spectral-mcp/spectral/commit/1012b4713d27478ab2fa83e944911e37b52e839f))

Deduplicate _safe_name/_python_type/_to_func_name across generators into cli/helpers/naming.py, the
  subprocess run-check-raise pattern across android/ into cli/helpers/subprocess.py, and
  _get_header/get_header across analyze/ into cli/helpers/http.py. Adds 25 tests for the new
  helpers.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract shared mitmproxy infra and GraphQL injection from proxy.py
  ([`881324e`](https://github.com/spectral-mcp/spectral/commit/881324ee83dbc70e51470c83645d4cfca98b7b12))

Split proxy.py (517 lines) into focused modules: - _mitmproxy.py: shared infra (flow_to_trace,
  ws_flow_to_connection, domain_to_regex, run_mitmproxy) - _mitm_gql_injection.py: GraphQL
  __typename injection (renamed from graphql_utils.py, absorbed flow-level injection) - proxy.py:
  CaptureAddon + proxy CLI only - discover.py: DiscoveryAddon + run_discover (no longer depends on
  proxy)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Extract subcommands from cmd.py into individual modules
  ([`87af1f7`](https://github.com/spectral-mcp/spectral/commit/87af1f7b8845c07380e401958c05977ae59ad207))

Split monolithic cmd.py files across all command groups (android, auth, capture, extension, graphql,
  mcp, openapi) into one module per subcommand. The cmd.py files become thin registration-only
  wiring.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Greedy per-trace MCP pipeline with response models and system context
  ([`b9ca8f4`](https://github.com/spectral-mcp/spectral/commit/b9ca8f4a7e8fdaa221ecf964a15b10b14bc2b635))

- Add IdentifyResponse, BuildToolResponse Pydantic models for LLM parsing - Replace
  correlation-based IdentifyInput with per-trace evaluation pattern - Add ToolBuildResult dataclass,
  contexts to ToolBuildInput - Rename timeline_text to system_context for prompt caching - Build
  system_context (role + base URL + timeline) in pipeline orchestrator

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Lazy-import decode_base64 in http.py and reformat frozenset
  ([`d56c603`](https://github.com/spectral-mcp/spectral/commit/d56c6037a20b905d415e14e490aec9a49e470b03))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Llm-first analysis with mechanical verification
  ([`454d87e`](https://github.com/spectral-mcp/spectral/commit/454d87ef7eaf6907ceaa3b9959d05f576623c12a))

Replace the mechanical-first pipeline with an LLM-first architecture: the LLM groups URLs into
  endpoints and infers business meaning, then mechanical code validates the result against actual
  traces and triggers a correction pass if needed.

- Extension: filter static assets and chrome-extension:// URLs at capture - llm.py: specialized
  calls (analyze_endpoints, analyze_auth, analyze_endpoint_detail, analyze_business_context,
  correct_spec) - validator.py: mechanical checks (coverage, pattern match, schema consistency, auth
  coherence) returning structured errors - spec_builder.py: async LLM-first pipeline with validation
  loop - main.py: remove --no-llm flag, ANTHROPIC_API_KEY now required - Tests: add validator tests,
  mock LLM in spec_builder/CLI tests, add pytest-asyncio dependency

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Make pipeline protocol-agnostic via ProtocolBranch abstraction
  ([`2806f66`](https://github.com/spectral-mcp/spectral/commit/2806f66bf791ba743ada1f6f1cb1b6e5805e0b3a))

Each protocol (REST, GraphQL) is now encapsulated in a ProtocolBranch subclass with its own
  extract→enrich→assemble logic. The pipeline dispatches traces to branches generically and runs
  them in parallel, removing all protocol-specific code from pipeline.py. Unsupported protocols are
  handled by a catch-all branch instead of a special case.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Merge cmd.py into __init__.py for all command packages
  ([`4fb3711`](https://github.com/spectral-mcp/spectral/commit/4fb37114670adabf3a273d36731c2fe9d3e3dba7))

Move Click group definitions from the 7 cmd.py files into their package __init__.py, the idiomatic
  location for a package's public interface. Simplify imports in main.py accordingly.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Migrate ask_text JSON calls to ask_json with Pydantic models
  ([`54c82a3`](https://github.com/spectral-mcp/spectral/commit/54c82a3ff253937d813ba48bf55ce4f514aeb345))

Six call sites were using ask_text() + extract_json() + manual dict validation. Migrated them to
  ask_json(prompt, ResponseModel) to get automatic retry on parse/validation failure, Pydantic
  validation, and consistent JSON instructions. Also improved ask_json itself: the prompt now says
  "JSON value" (supports arrays), and the retry message includes the model's JSON schema.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Move auth_framework into cli/commands/auth/
  ([`9ee4eca`](https://github.com/spectral-mcp/spectral/commit/9ee4eca669d93d8304050636d11dc49cb4738433))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Move command packages under cli/commands/, shared utils under cli/helpers/
  ([`a38037b`](https://github.com/spectral-mcp/spectral/commit/a38037b8c0ddf904b15dd8d85f8477426a479e5c))

Separates concerns into three tiers: commands (analyze, android, capture, client, generate), formats
  (unchanged), and helpers (console). Updates all imports and patch() targets across cli/ and
  tests/.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Move debug_dir into llm.init() instead of threading through pipeline
  ([`06baa06`](https://github.com/spectral-mcp/spectral/commit/06baa06a327b84dc4e5a3fe67a31c66f58d71f53))

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Move extract_json and reformat helpers from llm.py into cli/helpers/json/
  ([`33bec24`](https://github.com/spectral-mcp/spectral/commit/33bec249c6a591452d7090a93b2168f14df5f010))

Delete the deprecated wrappers (compact_json, truncate_json, extract_json, _reformat_debug_text)
  from llm.py and migrate all callers to import directly from cli.helpers.json.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Move proxy to capture group, add android cert command
  ([`d10af2e`](https://github.com/spectral-mcp/spectral/commit/d10af2e599c928e2063ffa27a89c44d5f4a435f8))

The MITM proxy is generic (not Android-specific), so move it from `android capture` to `capture
  proxy`. Add `android cert` for pushing CA certificates to devices. `inspect` now lives under
  `capture inspect`.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Move subprocess.py into android/external_tools
  ([`bdac403`](https://github.com/spectral-mcp/spectral/commit/bdac403b3b16da2884b86619e7c35a2d72f6a8b3))

Only used by adb, apktool, uber_signer — not a shared helper.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Move transport layer to _client.py and rewrite helper tests
  ([`4e06bca`](https://github.com/spectral-mcp/spectral/commit/4e06bca27741814bb86d31eca296656482cf3bf7))

Move retry/semaphore/rate-limiting logic from _conversation.py into _client.py (new `send()`
  function), making the client a proper transport wrapper. Conversation now only manages
  conversation logic and delegates sends to _client.send(). Move _build_system_blocks,
  _check_truncation, _try_parse_model into the Conversation class.

Rewrite tests for helpers/json (add TestCompact, TestTruncateJson), helpers/llm (test public API
  only: Conversation, set_model, init_debug, send, print_usage_summary), and helpers/schema (drop
  private-API tests, fix LLM mock pattern for Conversation-based code).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Move truncate() into capture/cmd.py as private helper
  ([`cc122a3`](https://github.com/spectral-mcp/spectral/commit/cc122a32ac8be48a96ec9bb367a8493480058e56))

The function was only used in one module, so inlining it removes the shared dependency and keeps
  console.py minimal.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Output OpenAPI 3.1 directly, remove generate and client commands
  ([`1d7d16d`](https://github.com/spectral-mcp/spectral/commit/1d7d16ddf527d0c0b29c164d3836d17c1e7528e7))

Replace the custom enriched API spec format (api_spec.py Pydantic models) with direct OpenAPI 3.1
  dict output from the pipeline. The AssembleStep now builds a standard OpenAPI document with
  security schemes, parameters, request bodies, and responses — embedding LLM-inferred business
  semantics in summary/description fields.

Removed: - generate command and all 5 generators (openapi, python-client, mcp-server, markdown-docs,
  curl-scripts) - client/call command (ApiClient) - cli/formats/api_spec.py (spec types moved to
  steps/types.py as dataclasses) - build_ws_specs.py step

Changed: - Pipeline returns dict[str, Any] (OpenAPI 3.1) instead of ApiSpec - Spec types are now
  dataclasses in steps/types.py - Enrichment step refactored for parallel per-endpoint LLM calls -
  Schema inference expanded with annotation support - analyze command outputs YAML instead of JSON

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Relocate misplaced code to proper modules
  ([`fab0d40`](https://github.com/spectral-mcp/spectral/commit/fab0d40cdc9a30ca7edf6e0dfb0454cf98af5fdf))

- Move auth runtime (mcp/auth.py) to helpers/auth_runtime.py since it's shared infrastructure used
  by mcp, auth/login, and auth/refresh - Move fix_auth_script from auth/analyze.py to auth/login.py,
  its only caller - Delete helpers/naming.py and its tests (dead code, zero production imports)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove auth analysis from all analysis pipelines
  ([`0ceb2ef`](https://github.com/spectral-mcp/spectral/commit/0ceb2efddb35ec38c292416226488d514d43e713))

Auth analysis (AnalyzeAuthStep, detect_auth_mechanical, auth script generation, securitySchemes,
  per-operation security) was tightly coupled into REST, GraphQL, and MCP pipelines but is
  orthogonal to API discovery. Remove it entirely to simplify the pipelines; a dedicated `spectral
  auth` command can be added later if needed.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove cleanup step, add inspect_context tool, use centralized cost estimation
  ([`8e01bd2`](https://github.com/spectral-mcp/spectral/commit/8e01bd260a242e52316ff9b58df4c6189b341d33))

- Delete CleanupTracesStep (replaced by consumed_trace_ids in greedy pipeline) - Add inspect_context
  tool to MCP investigation tools with contexts param - Use llm.estimate_cost with cache token
  tracking in analyze command - Fix content block extraction in test pipeline mock

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove dead AUTH_FRAMEWORK_CODE and generate_auth_script
  ([`b15f076`](https://github.com/spectral-mcp/spectral/commit/b15f07678971151b209accd61144667c9a1bbc51))

The standalone auth script framework (TokenCache, JWT decode, prompt_credentials, main entrypoint)
  is no longer needed since spectral auth login/refresh handles everything via load_auth_module.
  Delete auth_framework.py and its 25 tests.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove dead run_proxy function after managed storage migration
  ([`0ec4ac9`](https://github.com/spectral-mcp/spectral/commit/0ec4ac99ff89a2dfc3f1e1590d4bcae25631c280))

The proxy now writes to managed storage via run_proxy_to_storage, making run_proxy and its
  write_bundle import unused. Also clarifies that write_bundle in loader.py is now test-only.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove HAR import/export support
  ([`0968106`](https://github.com/spectral-mcp/spectral/commit/0968106cbbad7183d3175d060c50a8c457a927d8))

HAR was redundant with our custom capture bundle format — it added complexity without real value
  since HAR cannot represent UI contexts, binary payloads natively, or WebSocket messages properly.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove Restish, rewrite docs for MCP-first narrative
  ([`be4024d`](https://github.com/spectral-mcp/spectral/commit/be4024def1674f0827c74e01a4466399786567cb))

Restish was REST-only while MCP tools work with any HTTP/JSON API. Remove all Restish code
  (restish.py, config generation, --restish auth mode) and reframe documentation to lead with MCP as
  the primary output, with OpenAPI/GraphQL specs as secondary for human consumption.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Rename schema key "observed" → "examples" and delete _observed_to_examples
  ([`9816dc9`](https://github.com/spectral-mcp/spectral/commit/9816dc9335276eaf8b370ab206185bb41c374a08))

Use "examples" directly in schema inference output instead of "observed", eliminating the pointless
  rename pass in assemble.py.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Replace 50 inline pyright ignores with 8 file-level directives
  ([`758efd5`](https://github.com/spectral-mcp/spectral/commit/758efd5ec547fa61cda1f4304cdab0153b3fd0f9))

Test files legitimately access private functions for unit testing. Instead of annotating each
  import/call individually, use a single `# pyright: reportPrivateUsage=false` directive per file.
  Also: - Remove `_foo as _foo` aliasing trick on imports (no longer needed) - Remove unused test
  imports (_classify_key_pattern, _collect_map_candidates, _schemas_structurally_similar,
  _MAX_RESPONSE_SCHEMA_CHARS, _MAX_SUMMARY_CHARS) - proxy.py: replace untyped lambda with named
  _sigint_handler function - test_commands.py: replace pyright ignores with cast()

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Replace monolithic analysis with step-based pipeline architecture
  ([`cc82e4f`](https://github.com/spectral-mcp/spectral/commit/cc82e4fec76ed4a8682fb2413c79b6a0864d6912))

Replace llm.py, spec_builder.py, and validator.py with a modular Step[In,Out] pipeline: 10 typed
  steps (4 LLM, 6 mechanical) with validation, retry, and parallel branches via asyncio.gather. Add
  schema inference module, shared utilities, investigation tools, and per-step documentation.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Restructure CLI into openapi/graphql/mcp command groups
  ([`959783b`](https://github.com/spectral-mcp/spectral/commit/959783b0b4e1c50210ac5c9a73c76cd887db3696))

Replace the monolithic `analyze` command with protocol-specific groups: - `spectral openapi analyze`
  for REST (OpenAPI output) - `spectral graphql analyze` for GraphQL (SDL output) - `spectral mcp
  analyze` for MCP tool generation - `spectral mcp stdio` for the MCP server

Move login/refresh from `query` to `auth`, add `auth logout`. Delete the `query` command group
  entirely.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Restructure login fix flow into separate functions
  ([`9ea3c0c`](https://github.com/spectral-mcp/spectral/commit/9ea3c0ceb0b6d9d900d55f3286a26669239fedd8))

Separate the happy path from the fix loop: login() handles the initial attempt, _fix_loop()
  initializes LLM context once and retries, and _request_fix() sends prompts. Eliminates lazy
  variables and the tuple[str, Conversation] return pattern.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Restructure test suite into subdirectories mirroring source layout
  ([`a288c94`](https://github.com/spectral-mcp/spectral/commit/a288c94e6a10ea82d3b99210273477974d6b41e5))

Split 14 flat test files (5347 lines) into 25 files across 8 subdirectories (formats/, capture/,
  analyze/, analyze/steps/, analyze/steps/rest/, analyze/steps/graphql/, helpers/, android/, cli/)
  to improve discoverability and maintainability. Deduplicated reset_llm_globals fixture into root
  conftest.py and extracted shared GraphQL test helpers into a subdirectory conftest. All 373 tests
  pass, zero lint/type errors.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Simplify _strip_non_leaf_observed into single generic recursion
  ([`0906bab`](https://github.com/spectral-mcp/spectral/commit/0906babd470381d67e9bc5ac805ce339a870f73f))

Replace _strip_non_leaf_observed + _strip_observed_from_items (~57 lines) with one ~20-line
  recursive function that handles all schema node types uniformly: strip observed from object/array
  nodes, recurse into children (properties, additionalProperties, items), leave leaf scalars as-is.

Add regression tests for array-of-objects recursion and additionalProperties array items.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Simplify GraphQL detection in MITM proxy
  ([`4831f86`](https://github.com/spectral-mcp/spectral/commit/4831f86f1bb72be4faea45fdaa5eb8b7c53e2c72))

Remove URL regex and body keyword heuristics from __typename injection. The graphql-core parser in
  inject_typename() already serves as the definitive detector, matching the approach used by the
  Chrome extension.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Simplify Step classes and centralize model in llm.py
  ([`2084559`](https://github.com/spectral-mcp/spectral/commit/20845591ed13f25ec3321505f24cd8e5802e0c8f))

Merge LLMStep/MechanicalStep into a single Step class — the retry mechanism was dead code (never
  triggered in practice). Centralize the LLM model in llm.init(model=...) instead of threading it
  through the entire pipeline. Add early truncation detection (max_tokens) in llm.ask() with an
  actionable error message.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Simplify URL counting in detect_base_url
  ([`2ec2191`](https://github.com/spectral-mcp/spectral/commit/2ec219135f89dc9da78aa292afecf69310060cdd))

Use tuples instead of MethodUrlPair for the local Counter, with direct unpacking in the
  comprehension. MethodUrlPair stays exported for group_endpoints.py consumers.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Split auth helper into two-layer architecture with static framework
  ([`bde39d7`](https://github.com/spectral-mcp/spectral/commit/bde39d70926ba76cb368e61389f3fbfdee64401c))

Separate LLM-generated acquire/refresh functions from static framework code (token caching, CLI arg
  parsing, file output). Add cost estimation to analyze output, map candidate resolution in REST
  pipeline, and type improvements across schemas/utils/types modules.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Split CLAUDE.md into scoped rule files
  ([`7d0d8ee`](https://github.com/spectral-mcp/spectral/commit/7d0d8eec4697e5dede5cb0f5b2ad3edc520a3b1a))

Move extension-specific and CLI-specific instructions into .claude/rules/ with path scoping so they
  only load when working on the relevant part of the codebase (812 → 137 lines always loaded).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Split CLI commands out of main.py into per-module cmd.py files
  ([`d6f979b`](https://github.com/spectral-mcp/spectral/commit/d6f979b497792bbb51d7888c6e3ca269b85b521c))

Move each command into its respective module (analyze, generate, capture, client, android) leaving
  main.py as a thin ~30-line entry point that defines the Click group and registers commands. Also
  moves cli/client.py into a cli/client/ package with re-export for backward compatibility.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Split discovery into separate command, proxy MITMs all by default
  ([`9f4a2d8`](https://github.com/spectral-mcp/spectral/commit/9f4a2d86a54660af3ae780964d30d12d8e14cc5a))

Extract _run_mitmproxy shared helper, add run_discover() engine function, and simplify run_proxy()
  to always capture. Discovery is now its own `capture discover` subcommand. Remove click.echo from
  engine functions.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Split enrichment into parallel per-endpoint LLM calls
  ([`f47141b`](https://github.com/spectral-mcp/spectral/commit/f47141b23bf3451523b34e537deb483cfae3d342))

Replace the single batch LLM call (EnrichAndContextStep) with N parallel per-endpoint calls
  (EnrichEndpointsStep). Each call focuses on one endpoint, producing higher-quality business
  semantics. Failures are isolated — one endpoint failing doesn't affect others.

Remove business_context, business_glossary, and api_name from the pipeline and ApiSpec format —
  these were produced by the batch call and are no longer inferred. spec.name now comes directly
  from the capture bundle app name.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Split json schema inference into pure sync + async analysis layers
  ([`4fffcdd`](https://github.com/spectral-mcp/spectral/commit/4fffcddbc16241b079e6ef6a12397ae5d67e89c0))

Separate _schema_inference (pure mechanical infer_schema) from _schema_analysis (async
  analyze_schema with map detection + LLM resolution). Make all submodules private, expose only 5
  public symbols from cli.helpers.json.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Split llm.py into cli/helpers/llm/ package with Conversation class
  ([`cd75adc`](https://github.com/spectral-mcp/spectral/commit/cd75adcba9309b8f14c0fca036c6bd4831eb0c29))

Dissolve the monolithic llm.py (695 lines) into focused modules: - _client.py: model config and
  Anthropic client - _conversation.py: Conversation class encapsulating multi-turn tool use -
  _cost.py: token usage tracking and cost estimation - _debug.py: debug logging setup - _utils.py:
  text extraction helpers - tools/: tool definitions and executors (moved from llm_tools.py +
  investigation.py)

Also: move imports to file top per new import convention, remove _print_usage from auth cmd, pass
  CaptureBundle through to auth analyze.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Unify internal dataclass files to types.py convention
  ([`0574ecd`](https://github.com/spectral-mcp/spectral/commit/0574ecd5ac5e20d9d0b5ee34b594befb5b53981f))

Rename capture/models.py → capture/types.py and move Correlation from correlator.py into
  analyze/steps/types.py so all internal dataclass files follow the same types.py naming convention.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Testing

- Add GraphQL alias handling test for extraction
  ([`151edaa`](https://github.com/spectral-mcp/spectral/commit/151edaae2d54e1d66144ca3c1652898f8f815247))

Verify that aliases in queries read values from aliased response keys but store fields under their
  real schema names, preventing silent regressions in alias support.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

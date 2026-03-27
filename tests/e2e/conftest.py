"""E2E test fixtures: Flask server, MITM proxy capture, LLM analysis."""
# pyright: reportPrivateUsage=false, reportUnusedFunction=false

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import socket
import threading
import time
from typing import TYPE_CHECKING, Generator

import pytest

from tests.e2e.client import run_client
from tests.e2e.server import app as flask_app

if TYPE_CHECKING:
    from cli.formats.mcp_tool import ToolDefinition

# --------------------------------------------------------------------------- #
# CLI option: --run-e2e
# --------------------------------------------------------------------------- #

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-e2e", action="store_true", default=False, help="Run E2E tests")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-e2e"):
        return
    skip = pytest.mark.skip(reason="E2E tests need --run-e2e")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise TimeoutError(f"Port {port} not ready after {timeout}s")


# --------------------------------------------------------------------------- #
# SPECTRAL_HOME — isolated storage with real LLM config
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def spectral_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    home = tmp_path_factory.mktemp("spectral_home")
    real_config = Path.home() / ".local" / "share" / "spectral" / "config.json"
    if not real_config.exists():
        pytest.skip("No LLM config at ~/.local/share/spectral/config.json — run 'spectral config' first")
    shutil.copy(real_config, home / "config.json")
    return home


@pytest.fixture(scope="session", autouse=True)
def _set_spectral_home(spectral_home: Path) -> Generator[None, None, None]:
    old = os.environ.get("SPECTRAL_HOME")
    os.environ["SPECTRAL_HOME"] = str(spectral_home)
    yield
    if old is None:
        os.environ.pop("SPECTRAL_HOME", None)
    else:
        os.environ["SPECTRAL_HOME"] = old


# --------------------------------------------------------------------------- #
# Flask test server
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def flask_server() -> Generator[tuple[str, int], None, None]:
    from werkzeug.serving import make_server

    port = _find_free_port()
    server = make_server("127.0.0.1", port, flask_app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _wait_for_port(port)
    yield ("127.0.0.1", port)
    server.shutdown()


# --------------------------------------------------------------------------- #
# Proxy capture
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def proxy_capture(
    spectral_home: Path, flask_server: tuple[str, int]
) -> Generator[str, None, None]:
    from mitmproxy.options import Options
    from mitmproxy.tools.dump import DumpMaster

    from cli.commands.capture.proxy import CaptureAddon, FixedAppProvider
    import cli.helpers.storage as storage

    app_name = "e2e-test-app"
    host, server_port = flask_server
    proxy_port = _find_free_port()

    app_provider = FixedAppProvider(app_name)
    addon = CaptureAddon(app_provider)

    loop = asyncio.new_event_loop()
    opts = Options(
        listen_port=proxy_port,
        mode=["regular"],
        ssl_insecure=True,
    )
    master = DumpMaster(opts, loop=loop)
    master.addons.add(addon)  # pyright: ignore[reportUnknownMemberType]

    proxy_thread = threading.Thread(
        target=loop.run_until_complete,
        args=(master.run(),),
        daemon=True,
    )
    proxy_thread.start()
    _wait_for_port(proxy_port)

    start_time = time.time()

    base_url = f"http://{host}:{server_port}"
    proxy_url = f"http://127.0.0.1:{proxy_port}"
    run_client(base_url, proxy_url)

    end_time = time.time()

    loop.call_soon_threadsafe(master.shutdown)
    proxy_thread.join(timeout=10)

    bundles = addon.build_bundles_by_app(start_time, end_time)
    storage.ensure_app(app_name)
    for _package, bundle in bundles.items():
        storage.store_capture(bundle, app_name)

    yield app_name


# --------------------------------------------------------------------------- #
# MCP analysis (real LLM calls)
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def analyzed_tools(proxy_capture: str, spectral_home: Path) -> list[ToolDefinition]:
    from click.testing import CliRunner

    from cli.helpers.storage import list_tools
    from cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["mcp", "analyze", proxy_capture])
    assert result.exit_code == 0, f"mcp analyze failed:\n{result.output}"
    tools = list_tools(proxy_capture)
    assert len(tools) >= 1, "No tools generated by mcp analyze"
    return tools

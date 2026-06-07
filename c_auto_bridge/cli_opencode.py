import os
import shutil
import subprocess
import time
import inspect
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from c_auto_bridge.agent.opencode_http import OpencodeHttpClient
from c_auto_bridge.config_opencode import OpenCodeConfig
from c_auto_bridge.config_opencode import missing_opencode_env_vars, parse_opencode_model


class OpencodeServerChecker(Protocol):
    def __call__(self, url: str) -> tuple[bool, str]:
        raise NotImplementedError


class OpencodeServerProcess(Protocol):
    def poll(self) -> int | None:
        raise NotImplementedError

    def terminate(self) -> None:
        raise NotImplementedError


class OpencodeProcessFactory(Protocol):
    def __call__(self, command: list[str]) -> OpencodeServerProcess:
        raise NotImplementedError


class OpencodeConfigClient(Protocol):
    async def list_providers(self, *, workspace: str) -> dict:
        raise NotImplementedError


class OpencodeConfigClientFactory(Protocol):
    def __call__(self, url: str) -> OpencodeConfigClient:
        raise NotImplementedError


REQUIRED_OPENCODE_CAPABILITIES = (
    ("health", "health"),
    ("event stream", "events"),
    ("create session", "create_session"),
    ("prompt async", "prompt_async"),
    ("message read", "session_messages"),
    ("permission reply", "answer_permission"),
    ("abort session", "abort_session"),
)


def opencode_start_checks() -> list[tuple[bool, str]]:
    checks = [
        _check_opencode_env(),
        _check_opencode_cli_path(),
        _check_path("OPENCODE_WORKSPACE", "OpenCode workspace"),
        _check_opencode_server_url(),
    ]
    return checks


def check_opencode_startup_capabilities(
    config: OpenCodeConfig,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> tuple[bool, str]:
    if client_factory is None:
        client_factory = OpencodeHttpClient
    client = client_factory(config.server_url)
    for capability_name, method_name in REQUIRED_OPENCODE_CAPABILITIES:
        if not callable(getattr(client, method_name, None)):
            return False, f"OpenCode required capability is missing: {capability_name}"
    model_passed, model_message = check_opencode_model_available(
        config.server_url,
        config.model,
        workspace=config.workspace,
        client_factory=client_factory,
    )
    if not model_passed:
        return False, model_message
    try:
        import asyncio

        capability_result = asyncio.run(_probe_opencode_startup_capabilities(client, config))
    except Exception as exc:
        capability_name = getattr(exc, "capability_name", None)
        if isinstance(capability_name, str):
            return False, f"OpenCode required capability failed: {capability_name} ({exc})"
        return False, f"OpenCode required capability failed: {exc}"
    if capability_result.configured_agent_available is False:
        return False, f"OpenCode configured agent is not available: {config.agent}"
    return True, "OpenCode required capabilities are present; question capability: disabled"


class _OpencodeStartupCapabilityResult:
    def __init__(self, *, configured_agent_available: bool | None) -> None:
        self.configured_agent_available = configured_agent_available


async def _probe_opencode_startup_capabilities(
    client: Any,
    config: OpenCodeConfig,
) -> _OpencodeStartupCapabilityResult:
    await _probe("health", client.health())
    _probe_event_stream(client, config.workspace)
    configured_agent_available = await _probe_configured_agent(client, config.agent, config.workspace)
    return _OpencodeStartupCapabilityResult(
        configured_agent_available=configured_agent_available,
    )


async def _probe_configured_agent(client: Any, configured_agent: str | None, workspace: str) -> bool | None:
    if configured_agent is None:
        return None
    list_agents = getattr(client, "list_agents", None)
    if not callable(list_agents):
        return None
    agents = await list_agents(workspace=workspace)
    if not isinstance(agents, list):
        return False
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if agent.get("name") == configured_agent or agent.get("id") == configured_agent:
            return True
    return False


async def _probe(capability_name: str, awaitable: Any) -> Any:
    try:
        return await awaitable
    except Exception as exc:
        raise _OpencodeCapabilityProbeError(capability_name, str(exc)) from exc


def _probe_event_stream(client: Any, workspace: str) -> None:
    try:
        events = client.events(workspace=workspace)
        if not inspect.isasyncgen(events) and not hasattr(events, "__aiter__"):
            raise TypeError("events must be an async iterator")
    except Exception as exc:
        raise _OpencodeCapabilityProbeError("event stream", str(exc)) from exc


class _OpencodeCapabilityProbeError(RuntimeError):
    def __init__(self, capability_name: str, message: str) -> None:
        self.capability_name = capability_name
        super().__init__(message)


def check_opencode_server_connection(url: str) -> tuple[bool, str]:
    try:
        import asyncio

        asyncio.run(OpencodeHttpClient(url).health())
    except Exception as exc:
        return False, f"OpenCode Server is not reachable: {exc}"
    return True, "OpenCode Server is reachable"


def check_opencode_model_available(
    url: str,
    model: str | None,
    *,
    workspace: str,
    client_factory: OpencodeConfigClientFactory | None = None,
) -> tuple[bool, str]:
    if model is None:
        return True, "OpenCode model override is not configured"
    try:
        provider_id, model_id = parse_opencode_model(model)
    except ValueError as exc:
        return False, str(exc)

    if client_factory is None:
        client_factory = OpencodeHttpClient
    try:
        import asyncio

        payload = asyncio.run(client_factory(url).list_providers(workspace=workspace))
    except Exception as exc:
        return False, f"OpenCode Server providers are not reachable: {exc}"

    providers = payload.get("all")
    if providers is None:
        providers = payload.get("providers")
    if not isinstance(providers, list):
        return False, "OpenCode Server providers response is invalid"

    provider_ids: list[str] = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        current_provider_id = provider.get("id")
        if not isinstance(current_provider_id, str):
            continue
        provider_ids.append(current_provider_id)
        if current_provider_id != provider_id:
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            return False, f"OpenCode provider has invalid models response: {provider_id}"
        if model_id in models:
            return True, f"OpenCode model is available: {model}"
        available = ", ".join(sorted(models.keys())[:10])
        return False, (
            f"OpenCode model is not loaded by provider {provider_id}: {model_id}"
            f" (available: {available})"
        )

    available_providers = ", ".join(provider_ids)
    return False, (
        f"OpenCode provider is not loaded: {provider_id}"
        f" (available providers: {available_providers})"
    )


def ensure_opencode_server(
    url: str,
    *,
    opencode_server_checker: OpencodeServerChecker | None = None,
    process_factory: OpencodeProcessFactory | None = None,
    sleep: Callable[[float], None] = time.sleep,
    startup_timeout_seconds: float = 10,
) -> OpencodeServerProcess | None:
    opencode_server_checker = opencode_server_checker or check_opencode_server_connection
    process_factory = process_factory or subprocess.Popen
    passed, _ = opencode_server_checker(url)
    if passed:
        return None

    host, port = _local_server_host_port(url)
    try:
        executable = _opencode_executable()
        process = process_factory(
            [executable, "serve", "--port", str(port), "--hostname", host]
        )
    except OSError as exc:
        raise RuntimeError(f"failed to start OpenCode Server: {exc}") from exc

    deadline = time.monotonic() + startup_timeout_seconds
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"OpenCode Server exited before becoming reachable: {exit_code}")
        passed, _ = opencode_server_checker(url)
        if passed:
            return process
        sleep(0.25)

    process.terminate()
    raise RuntimeError(f"OpenCode Server did not become reachable: {url}")


def _check_opencode_env() -> tuple[bool, str]:
    missing = missing_opencode_env_vars()
    if missing:
        return False, f"missing required OpenCode env vars: {', '.join(missing)}"
    return True, "required OpenCode env vars are present"


def _check_opencode_cli_path() -> tuple[bool, str]:
    value = os.environ.get("OPENCODE_CLI_PATH")
    if not value:
        return True, "OpenCode CLI path override is not configured; PATH will be used"
    path = Path(value)
    if not path.exists():
        return False, f"OpenCode CLI path does not exist: {path}"
    return True, f"OpenCode CLI path exists: {path}"


def _check_path(env_var: str, label: str) -> tuple[bool, str]:
    value = os.environ.get(env_var)
    if not value:
        return False, f"{label} path is not configured: {env_var}"
    path = Path(value)
    if not path.exists():
        return False, f"{label} path does not exist: {path}"
    return True, f"{label} path exists: {path}"


def _check_opencode_server_url() -> tuple[bool, str]:
    value = os.environ.get("OPENCODE_SERVER_URL")
    if not value:
        return False, "OpenCode Server URL is not configured: OPENCODE_SERVER_URL"
    if not value.startswith("http://") and not value.startswith("https://"):
        return False, f"OpenCode Server URL must start with http:// or https://: {value}"
    return True, f"OpenCode Server URL is configured: {value}"


def _opencode_executable() -> str:
    configured_path = os.environ.get("OPENCODE_CLI_PATH")
    if configured_path:
        path = Path(configured_path)
        if not path.exists():
            raise RuntimeError(f"configured OpenCode CLI executable was not found: {path}")
        return str(path)

    for name in ("opencode.exe", "opencode.cmd", "opencode"):
        executable = shutil.which(name)
        if executable is not None:
            return executable
    raise RuntimeError("OpenCode CLI executable was not found on PATH")


def _local_server_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme != "http":
        raise RuntimeError(f"cannot start local OpenCode Server for URL: {url}")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise RuntimeError(f"OpenCode Server URL must not include path, query, or fragment: {url}")
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        raise RuntimeError(f"cannot start local OpenCode Server for host: {parsed.hostname}")
    if parsed.port is None:
        raise RuntimeError(f"OpenCode Server URL must include an explicit port: {url}")
    return parsed.hostname, parsed.port

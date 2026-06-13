import os
import shutil
from pathlib import Path

from c_auto_bridge.config_codex import DEFAULT_APPROVAL_POLICY, SUPPORTED_APPROVAL_POLICIES


def codex_start_checks() -> list[tuple[bool, str]]:
    return [
        _check_app_server_connection_path(),
        _check_codex_cli_path(),
        _check_optional_path("CODEX_HOME", "Codex home"),
        _check_optional_path("CODEX_WORKSPACE", "workspace", "bridge process cwd will be used"),
        _check_sandbox(),
        _check_approval_policy(),
    ]


def _check_app_server_connection_path() -> tuple[bool, str]:
    value = os.environ.get("CODEX_APP_SERVER_URL")
    if value:
        return True, f"Codex App Server connection path: explicit WebSocket override ({value})"
    return True, "Codex App Server connection path: default stdio (codex app-server --listen stdio://)"


def _check_codex_cli_path() -> tuple[bool, str]:
    value = os.environ.get("CODEX_CLI_PATH")
    if value:
        path = Path(value)
        if not path.exists():
            return False, f"Codex CLI path does not exist: {path}"
        return True, f"Codex CLI path exists: {path}"
    executable = shutil.which("codex")
    if executable is None:
        return False, "Codex CLI executable was not found on PATH"
    return True, f"Codex CLI executable is available: {executable}"


def _check_optional_path(env_var: str, label: str, fallback: str = "Codex default will be used") -> tuple[bool, str]:
    value = os.environ.get(env_var)
    if not value:
        return True, f"{label} path is not configured; {fallback}"
    path = Path(value)
    if not path.exists():
        return False, f"{label} path does not exist: {path}"
    return True, f"{label} path exists: {path}"


def _check_sandbox() -> tuple[bool, str]:
    value = os.environ.get("CODEX_SANDBOX", "workspace-write")
    if value != "workspace-write":
        return False, f"unsupported Codex sandbox: {value} (only workspace-write is supported)"
    return True, "Codex sandbox is workspace-write"


def _check_approval_policy() -> tuple[bool, str]:
    value = os.environ.get("CODEX_APPROVAL_POLICY")
    if not value:
        return True, f"Codex approval policy is {DEFAULT_APPROVAL_POLICY} (interactive bridge default)"
    if value not in SUPPORTED_APPROVAL_POLICIES:
        return (
            False,
            "unsupported Codex approval policy: "
            f"{value} (supported: {', '.join(sorted(SUPPORTED_APPROVAL_POLICIES))})",
        )
    if value == "never":
        return True, "Codex approval policy is never; approval prompts are disabled"
    return True, f"Codex approval policy is {value}"

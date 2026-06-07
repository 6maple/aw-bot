import os
import shutil
from pathlib import Path

from c_auto_bridge.config_codex import missing_codex_env_vars


def codex_start_checks() -> list[tuple[bool, str]]:
    return [
        _check_codex_env(),
        _check_codex_cli_path(),
        _check_path("CODEX_HOME", "Codex home"),
        _check_path("CODEX_WORKSPACE", "workspace"),
    ]


def _check_codex_env() -> tuple[bool, str]:
    missing = missing_codex_env_vars()
    if missing:
        return False, f"missing required Codex env vars: {', '.join(missing)}"
    return True, "required Codex env vars are present"


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


def _check_path(env_var: str, label: str) -> tuple[bool, str]:
    value = os.environ.get(env_var)
    if not value:
        return False, f"{label} path is not configured: {env_var}"
    path = Path(value)
    if not path.exists():
        return False, f"{label} path does not exist: {path}"
    return True, f"{label} path exists: {path}"

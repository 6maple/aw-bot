from dataclasses import dataclass
import os


DEFAULT_APPROVAL_POLICY = "on-request"
SUPPORTED_APPROVAL_POLICIES = {"never", "on-request", "untrusted"}


@dataclass(frozen=True)
class CodexConfig:
    app_server_url: str | None
    cli_path: str | None
    home: str | None
    workspace: str
    c_auto_skill_path: str | None
    model: str | None
    sandbox: str
    approval_policy: str | None


def load_codex_config() -> CodexConfig:
    sandbox = os.environ.get("CODEX_SANDBOX", "workspace-write")
    if sandbox != "workspace-write":
        raise ValueError(f"unsupported Codex sandbox: {sandbox}")
    return CodexConfig(
        app_server_url=_optional_env("CODEX_APP_SERVER_URL"),
        cli_path=_optional_env("CODEX_CLI_PATH"),
        home=_optional_env("CODEX_HOME"),
        workspace=os.environ.get("CODEX_WORKSPACE", os.getcwd()),
        c_auto_skill_path=_optional_env("CODEX_C_AUTO_SKILL_PATH"),
        model=_optional_env("CODEX_MODEL"),
        sandbox=sandbox,
        approval_policy=_approval_policy(),
    )


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def _approval_policy() -> str:
    value = os.environ.get("CODEX_APPROVAL_POLICY")
    if not value:
        return DEFAULT_APPROVAL_POLICY
    if value not in SUPPORTED_APPROVAL_POLICIES:
        raise ValueError(
            "unsupported Codex approval policy: "
            f"{value} (supported: {', '.join(sorted(SUPPORTED_APPROVAL_POLICIES))})"
        )
    return value

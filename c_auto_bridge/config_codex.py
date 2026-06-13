from dataclasses import dataclass
import os


@dataclass(frozen=True)
class CodexConfig:
    app_server_url: str | None
    cli_path: str | None
    home: str
    workspace: str
    c_auto_skill_path: str | None
    model: str
    models: tuple[str, ...]
    sandbox: str
    approval_policy: str


REQUIRED_ENV_VARS = (
    "CODEX_HOME",
    "CODEX_WORKSPACE",
    "CODEX_MODEL",
    "CODEX_SANDBOX",
    "CODEX_APPROVAL_POLICY",
)


def load_codex_config() -> CodexConfig:
    return CodexConfig(
        app_server_url=os.environ.get("CODEX_APP_SERVER_URL"),
        cli_path=os.environ.get("CODEX_CLI_PATH"),
        home=os.environ["CODEX_HOME"],
        workspace=os.environ["CODEX_WORKSPACE"],
        c_auto_skill_path=os.environ.get("CODEX_C_AUTO_SKILL_PATH"),
        model=os.environ["CODEX_MODEL"],
        models=_codex_models(os.environ.get("CODEX_MODELS"), os.environ["CODEX_MODEL"]),
        sandbox=os.environ["CODEX_SANDBOX"],
        approval_policy=os.environ["CODEX_APPROVAL_POLICY"],
    )


def missing_codex_env_vars() -> list[str]:
    return [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]


def _codex_models(value: str | None, configured_model: str) -> tuple[str, ...]:
    if value is None:
        return (configured_model,)
    models = tuple(model.strip() for model in value.split(",") if model.strip() != "")
    if len(models) == 0:
        raise ValueError("CODEX_MODELS must include at least one model")
    return models

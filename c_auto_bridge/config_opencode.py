from dataclasses import dataclass
import os


@dataclass(frozen=True)
class OpenCodeConfig:
    server_url: str
    workspace: str
    model: str | None
    agent: str | None


REQUIRED_ENV_VARS = (
    "OPENCODE_SERVER_URL",
    "OPENCODE_WORKSPACE",
)


def load_opencode_config() -> OpenCodeConfig:
    return OpenCodeConfig(
        server_url=os.environ["OPENCODE_SERVER_URL"],
        workspace=os.environ["OPENCODE_WORKSPACE"],
        model=os.environ.get("OPENCODE_MODEL"),
        agent=os.environ.get("OPENCODE_AGENT"),
    )


def missing_opencode_env_vars() -> list[str]:
    return [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]


def opencode_model_payload(value: str | None) -> dict[str, str] | None:
    if value is None:
        return None
    provider_id, model_id = parse_opencode_model(value)
    return {"providerID": provider_id, "modelID": model_id}


def parse_opencode_model(value: str) -> tuple[str, str]:
    parts = value.split("/", maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("OPENCODE_MODEL must use provider/model format")
    return parts[0], parts[1]

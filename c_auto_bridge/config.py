from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: str
    default_agent: str


def load_config() -> Config:
    return Config(
        data_dir=os.getenv("C_AUTO_DATA_DIR", ".data"),
        default_agent=os.getenv("C_AUTO_DEFAULT_AGENT", "codex"),
    )


def configured_data_dir() -> Path:
    return Path(os.getenv("C_AUTO_DATA_DIR", ".data"))

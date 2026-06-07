import logging
import os


LOG_LEVEL_ENV_VAR = "C_AUTO_LOG_LEVEL"
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def configure_logging() -> None:
    level_name = os.environ.get(LOG_LEVEL_ENV_VAR)
    level = _parse_log_level(level_name)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def _parse_log_level(value: str | None) -> int:
    if value is None:
        return logging.INFO
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError(f"{LOG_LEVEL_ENV_VAR} must not be empty")
    if normalized not in LOG_LEVELS:
        valid_values = ", ".join(LOG_LEVELS)
        raise ValueError(f"{LOG_LEVEL_ENV_VAR} must be one of: {valid_values}")
    return LOG_LEVELS[normalized]

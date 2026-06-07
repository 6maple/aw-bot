import argparse
import logging
import os

from dotenv import load_dotenv

from c_auto_bridge.cli_codex import codex_start_checks
from c_auto_bridge.cli_opencode import (
    check_opencode_startup_capabilities,
    ensure_opencode_server,
    opencode_start_checks,
)
from c_auto_bridge.app.runtime import build_runtime, start_runtime, stop_runtime
from c_auto_bridge.config import configured_data_dir, load_config
from c_auto_bridge.config_opencode import load_opencode_config
from c_auto_bridge.store.file_store import FileStore
from c_auto_bridge.utils.log import configure_logging


logger = logging.getLogger(__name__)


def main() -> int:
    load_dotenv(".env")
    load_dotenv(".env.local", override=True)
    configure_logging()

    parser = argparse.ArgumentParser(prog="c-auto-bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor")
    subparsers.add_parser("start")
    args = parser.parse_args()

    if args.command == "doctor":
        return doctor()
    if args.command == "start":
        return start()
    raise ValueError(f"unknown command: {args.command}")


def doctor() -> int:
    checks = validate_start_environment()
    _print_checks(checks)
    return 0 if all(passed for passed, _ in checks) else 1


def start() -> int:
    logger.info("starting c-auto bridge")
    checks = validate_start_environment()
    if not all(passed for passed, _ in checks):
        logger.error("startup environment validation failed")
        _print_checks(checks)
        return 1

    config = load_config()
    server_process = None
    if config.default_agent == "opencode":
        opencode_config = load_opencode_config()
        try:
            server_process = ensure_opencode_server(opencode_config.server_url)
        except RuntimeError as exc:
            logger.error("failed to ensure OpenCode Server: %s", exc)
            print(f"[FAIL] {exc}")
            return 1
        capability_passed, capability_message = check_opencode_startup_capabilities(opencode_config)
        if not capability_passed:
            logger.error("OpenCode startup capability validation failed: %s", capability_message)
            print(f"[FAIL] {capability_message}")
            return 1
    app_id = os.environ["LARK_APP_ID"]
    app_secret = os.environ["LARK_APP_SECRET"]
    components = build_runtime(config, app_id=app_id, app_secret=app_secret)
    try:
        logger.info("starting runtime")
        start_runtime(components)
    finally:
        logger.info("stopping runtime")
        stop_runtime(components)
        if server_process is not None:
            logger.info("terminating managed Agent Server")
            server_process.terminate()
    return 0


def validate_start_environment() -> list[tuple[bool, str]]:
    checks = [
        _check_lark_env(),
        _check_data_dir(),
    ]
    agent = os.getenv("C_AUTO_DEFAULT_AGENT", "codex")
    if agent == "codex":
        checks.extend(codex_start_checks())
    elif agent == "opencode":
        checks.extend(opencode_start_checks())
    else:
        checks.append((False, f"unsupported default agent: {agent}"))
    return checks


def _print_checks(checks: list[tuple[bool, str]]) -> None:
    for passed, text in checks:
        marker = "OK" if passed else "FAIL"
        print(f"[{marker}] {text}")


def _check_lark_env() -> tuple[bool, str]:
    missing = [name for name in ("LARK_APP_ID", "LARK_APP_SECRET") if not os.environ.get(name)]
    if missing:
        return False, f"missing required Feishu env vars: {', '.join(missing)}"
    return True, "required Feishu env vars are present"


def _check_data_dir() -> tuple[bool, str]:
    data_dir = configured_data_dir()
    try:
        FileStore(data_dir).initialize()
    except OSError as exc:
        return False, f"data dir is not writable: {data_dir} ({exc})"
    return True, f"data dir is writable: {data_dir}"


if __name__ == "__main__":
    raise SystemExit(main())

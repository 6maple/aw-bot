import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


REPLACE_ATTEMPTS = 5
REPLACE_RETRY_SECONDS = 0.05


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    try:
        _replace_with_retry(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replace_with_retry(tmp_path: Path, path: Path) -> None:
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_RETRY_SECONDS)

from typing import Any


CLIENT_INFO = {"name": "aw-bot", "title": "aw-bot", "version": "0.1.0"}


class JsonRpcError(RuntimeError):
    def __init__(self, error: dict[str, Any]):
        self.error = error
        super().__init__(str(error))

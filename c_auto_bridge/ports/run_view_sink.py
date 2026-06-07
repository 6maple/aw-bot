from typing import Protocol

from c_auto_bridge.core.run_view import RunView


class RunViewSinkPort(Protocol):
    async def publish(self, *, private_chat_scope_id: str, run_view: RunView) -> None:
        ...

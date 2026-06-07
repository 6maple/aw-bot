import asyncio
from collections.abc import Awaitable, Callable


class PendingQueue:
    def __init__(
        self,
        dispatch: Callable[[str, str, str], Awaitable[None]],
        *,
        is_active: Callable[[str], bool],
        debounce_seconds: float = 0.6,
    ):
        self.dispatch = dispatch
        self.is_active = is_active
        self.debounce_seconds = debounce_seconds
        self._pending: dict[str, list[tuple[str, str]]] = {}
        self._workers: dict[str, asyncio.Task] = {}

    def submit(self, scope_id: str, user_id: str, text: str) -> None:
        self._pending.setdefault(scope_id, []).append((user_id, text))
        if scope_id not in self._workers:
            self._workers[scope_id] = asyncio.create_task(self._worker(scope_id))

    async def close(self) -> None:
        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

    async def _worker(self, scope_id: str) -> None:
        try:
            while scope_id in self._pending:
                while self.is_active(scope_id):
                    await asyncio.sleep(self.debounce_seconds)
                await asyncio.sleep(self.debounce_seconds)
                items = self._pending.pop(scope_id)
                user_id = items[-1][0]
                text = "\n".join(item[1] for item in items)
                await self.dispatch(scope_id, user_id, text)
        finally:
            self._workers.pop(scope_id, None)
            if scope_id in self._pending:
                self._workers[scope_id] = asyncio.create_task(self._worker(scope_id))

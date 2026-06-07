import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol


class IdleTimeoutHandle(Protocol):
    def cancel(self) -> None:
        ...


class IdleTimeoutScheduler(Protocol):
    def schedule(
        self,
        *,
        delay_seconds: float,
        callback: Callable[[], Awaitable[None]],
    ) -> IdleTimeoutHandle:
        ...


class AsyncioIdleTimeoutScheduler:
    def schedule(
        self,
        *,
        delay_seconds: float,
        callback: Callable[[], Awaitable[None]],
    ) -> IdleTimeoutHandle:
        loop = asyncio.get_running_loop()
        return loop.call_later(
            delay_seconds,
            lambda: asyncio.create_task(callback()),
        )

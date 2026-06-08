import asyncio
import json
from collections.abc import Awaitable, Callable, AsyncIterator
from typing import Any, Protocol

from c_auto_bridge.agent.codex_jsonrpc import CLIENT_INFO, JsonRpcError


class CodexWebSocket(Protocol):
    async def send(self, data: str) -> None:
        raise NotImplementedError

    async def recv(self) -> str:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class CodexWebSocketClient:
    def __init__(
        self,
        *,
        url: str,
        executable: str | None,
        codex_home: str | None,
        connector: Callable[[str], Awaitable[CodexWebSocket]] | None = None,
    ) -> None:
        self.url = url
        self.executable = executable
        self.codex_home = codex_home
        self.connector = connector
        self.websocket: CodexWebSocket | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        if self.websocket is not None:
            return
        await self._connect_websocket()
        self._reader_task = asyncio.create_task(self._read_messages())

    async def initialize(self) -> dict[str, Any]:
        result = await self.request(
            "initialize",
            {
                "clientInfo": CLIENT_INFO,
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.notify("initialized", {})
        return result

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._write({"id": request_id, "method": method, "params": params})
        return await future

    async def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        await self._write({"id": request_id, "result": result})

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"method": method, "params": params})

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await self._events.get()

    async def close(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
        if self._reader_task is not None:
            await asyncio.gather(self._reader_task, return_exceptions=True)
        self.websocket = None
        self._reader_task = None

    async def _connect_websocket(self) -> None:
        connector = self.connector or _connect_websocket
        self.websocket = await connector(self.url)

    async def _write(self, message: dict[str, Any]) -> None:
        if self.websocket is None:
            raise RuntimeError("Codex App Server is not connected")
        await self.websocket.send(json.dumps(message, ensure_ascii=False))

    async def _read_messages(self) -> None:
        if self.websocket is None:
            raise RuntimeError("Codex App Server is not connected")
        while True:
            try:
                raw = await self.websocket.recv()
            except Exception:
                break
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise TypeError("Codex App Server message must be a dict")
            request_id = message.get("id")
            if request_id in self._pending and "method" not in message:
                future = self._pending.pop(request_id)
                if "error" in message:
                    future.set_exception(JsonRpcError(message["error"]))
                else:
                    result = message.get("result")
                    if not isinstance(result, dict):
                        future.set_exception(TypeError("Codex RPC result must be a dict"))
                    else:
                        future.set_result(result)
                continue
            await self._events.put(message)
        error = RuntimeError("Codex App Server connection closed")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()


async def _connect_websocket(url: str) -> CodexWebSocket:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("websockets is required for CODEX_APP_SERVER_URL") from exc
    return await websockets.connect(url)

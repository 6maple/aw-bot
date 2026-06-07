import asyncio
import json
import os
from collections.abc import Awaitable, Callable, AsyncIterator
from typing import Any, Protocol

from c_auto_bridge.agent.codex_jsonrpc import CLIENT_INFO, JsonRpcError
from c_auto_bridge.agent.codex_stdio import _find_codex_executable


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
        codex_home: str,
        connector: Callable[[str], Awaitable[CodexWebSocket]] | None = None,
        process_factory: Callable[..., Awaitable[asyncio.subprocess.Process]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        startup_timeout_seconds: float = 10,
    ) -> None:
        self.url = url
        self.executable = executable
        self.codex_home = codex_home
        self.connector = connector
        self.process_factory = process_factory
        self.sleep = sleep
        self.startup_timeout_seconds = startup_timeout_seconds
        self.websocket: CodexWebSocket | None = None
        self.process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        if self.websocket is not None:
            return
        try:
            await self._connect_websocket()
        except Exception:
            await self._start_managed_server()
            await self._wait_for_managed_server()
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
        if self.process is not None:
            self.process.terminate()
            await self.process.wait()
        self.websocket = None
        self.process = None
        self._reader_task = None

    async def _connect_websocket(self) -> None:
        connector = self.connector or _connect_websocket
        self.websocket = await connector(self.url)

    async def _start_managed_server(self) -> None:
        executable = _find_codex_executable(self.executable)
        if executable is None:
            raise RuntimeError("Codex CLI executable was not found on PATH")
        env = os.environ.copy()
        env["CODEX_HOME"] = self.codex_home
        process_factory = self.process_factory or asyncio.create_subprocess_exec
        self.process = await process_factory(
            executable,
            "app-server",
            "--listen",
            self.url,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )

    async def _wait_for_managed_server(self) -> None:
        deadline = asyncio.get_running_loop().time() + self.startup_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if self.process is not None and self.process.returncode is not None:
                raise RuntimeError(
                    f"Codex App Server exited before becoming reachable: {self.process.returncode}"
                )
            try:
                await self._connect_websocket()
                return
            except Exception:
                await self.sleep(0.25)
        if self.process is not None:
            self.process.terminate()
        raise RuntimeError(f"Codex App Server did not become reachable: {self.url}")

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

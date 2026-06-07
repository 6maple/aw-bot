import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from c_auto_bridge.agent.codex_jsonrpc import CLIENT_INFO, JsonRpcError


class CodexStdioClient:
    def __init__(self, *, executable: str | None, codex_home: str):
        self.executable = executable
        self.codex_home = codex_home
        self.process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        if self.process is not None:
            return
        executable = _find_codex_executable(self.executable)
        if executable is None:
            raise RuntimeError("Codex CLI executable was not found on PATH")
        env = os.environ.copy()
        env["CODEX_HOME"] = self.codex_home
        self.process = await asyncio.create_subprocess_exec(
            executable,
            "app-server",
            "--listen",
            "stdio://",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
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
        if self.process is None:
            return
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5)
        except TimeoutError:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self._reader_task is not None:
            await asyncio.gather(self._reader_task, return_exceptions=True)
        self.process = None
        self._reader_task = None

    async def _write(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("Codex App Server is not connected")
        self.process.stdin.write(
            json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        )
        await self.process.stdin.drain()

    async def _read_messages(self) -> None:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("Codex App Server is not connected")
        while line := await self.process.stdout.readline():
            message = json.loads(line)
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


def _find_codex_executable(configured: str | None = None) -> str | None:
    if configured is not None and Path(configured).suffix.lower() == ".exe":
        return configured
    node = shutil.which("node.exe")
    if node is not None:
        node_root = Path(node).resolve().parent
        binaries = sorted(
            node_root.glob(
                "node_modules/@openai/codex/node_modules/@openai/"
                "codex-*/vendor/*/bin/codex.exe"
            )
        )
        if binaries:
            return str(binaries[0])
    return configured or shutil.which("codex")

import asyncio
import unittest
from unittest.mock import patch

from c_auto_bridge.agent.codex_websocket import CodexWebSocketClient


class CodexWebSocketClientTest(unittest.TestCase):
    def test_reuses_running_app_server(self) -> None:
        async def run() -> None:
            websocket = FakeWebSocket()

            async def connector(url: str):
                return websocket

            async def fail_process_factory(*args, **kwargs):
                raise AssertionError("app-server should not be started")

            client = CodexWebSocketClient(
                url="ws://127.0.0.1:4500",
                executable="codex",
                codex_home="home",
                connector=connector,
                process_factory=fail_process_factory,
            )
            await client.connect()
            await client.close()

        asyncio.run(run())

    def test_starts_app_server_after_connection_failure(self) -> None:
        async def run() -> None:
            websocket = FakeWebSocket()
            calls = []

            async def connector(url: str):
                calls.append(("connect", url))
                if len(calls) == 1:
                    raise OSError("not listening")
                return websocket

            async def process_factory(*args, **kwargs):
                calls.append(("process", args))
                return FakeProcess()

            with patch("c_auto_bridge.agent.codex_websocket._find_codex_executable", return_value="codex"):
                client = CodexWebSocketClient(
                    url="ws://127.0.0.1:4500",
                    executable="codex",
                    codex_home="home",
                    connector=connector,
                    process_factory=process_factory,
                    sleep=lambda seconds: asyncio.sleep(0),
                )
                await client.connect()
                await client.close()

            self.assertEqual(calls[0], ("connect", "ws://127.0.0.1:4500"))
            self.assertEqual(calls[1][0], "process")
            self.assertEqual(calls[2], ("connect", "ws://127.0.0.1:4500"))

        asyncio.run(run())


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False

    async def send(self, data: str) -> None:
        return None

    async def recv(self) -> str:
        while not self.closed:
            await asyncio.sleep(0)
        raise RuntimeError("closed")

    async def close(self) -> None:
        self.closed = True


class FakeProcess:
    returncode = None

    def terminate(self) -> None:
        self.returncode = 0

    async def wait(self) -> int:
        return 0


if __name__ == "__main__":
    unittest.main()

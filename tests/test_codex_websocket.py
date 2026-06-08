import asyncio
import unittest
from unittest.mock import patch

from c_auto_bridge.agent.codex_websocket import CodexWebSocketClient


class CodexWebSocketClientTest(unittest.TestCase):
    def test_reuses_running_app_server(self) -> None:
        async def run() -> None:
            websocket = FakeWebSocket()
            calls = []

            async def connector(url: str):
                calls.append(("connect", url))
                return websocket

            async def fail_process_factory(*args, **kwargs):
                raise AssertionError("WebSocket override must not start a managed app-server")

            with patch("c_auto_bridge.agent.codex_websocket.asyncio.create_subprocess_exec", fail_process_factory):
                client = CodexWebSocketClient(
                    url="ws://127.0.0.1:4500",
                    executable="codex",
                    codex_home="home",
                    connector=connector,
                )
                await client.connect()
                await client.close()

            self.assertEqual(calls, [("connect", "ws://127.0.0.1:4500")])

        asyncio.run(run())

    def test_connection_failure_does_not_start_managed_app_server(self) -> None:
        async def run() -> None:
            calls = []

            async def connector(url: str):
                calls.append(("connect", url))
                raise OSError("not listening")

            async def fail_process_factory(*args, **kwargs):
                raise AssertionError("WebSocket override must not start a managed app-server")

            with patch("c_auto_bridge.agent.codex_websocket.asyncio.create_subprocess_exec", fail_process_factory):
                client = CodexWebSocketClient(
                    url="ws://127.0.0.1:4500",
                    executable="codex",
                    codex_home="home",
                    connector=connector,
                )
                with self.assertRaisesRegex(OSError, "not listening"):
                    await client.connect()

            self.assertEqual(calls, [("connect", "ws://127.0.0.1:4500")])

        asyncio.run(run())

    def test_unset_codex_home_does_not_create_process_environment(self) -> None:
        async def run() -> None:
            websocket = FakeWebSocket()
            calls = []

            async def connector(url: str):
                calls.append(("connect", url))
                return websocket

            async def fail_process_factory(*args, **kwargs):
                raise AssertionError("WebSocket override must not create a Codex process environment")

            with (
                patch.dict("os.environ", {}, clear=True),
                patch("c_auto_bridge.agent.codex_websocket.asyncio.create_subprocess_exec", fail_process_factory),
            ):
                client = CodexWebSocketClient(
                    url="ws://127.0.0.1:4500",
                    executable="codex",
                    codex_home=None,
                    connector=connector,
                )
                await client.connect()
                await client.close()

            self.assertEqual(calls, [("connect", "ws://127.0.0.1:4500")])

        asyncio.run(run())

    def test_configured_codex_home_is_retained_without_starting_process(self) -> None:
        async def run() -> None:
            websocket = FakeWebSocket()

            async def connector(url: str):
                return websocket

            async def fail_process_factory(*args, **kwargs):
                raise AssertionError("WebSocket override must not inject CODEX_HOME into a managed process")

            with patch("c_auto_bridge.agent.codex_websocket.asyncio.create_subprocess_exec", fail_process_factory):
                client = CodexWebSocketClient(
                    url="ws://127.0.0.1:4500",
                    executable="codex",
                    codex_home="/tmp/codex-home",
                    connector=connector,
                )
                await client.connect()
                await client.close()

            self.assertEqual(client.codex_home, "/tmp/codex-home")

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


if __name__ == "__main__":
    unittest.main()

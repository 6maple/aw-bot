import asyncio
import json
import unittest
from unittest.mock import patch

from c_auto_bridge.agent.codex_stdio import CodexStdioClient


class CodexStdioClientTest(unittest.TestCase):
    def test_uses_single_bidirectional_stdio_connection(self) -> None:
        async def run() -> None:
            process = FakeProcess()
            calls = []

            async def process_factory(*args, **kwargs):
                calls.append((args, kwargs))
                return process

            with patch("c_auto_bridge.agent.codex_stdio.asyncio.create_subprocess_exec", process_factory):
                client = CodexStdioClient(executable="codex", codex_home="home")
                await client.connect()
                initialize = asyncio.create_task(client.initialize())
                await asyncio.sleep(0)
                process.stdout.feed_data(b'{"id":1,"result":{"userAgent":"codex"}}\n')
                self.assertEqual(await initialize, {"userAgent": "codex"})
                process.stdout.feed_data(b'{"id":9,"method":"item/fileChange/requestApproval","params":{}}\n')
                self.assertEqual((await anext(client.listen()))["id"], 9)
                await client.respond(9, {"decision": "accept"})
                await client.close()

            sent = [json.loads(line) for line in process.stdin.lines]
            self.assertEqual(sent[0]["method"], "initialize")
            self.assertEqual(sent[1]["method"], "initialized")
            self.assertEqual(sent[2], {"id": 9, "result": {"decision": "accept"}})
            self.assertEqual(calls[0][0][:4], ("codex", "app-server", "--listen", "stdio://"))
            self.assertEqual(calls[0][1]["env"]["CODEX_HOME"], "home")

        asyncio.run(run())

    def test_omits_codex_home_from_process_environment_when_unset(self) -> None:
        async def run() -> None:
            process = FakeProcess()
            captured_env = {}

            async def process_factory(*args, **kwargs):
                captured_env.update(kwargs["env"])
                return process

            with (
                patch.dict("os.environ", {}, clear=True),
                patch("c_auto_bridge.agent.codex_stdio.asyncio.create_subprocess_exec", process_factory),
            ):
                client = CodexStdioClient(executable="codex", codex_home=None)
                await client.connect()
                await client.close()

            self.assertNotIn("CODEX_HOME", captured_env)

        asyncio.run(run())


class FakeWriter:
    def __init__(self):
        self.lines = []

    def write(self, data):
        self.lines.append(data.decode("utf-8"))

    async def drain(self):
        return None

    def close(self):
        return None


class FakeProcess:
    def __init__(self):
        self.stdin = FakeWriter()
        self.stdout = asyncio.StreamReader()

    def terminate(self):
        self.stdout.feed_eof()

    def kill(self):
        self.stdout.feed_eof()

    async def wait(self):
        self.stdout.feed_eof()
        return 0


if __name__ == "__main__":
    unittest.main()

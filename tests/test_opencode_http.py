import json
import os
import unittest
from unittest.mock import patch

from c_auto_bridge.agent.opencode_http import OpencodeHttpClient


class OpencodeHttpClientTest(unittest.TestCase):
    def test_health_uses_global_health_endpoint(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"healthy": true, "version": "1.0.0"}'
            )

            import asyncio

            result = asyncio.run(client.health())

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:4096/global/health")
        self.assertEqual(result, {"healthy": True, "version": "1.0.0"})

    def test_create_session_uses_session_endpoint(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"id": "session_1"}'

            import asyncio

            result = asyncio.run(client.create_session(title="Bridge Session", workspace="D:/repo with space"))

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:4096/session?directory=D%3A%2Frepo+with+space",
        )
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"title": "Bridge Session"})
        self.assertEqual(result, {"id": "session_1"})

    def test_session_messages_uses_session_message_endpoint(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"[]"

            import asyncio

            result = asyncio.run(client.session_messages(session_id="session/1", workspace="D:/repo"))

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:4096/session/session%2F1/message?directory=D%3A%2Frepo",
        )
        self.assertEqual(result, [])

    def test_session_messages_supports_limited_backfill_scope(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"[]"

            import asyncio

            asyncio.run(client.session_messages(session_id="session/1", workspace="D:/repo", limit=2))

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:4096/session/session%2F1/message?limit=2&directory=D%3A%2Frepo",
        )

    def test_session_message_uses_single_message_endpoint(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"info": {"id": "msg_1"}, "parts": []}'

            import asyncio

            result = asyncio.run(client.session_message(session_id="session/1", message_id="msg/1", workspace="D:/repo"))

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:4096/session/session%2F1/message/msg%2F1?directory=D%3A%2Frepo",
        )
        self.assertEqual(result, {"info": {"id": "msg_1"}, "parts": []})

    def test_uses_basic_auth_when_server_password_is_configured(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with (
            patch.dict(os.environ, {"OPENCODE_SERVER_PASSWORD": "secret"}, clear=True),
            patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen,
        ):
            urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"healthy": true}'
            )

            import asyncio

            asyncio.run(client.health())

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            "Basic b3BlbmNvZGU6c2VjcmV0",
        )

    def test_uses_configured_basic_auth_username(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with (
            patch.dict(
                os.environ,
                {
                    "OPENCODE_SERVER_USERNAME": "bot",
                    "OPENCODE_SERVER_PASSWORD": "secret",
                },
                clear=True,
            ),
            patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen,
        ):
            urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"healthy": true}'
            )

            import asyncio

            asyncio.run(client.health())

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            "Basic Ym90OnNlY3JldA==",
        )

    def test_answer_permission_uses_current_permission_reply_route(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"true"

            import asyncio

            result = asyncio.run(
                client.answer_permission(
                    session_id="session/1",
                    permission_id="perm/1",
                    decision="once",
                    workspace="D:/repo",
                )
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:4096/permission/perm%2F1/reply?directory=D%3A%2Frepo",
        )
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"reply": "once"})
        self.assertTrue(result)

    def test_answer_question_uses_official_reply_payload(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"true"

            import asyncio

            result = asyncio.run(
                client.answer_question(
                    question_id="que/1",
                    answers=[["src/app.py"]],
                    workspace="D:/repo",
                )
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:4096/question/que%2F1/reply?directory=D%3A%2Frepo",
        )
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"answers": [["src/app.py"]]})
        self.assertTrue(result)

    def test_abort_session_uses_abort_endpoint(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"true"

            import asyncio

            result = asyncio.run(client.abort_session(session_id="session/1", workspace="D:/repo"))

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:4096/session/session%2F1/abort?directory=D%3A%2Frepo",
        )
        self.assertTrue(result)

    def test_prompt_async_uses_async_endpoint_and_message_id(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b""

            import asyncio

            result = asyncio.run(
                client.prompt_async(
                    session_id="session/1",
                    message_id="msg_1",
                    text="hi",
                    model={"providerID": "test-provider", "modelID": "test-model"},
                    agent="build",
                    workspace="D:/repo",
                )
            )

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:4096/session/session%2F1/prompt_async?directory=D%3A%2Frepo",
        )
        self.assertEqual(body["messageID"], "msg_1")
        self.assertEqual(body["parts"], [{"type": "text", "text": "hi"}])
        self.assertTrue(result)

    def test_list_providers_uses_runtime_provider_endpoint(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"all": [], "default": {}, "connected": []}'

            import asyncio

            result = asyncio.run(client.list_providers(workspace="D:/repo"))

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:4096/provider?directory=D%3A%2Frepo")
        self.assertEqual(result, {"all": [], "default": {}, "connected": []})

    def test_list_agents_uses_agent_endpoint(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        with patch("c_auto_bridge.agent.opencode_http.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"[]"

            import asyncio

            result = asyncio.run(client.list_agents(workspace="D:/repo"))

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:4096/agent?directory=D%3A%2Frepo")
        self.assertEqual(result, [])

    def test_events_uses_workspace_scoped_event_endpoint(self) -> None:
        client = OpencodeHttpClient("http://127.0.0.1:4096")

        class FakeResponse:
            def __enter__(self):
                return [b'data: {"type":"session.idle","properties":{"sessionID":"s"}}\n', b"\n"]

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("c_auto_bridge.agent.opencode_http.urlopen", return_value=FakeResponse()) as urlopen:
            event = next(client._sync_events(workspace="D:/repo"))

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:4096/event?directory=D%3A%2Frepo")
        self.assertEqual(event, {"type": "session.idle", "properties": {"sessionID": "s"}})


if __name__ == "__main__":
    unittest.main()

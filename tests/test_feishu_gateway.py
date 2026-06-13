import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from c_auto_bridge.feishu.gateway import FeishuGateway, FeishuMessageBackfill
from c_auto_bridge.feishu.message import IncomingAttachment, IncomingMessage
from c_auto_bridge.feishu.ws_keepalive import (
    LARK_WS_KEEPALIVE_DISABLED_MARKER,
    disable_websockets_builtin_keepalive,
)


class FeishuGatewayMessageTest(unittest.TestCase):
    def test_init_disables_websockets_builtin_keepalive_and_keeps_sdk_reconnect_enabled(self) -> None:
        ws_clients = []

        with (
            patch("c_auto_bridge.feishu.gateway.lark.Client.builder", return_value=FakeClientBuilder(FakeLarkClient())),
            patch("c_auto_bridge.feishu.gateway.lark.ws.Client", side_effect=lambda *args, **kwargs: ws_clients.append((args, kwargs)) or FakeWsClient()),
            patch("c_auto_bridge.feishu.gateway.disable_websockets_builtin_keepalive") as disable_keepalive,
        ):
            FeishuGateway(
                "app_id",
                "app_secret",
                on_message=_noop_message_handler,
                on_card_action=_noop_card_action_handler,
                submit=lambda value: value,
            )

        disable_keepalive.assert_called_once()
        self.assertEqual(ws_clients[0][1]["auto_reconnect"], True)

    def test_noop_handlers_accept_non_message_bot_events(self) -> None:
        gateway = object.__new__(FeishuGateway)

        self.assertIsNone(gateway.on_bot_p2p_chat_entered(object()))
        self.assertIsNone(gateway.on_bot_menu(object()))

    def test_on_message_normalizes_file_attachment_message(self) -> None:
        gateway = object.__new__(FeishuGateway)
        calls = []
        gateway.submit = lambda value: calls.append(value)
        gateway.on_incoming_message = lambda incoming: incoming
        gateway._seen_message_ids = set()
        gateway._known_private_chat_ids = set()

        gateway.on_message(
            _message_event(
                message_type="file",
                content='{"file_key":"file_1","file_name":"notes.txt"}',
            )
        )

        self.assertEqual(
            calls,
            [
                IncomingMessage(
                    message_id="om_1",
                    chat_id="chat_1",
                    chat_type="p2p",
                    user_id="user_1",
                    text="",
                    attachments=(
                        IncomingAttachment(kind="file", resource_key="file_1", file_name="notes.txt"),
                    ),
                )
            ],
        )

    def test_on_message_deduplicates_message_ids(self) -> None:
        gateway = object.__new__(FeishuGateway)
        calls = []
        gateway.submit = lambda value: calls.append(value)
        gateway.on_incoming_message = lambda incoming: incoming
        gateway._seen_message_ids = set()
        gateway._known_private_chat_ids = set()

        event = _message_event(message_type="text", content='{"text":"hello"}')
        gateway.on_message(event)
        gateway.on_message(event)

        self.assertEqual(
            calls,
            [
                IncomingMessage(
                    message_id="om_1",
                    chat_id="chat_1",
                    chat_type="p2p",
                    user_id="user_1",
                    text="hello",
                )
            ],
        )

    def test_bot_p2p_chat_entered_remembers_private_chat_for_backfill(self) -> None:
        gateway = object.__new__(FeishuGateway)
        gateway._known_private_chat_ids = set()

        gateway.on_bot_p2p_chat_entered(type("Payload", (), {"event": type("Event", (), {"chat_id": "chat_1"})()})())

        self.assertEqual(gateway._known_private_chat_ids, {"chat_1"})


class FeishuGatewayBackfillTest(unittest.IsolatedAsyncioTestCase):
    async def test_backfill_recent_private_messages_submits_unseen_messages(self) -> None:
        submitted = []
        client = FakeLarkClient(
            list_pages=[
                FakeListResponse(
                    [
                        _history_message(
                            message_id="om_seen",
                            chat_id="chat_1",
                            sender_id="user_1",
                            msg_type="text",
                            content='{"text":"already handled"}',
                            create_time=1700000000000,
                        ),
                        _history_message(
                            message_id="om_new",
                            chat_id="chat_1",
                            sender_id="user_1",
                            msg_type="text",
                            content='{"text":"missed"}',
                            create_time=1700000001000,
                        ),
                    ]
                )
            ]
        )
        gateway = object.__new__(FeishuGateway)
        gateway.client = client
        gateway.submit = lambda value: submitted.append(value)
        gateway.on_incoming_message = lambda incoming: incoming
        gateway._seen_message_ids = {"om_seen"}
        gateway._known_private_chat_ids = {"chat_1"}
        gateway._backfill = FeishuMessageBackfill(lookback_seconds=300, page_size=20)
        gateway._clock = lambda: datetime.fromtimestamp(1700000300, timezone.utc)

        await gateway.backfill_recent_private_messages(reason="test")

        self.assertEqual(
            submitted,
            [
                IncomingMessage(
                    message_id="om_new",
                    chat_id="chat_1",
                    chat_type="p2p",
                    user_id="user_1",
                    text="missed",
                )
            ],
        )
        self.assertEqual(gateway._seen_message_ids, {"om_seen", "om_new"})
        self.assertEqual(
            client.list_requests[0].queries,
            [
                ("container_id_type", "chat"),
                ("container_id", "chat_1"),
                ("start_time", "1700000000"),
                ("end_time", "1700000300"),
                ("sort_type", "ByCreateTimeAsc"),
                ("page_size", "20"),
            ],
        )

    async def test_backfill_paginates_until_has_more_is_false(self) -> None:
        submitted = []
        client = FakeLarkClient(
            list_pages=[
                FakeListResponse(
                    [
                        _history_message(
                            message_id="om_1",
                            chat_id="chat_1",
                            sender_id="user_1",
                            msg_type="text",
                            content='{"text":"one"}',
                            create_time=1700000000000,
                        )
                    ],
                    has_more=True,
                    page_token="next",
                ),
                FakeListResponse(
                    [
                        _history_message(
                            message_id="om_2",
                            chat_id="chat_1",
                            sender_id="user_1",
                            msg_type="text",
                            content='{"text":"two"}',
                            create_time=1700000001000,
                        )
                    ],
                    has_more=False,
                ),
            ]
        )
        gateway = object.__new__(FeishuGateway)
        gateway.client = client
        gateway.submit = lambda value: submitted.append(value)
        gateway.on_incoming_message = lambda incoming: incoming
        gateway._seen_message_ids = set()
        gateway._known_private_chat_ids = {"chat_1"}
        gateway._backfill = FeishuMessageBackfill(lookback_seconds=60, page_size=1)
        gateway._clock = lambda: datetime.fromtimestamp(1700000300, timezone.utc)

        await gateway.backfill_recent_private_messages(reason="test")

        self.assertEqual([item.message_id for item in submitted], ["om_1", "om_2"])
        self.assertEqual(client.list_requests[1].queries[-1], ("page_token", "next"))

    async def test_backfill_ignores_unsupported_history_message_types(self) -> None:
        submitted = []
        client = FakeLarkClient(
            list_pages=[
                FakeListResponse(
                    [
                        _history_message(
                            message_id="om_audio",
                            chat_id="chat_1",
                            sender_id="user_1",
                            msg_type="audio",
                            content='{"file_key":"audio_1"}',
                            create_time=1700000000000,
                        )
                    ]
                )
            ]
        )
        gateway = object.__new__(FeishuGateway)
        gateway.client = client
        gateway.submit = lambda value: submitted.append(value)
        gateway.on_incoming_message = lambda incoming: incoming
        gateway._seen_message_ids = set()
        gateway._known_private_chat_ids = {"chat_1"}
        gateway._backfill = FeishuMessageBackfill(lookback_seconds=60, page_size=20)
        gateway._clock = lambda: datetime.fromtimestamp(1700000300, timezone.utc)

        await gateway.backfill_recent_private_messages(reason="test")

        self.assertEqual(submitted, [])
        self.assertEqual(gateway._seen_message_ids, set())


class LarkWebSocketKeepaliveTest(unittest.TestCase):
    def test_disable_websockets_builtin_keepalive_patches_sdk_connect_kwargs_once(self) -> None:
        class FakeWsClientModule:
            @staticmethod
            def _ws_connect_kwargs():
                return {"proxy": None}

        disable_websockets_builtin_keepalive(FakeWsClientModule)
        disable_websockets_builtin_keepalive(FakeWsClientModule)

        self.assertEqual(
            FakeWsClientModule._ws_connect_kwargs(),
            {"proxy": None, "ping_interval": None},
        )
        self.assertTrue(getattr(FakeWsClientModule._ws_connect_kwargs, LARK_WS_KEEPALIVE_DISABLED_MARKER))


def _message_event(*, message_type: str, content: str):
    sender_id = type("SenderId", (), {"open_id": "user_1"})()
    sender = type("Sender", (), {"sender_id": sender_id})()
    message = type(
        "Message",
        (),
        {
            "message_id": "om_1",
            "chat_id": "chat_1",
            "chat_type": "p2p",
            "message_type": message_type,
            "content": content,
        },
    )()
    event = type("Event", (), {"message": message, "sender": sender})()
    return type("Payload", (), {"event": event})()


def _history_message(
    *,
    message_id: str,
    chat_id: str,
    sender_id: str,
    msg_type: str,
    content: str,
    create_time: int,
):
    sender = type("Sender", (), {"id": sender_id})()
    body = type("Body", (), {"content": content})()
    return type(
        "Message",
        (),
        {
            "message_id": message_id,
            "chat_id": chat_id,
            "sender": sender,
            "msg_type": msg_type,
            "body": body,
            "create_time": create_time,
        },
    )()


class FakeClientBuilder:
    def __init__(self, client):
        self.client = client

    def app_id(self, app_id):
        return self

    def app_secret(self, app_secret):
        return self

    def build(self):
        return self.client


class FakeWsClient:
    def start(self):
        return None


class FakeLarkClient:
    def __init__(self, *, list_pages=None) -> None:
        self.list_pages = list(list_pages or [])
        self.list_requests = []
        self.im = type("Im", (), {"v1": type("V1", (), {"message": FakeMessageResource(self)})()})()


class FakeMessageResource:
    def __init__(self, client: FakeLarkClient) -> None:
        self.client = client

    async def alist(self, request):
        self.client.list_requests.append(request)
        return self.client.list_pages.pop(0)


class FakeListResponse:
    def __init__(self, items, *, has_more=False, page_token=None) -> None:
        self.data = type("Data", (), {"items": items, "has_more": has_more, "page_token": page_token})()
        self.code = 0
        self.msg = ""

    def success(self) -> bool:
        return True

    def get_log_id(self):
        return "log_1"


async def _noop_message_handler(incoming):
    return None


async def _noop_card_action_handler(incoming):
    return None


if __name__ == "__main__":
    unittest.main()

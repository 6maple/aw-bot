import unittest

from c_auto_bridge.feishu.gateway import FeishuGateway
from c_auto_bridge.feishu.message import IncomingAttachment, IncomingMessage


class FeishuGatewayMessageTest(unittest.TestCase):
    def test_noop_handlers_accept_non_message_bot_events(self) -> None:
        gateway = object.__new__(FeishuGateway)

        self.assertIsNone(gateway.on_bot_p2p_chat_entered(object()))
        self.assertIsNone(gateway.on_bot_menu(object()))

    def test_on_message_normalizes_file_attachment_message(self) -> None:
        gateway = object.__new__(FeishuGateway)
        calls = []
        gateway.submit = lambda value: calls.append(value)
        gateway.on_incoming_message = lambda incoming: incoming

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


if __name__ == "__main__":
    unittest.main()

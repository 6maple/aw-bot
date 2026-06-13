import unittest

from c_auto_bridge.feishu.gateway import FeishuGateway
from c_auto_bridge.feishu.message import IncomingAttachment, IncomingMenuEvent, IncomingMessage


class FeishuGatewayMessageTest(unittest.TestCase):
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

    def test_on_menu_normalizes_exact_command_menu_event(self) -> None:
        gateway = object.__new__(FeishuGateway)
        calls = []
        gateway.submit = lambda value: calls.append(value)
        gateway.on_incoming_menu = lambda incoming: incoming

        gateway.on_menu(_menu_event(event_key="aw_bot_menu()"))

        self.assertEqual(
            calls,
            [
                IncomingMenuEvent(
                    user_id="ou_1",
                    event_key="aw_bot_menu()",
                )
            ],
        )

    def test_event_handler_registers_menu_callback(self) -> None:
        gateway = object.__new__(FeishuGateway)
        gateway.on_message = lambda data: None
        gateway.on_menu = lambda data: None
        gateway.on_card_action = lambda data: None

        handler = gateway._build_event_handler()

        self.assertIn("p2.im.message.receive_v1", handler._processorMap)
        self.assertIn("p2.application.bot.menu_v6", handler._processorMap)
        self.assertIn("p2.card.action.trigger", handler._callback_processor_map)


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


def _menu_event(*, event_key: str):
    operator_id = type("OperatorId", (), {"open_id": "ou_1"})()
    operator = type("Operator", (), {"operator_id": operator_id})()
    event = type(
        "Event",
        (),
        {
            "event_key": event_key,
            "operator": operator,
        },
    )()
    return type("Payload", (), {"event": event})()


if __name__ == "__main__":
    unittest.main()

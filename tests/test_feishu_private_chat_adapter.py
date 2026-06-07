import unittest

from c_auto_bridge.core.use_cases import PrivateChatTextMessage, RunViewAction
from c_auto_bridge.feishu.gateway import IncomingCardAction
from c_auto_bridge.feishu.message import IncomingMessage
from c_auto_bridge.feishu.private_chat_adapter import FeishuPrivateChatAdapter


class FeishuPrivateChatAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_private_chat_message_is_forwarded_to_core_use_cases(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="p2p",
                user_id="user_1",
                text="ship it",
            )
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "ship it")],
        )

    async def test_non_private_chat_message_is_ignored(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="group",
                user_id="user_1",
                text="ship it",
            )
        )

        self.assertEqual(use_cases.text_messages, [])

    async def test_stop_card_action_becomes_stop_command(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "stop", "run_id": "run_1"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/stop")],
        )

    async def test_approval_card_action_is_mapped_to_core_run_view_action(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "approve", "pending_id": "pending_1"})
        )
        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"action": "reject", "pending_id": "pending_2"})
        )

        self.assertEqual(
            use_cases.run_view_actions,
            [
                RunViewAction("chat_1", "user_1", "accept", "pending_1"),
                RunViewAction("chat_1", "user_1", "deny", "pending_2"),
            ],
        )


class FakeUseCases:
    def __init__(self) -> None:
        self.text_messages: list[PrivateChatTextMessage] = []
        self.run_view_actions: list[RunViewAction] = []

    async def handle_private_chat_text(self, message: PrivateChatTextMessage) -> None:
        self.text_messages.append(message)

    async def handle_run_view_action(self, action: RunViewAction) -> None:
        self.run_view_actions.append(action)


if __name__ == "__main__":
    unittest.main()

import asyncio
import unittest

from c_auto_bridge.bot.command_router import CommandRouter
from c_auto_bridge.feishu.gateway import IncomingCardAction


class CommandRouterTest(unittest.TestCase):
    def test_card_cmd_stop_calls_controller_stop(self) -> None:
        async def run() -> None:
            controller = FakeController()
            router = CommandRouter(store=FakeStore(), controller=controller)

            await router.handle_card_action(
                IncomingCardAction("chat_1", "user_1", {"cmd": "stop", "run_id": "run_1"})
            )

            self.assertEqual(controller.stops, [("chat_1", "run_1")])

        asyncio.run(run())


class FakeStore:
    def get_open_pending_by_user(self, user_id):
        return None


class FakeController:
    def __init__(self):
        self.stops = []

    def is_active(self, scope_id):
        return False

    async def start(self, scope_id, user_id, text):
        raise AssertionError("start should not be called")

    async def stop(self, scope_id, run_id):
        self.stops.append((scope_id, run_id))
        return True

    async def answer_user_input(self, scope_id, text):
        raise AssertionError("answer_user_input should not be called")

    async def answer_approval(self, scope_id, run_id, pending_id, decision):
        raise AssertionError("answer_approval should not be called")


if __name__ == "__main__":
    unittest.main()

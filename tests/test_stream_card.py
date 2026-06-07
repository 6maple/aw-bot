import asyncio
from dataclasses import replace
import unittest

from c_auto_bridge.feishu.stream_card import StreamCard
from c_auto_bridge.react.state import initial_run_state


class StreamCardTest(unittest.TestCase):
    def test_throttles_updates_and_forces_final_close(self) -> None:
        async def run() -> None:
            transport = FakeTransport()
            clock = Clock()
            stream = StreamCard(
                transport, render_card=lambda state: {"text": state.text},
                render_text=lambda state: state.text,
                send_text=lambda chat_id, text: _done(),
                monotonic=clock,
            )
            card = await stream.create(run_id="r", chat_id="c", state=initial_run_state("r"), timestamp="now")
            self.assertFalse(await stream.update(card, initial_run_state("r"), final=False))
            clock.value = 0.5
            self.assertTrue(await stream.update(card, initial_run_state("r"), final=False))
            self.assertTrue(await stream.update(card, replace(initial_run_state("r"), status="completed"), final=True))
            self.assertEqual(transport.calls, ["create", "send", "update", "update", "close"])

        asyncio.run(run())


class Clock:
    value = 0.0
    def __call__(self):
        return self.value


class FakeTransport:
    def __init__(self):
        self.calls = []
    async def create_card(self, card):
        self.calls.append("create")
        return "card_1"
    async def send_card(self, chat_id, card_id):
        self.calls.append("send")
        return "msg_1"
    async def update_card(self, card_id, card, sequence):
        self.calls.append("update")
    async def close_card(self, card_id, sequence):
        self.calls.append("close")


async def _done():
    return None


if __name__ == "__main__":
    unittest.main()

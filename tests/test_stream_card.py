import asyncio
from dataclasses import replace
import json
import unittest

from c_auto_bridge.feishu.stream_card import LarkCardTransport, StreamCard
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

    def test_lark_card_transport_sets_json_content_type_for_async_cardkit_requests(self) -> None:
        async def run() -> None:
            card = {"config": {"wide_screen_mode": True}, "elements": []}
            client = FakeLarkClient()
            transport = LarkCardTransport(client)

            card_id = await transport.create_card(card)
            await transport.update_card(card_id, card, 2)
            await transport.close_card(card_id, 3)

            self.assertEqual(
                [option.headers["Content-Type"] for option in client.cardkit.v1.card.options],
                [
                    "application/json; charset=utf-8",
                    "application/json; charset=utf-8",
                    "application/json; charset=utf-8",
                ],
            )
            self.assertEqual(json.loads(client.cardkit.v1.card.created.body.data), card)

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


class FakeLarkClient:
    def __init__(self):
        self.cardkit = FakeCardkit()


class FakeCardkit:
    def __init__(self):
        self.v1 = FakeCardkitV1()


class FakeCardkitV1:
    def __init__(self):
        self.card = FakeCardResource()


class FakeCardResource:
    def __init__(self):
        self.options = []
        self.created = None

    async def acreate(self, request, option=None):
        self.created = request
        self.options.append(option)
        return FakeCreateCardResponse()

    async def aupdate(self, request, option=None):
        self.options.append(option)
        return FakeSuccessResponse()

    async def asettings(self, request, option=None):
        self.options.append(option)
        return FakeSuccessResponse()


class FakeCreateCardResponse:
    code = 0
    msg = "ok"

    def __init__(self):
        self.data = FakeCreateCardData()

    def success(self):
        return True


class FakeCreateCardData:
    card_id = "card_1"


class FakeSuccessResponse:
    code = 0
    msg = "ok"

    def success(self):
        return True


async def _done():
    return None


if __name__ == "__main__":
    unittest.main()

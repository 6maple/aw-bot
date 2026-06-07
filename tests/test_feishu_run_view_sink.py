from dataclasses import dataclass, replace
import unittest

from c_auto_bridge.core.run_view import RunView, UsageView, initial_run_view
from c_auto_bridge.feishu.run_view_sink import FeishuRunViewSink
from c_auto_bridge.store.models import StreamCardRef


class FeishuRunViewSinkTest(unittest.IsolatedAsyncioTestCase):
    async def test_publish_creates_and_updates_single_streaming_card(self) -> None:
        stream_card = FakeStreamCard()
        sink = FeishuRunViewSink(
            stream_card=stream_card,
            send_text=_send_text_noop,
            clock=lambda: "2026-06-06T12:00:00+00:00",
        )

        await sink.publish(private_chat_scope_id="chat_1", run_view=initial_run_view("run_1"))
        await sink.publish(
            private_chat_scope_id="chat_1",
            run_view=replace(initial_run_view("run_1"), text="hello"),
        )
        await sink.publish(
            private_chat_scope_id="chat_1",
            run_view=replace(initial_run_view("run_1"), status="completed", text="hello"),
        )

        self.assertEqual(len(stream_card.created), 1)
        self.assertEqual(
            [(call.card.run_id, call.state.text, call.final) for call in stream_card.updated],
            [("run_1", "hello", False), ("run_1", "hello", True)],
        )

    async def test_publish_falls_back_to_text_when_card_creation_fails(self) -> None:
        texts: list[tuple[str, str]] = []
        sink = FeishuRunViewSink(
            stream_card=FailingCreateStreamCard(),
            send_text=lambda chat_id, text: _capture_text(texts, chat_id, text),
            clock=lambda: "2026-06-06T12:00:00+00:00",
        )

        await sink.publish(
            private_chat_scope_id="chat_1",
            run_view=replace(initial_run_view("run_1"), status="completed", text="hello"),
        )

        self.assertEqual(texts, [("chat_1", "hello")])

    async def test_publish_ignores_update_failure(self) -> None:
        sink = FeishuRunViewSink(
            stream_card=FailingUpdateStreamCard(),
            send_text=_send_text_noop,
            clock=lambda: "2026-06-06T12:00:00+00:00",
        )

        await sink.publish(private_chat_scope_id="chat_1", run_view=initial_run_view("run_1"))
        await sink.publish(
            private_chat_scope_id="chat_1",
            run_view=replace(initial_run_view("run_1"), status="completed", text="done"),
        )


class FakeStreamCard:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, RunView]] = []
        self.updated: list[UpdateCall] = []

    async def create(self, *, run_id: str, chat_id: str, state, timestamp: str) -> StreamCardRef:
        self.created.append((run_id, chat_id, _to_run_view(state)))
        return StreamCardRef("card_1", run_id, chat_id, "message_1", "streaming", timestamp, timestamp)

    async def update(self, card: StreamCardRef, state, *, final: bool) -> bool:
        self.updated.append(UpdateCall(card=card, state=_to_run_view(state), final=final))
        return True


class FailingCreateStreamCard:
    async def create(self, *, run_id: str, chat_id: str, state, timestamp: str) -> StreamCardRef:
        raise RuntimeError("boom")

    async def update(self, card: StreamCardRef, state, *, final: bool) -> bool:
        raise AssertionError("update should not be called when create fails")


class FailingUpdateStreamCard(FakeStreamCard):
    async def update(self, card: StreamCardRef, state, *, final: bool) -> bool:
        raise RuntimeError("boom")


@dataclass
class UpdateCall:
    card: StreamCardRef
    state: RunView
    final: bool


async def _send_text_noop(chat_id: str, text: str) -> None:
    return None


async def _capture_text(texts: list[tuple[str, str]], chat_id: str, text: str) -> None:
    texts.append((chat_id, text))


def _to_run_view(state) -> RunView:
    return RunView(
        run_id=state.run_id,
        status=state.status,
        text=state.text,
        thinking=state.thinking,
        tools=(),
        pending=None,
        usage=UsageView(
            input_tokens=state.usage.input_tokens,
            output_tokens=state.usage.output_tokens,
        ),
        error=state.error,
    )


if __name__ == "__main__":
    unittest.main()

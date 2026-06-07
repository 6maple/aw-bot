import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import uuid4

import lark_oapi as lark
from lark_oapi.api.cardkit.v1 import (
    Card,
    CreateCardRequest,
    CreateCardRequestBody,
    SettingsCardRequest,
    SettingsCardRequestBody,
    UpdateCardRequest,
    UpdateCardRequestBody,
)
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

from c_auto_bridge.react.state import RunState
from c_auto_bridge.store.models import StreamCardRef


logger = logging.getLogger(__name__)


class CardTransport(Protocol):
    async def create_card(self, card: dict[str, Any]) -> str: ...
    async def send_card(self, chat_id: str, card_id: str) -> str: ...
    async def update_card(self, card_id: str, card: dict[str, Any], sequence: int) -> None: ...
    async def close_card(self, card_id: str, sequence: int) -> None: ...


class LarkCardTransport:
    def __init__(self, client: lark.Client):
        self.client = client

    async def create_card(self, card: dict[str, Any]) -> str:
        request = CreateCardRequest.builder().request_body(
            CreateCardRequestBody.builder().type("card_json").data(json.dumps(card, ensure_ascii=False)).build()
        ).build()
        response = await self.client.cardkit.v1.card.acreate(request)
        _require_success(response, "create card", card=card)
        card_id = response.data.card_id
        if not isinstance(card_id, str):
            raise TypeError("create card response has no card_id")
        return card_id

    async def send_card(self, chat_id: str, card_id: str) -> str:
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(json.dumps({"type": "card", "data": {"card_id": card_id}}))
                .build()
            )
            .build()
        )
        response = await self.client.im.v1.message.acreate(request)
        _require_success(response, "send card")
        message_id = response.data.message_id
        if not isinstance(message_id, str):
            raise TypeError("send card response has no message_id")
        return message_id

    async def update_card(self, card_id: str, card: dict[str, Any], sequence: int) -> None:
        request = (
            UpdateCardRequest.builder()
            .card_id(card_id)
            .request_body(
                UpdateCardRequestBody.builder()
                .card(Card.builder().type("card_json").data(json.dumps(card, ensure_ascii=False)).build())
                .uuid(uuid4().hex)
                .sequence(sequence)
                .build()
            )
            .build()
        )
        _require_success(await self.client.cardkit.v1.card.aupdate(request), "update card", card=card)

    async def close_card(self, card_id: str, sequence: int) -> None:
        request = (
            SettingsCardRequest.builder()
            .card_id(card_id)
            .request_body(
                SettingsCardRequestBody.builder()
                .settings(json.dumps({"streaming_mode": False}))
                .uuid(uuid4().hex)
                .sequence(sequence)
                .build()
            )
            .build()
        )
        _require_success(await self.client.cardkit.v1.card.asettings(request), "close card")


class StreamCard:
    def __init__(
        self,
        transport: CardTransport,
        *,
        render_card: Callable[[RunState], dict[str, Any]],
        render_text: Callable[[RunState], str],
        send_text: Callable[[str, str], Awaitable[None]],
        interval_seconds: float = 0.4,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.transport = transport
        self.render_card = render_card
        self.render_text = render_text
        self.send_text = send_text
        self.interval_seconds = interval_seconds
        self.monotonic = monotonic
        self._last_update: dict[str, float] = {}
        self._sequence: dict[str, int] = {}
        self._closed: set[str] = set()

    async def create(self, *, run_id: str, chat_id: str, state: RunState, timestamp: str) -> StreamCardRef:
        card_id = await self.transport.create_card(self.render_card(state))
        message_id = await self.transport.send_card(chat_id, card_id)
        self._last_update[card_id] = self.monotonic()
        self._sequence[card_id] = 1
        return StreamCardRef(card_id, run_id, chat_id, message_id, "streaming", timestamp, timestamp)

    async def update(self, card: StreamCardRef, state: RunState, *, final: bool) -> bool:
        if card.card_id in self._closed:
            logger.info("stream card update skipped after close: run_id=%s card_id=%s", card.run_id, card.card_id)
            return False
        now = self.monotonic()
        if not final and now - self._last_update[card.card_id] < self.interval_seconds:
            return False
        sequence = self._sequence[card.card_id] + 1
        try:
            if final:
                logger.info(
                    "stream card final update: run_id=%s card_id=%s status=%s sequence=%s text_len=%s",
                    card.run_id,
                    card.card_id,
                    state.status,
                    sequence,
                    len(state.text),
                )
            await self.transport.update_card(card.card_id, self.render_card(state), sequence)
            self._sequence[card.card_id] = sequence
            self._last_update[card.card_id] = now
            if final:
                await self.transport.close_card(card.card_id, sequence + 1)
                logger.info(
                    "stream card closed: run_id=%s card_id=%s sequence=%s",
                    card.run_id,
                    card.card_id,
                    sequence + 1,
                )
                self._closed.add(card.card_id)
            return True
        except Exception:
            if final:
                logger.exception(
                    "stream card final update failed, sending text fallback: run_id=%s card_id=%s",
                    card.run_id,
                    card.card_id,
                )
                await self.send_text(card.chat_id, self.render_text(state))
                self._closed.add(card.card_id)
            raise


def _require_success(response: Any, operation: str, *, card: dict[str, Any] | None = None) -> None:
    if not response.success():
        detail = f"{operation} failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
        if card is not None:
            logger.error("%s, card=%s", detail, json.dumps(card, ensure_ascii=False, sort_keys=True))
        raise RuntimeError(detail)

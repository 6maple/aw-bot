import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageResourceRequest,
    ListMessageRequest,
    P2ImMessageReceiveV1,
)
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger, P2CardActionTriggerResponse

from c_auto_bridge.feishu.attachment_intake import DownloadedAttachment
from c_auto_bridge.feishu.message import IncomingAttachment, IncomingMessage, parse_message_content
from c_auto_bridge.feishu.ws_keepalive import disable_websockets_builtin_keepalive


logger = logging.getLogger(__name__)
BACKFILL_MESSAGE_TYPES = {"text", "image", "file"}


@dataclass(frozen=True)
class IncomingCardAction:
    chat_id: str
    user_id: str
    value: dict[str, Any]


@dataclass(frozen=True)
class FeishuMessageBackfill:
    lookback_seconds: int = 10 * 60
    page_size: int = 50


class FeishuGateway:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        on_message: Callable[[IncomingMessage], Awaitable[None]],
        on_card_action: Callable[[IncomingCardAction], Awaitable[None]],
        submit: Callable[[Awaitable[None]], object],
        backfill: FeishuMessageBackfill | None = None,
        clock: Callable[[], datetime] | None = None,
        known_private_chat_ids: set[str] | None = None,
    ):
        self.on_incoming_message = on_message
        self.on_incoming_card_action = on_card_action
        self.submit = submit
        self._backfill = backfill or FeishuMessageBackfill()
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._seen_message_ids: set[str] = set()
        self._known_private_chat_ids: set[str] = set(known_private_chat_ids or ())
        self.client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
        disable_websockets_builtin_keepalive()
        self.ws_client = lark.ws.Client(
            app_id,
            app_secret,
            event_handler=self._build_event_handler(),
            log_level=lark.LogLevel.INFO,
            auto_reconnect=True,
        )
        self.ws_client.on_reconnecting = self._on_reconnecting
        self.ws_client.on_reconnected = self._on_reconnected

    def start(self) -> None:
        logger.info("starting Feishu websocket client")
        self.ws_client.start()

    async def backfill_recent_private_messages(self, *, reason: str) -> None:
        chat_ids = sorted(self._known_private_chat_ids)
        if not chat_ids:
            logger.info("feishu message backfill skipped: reason=%s known_private_chat_count=0", reason)
            return
        now = self._clock()
        start = now - timedelta(seconds=self._backfill.lookback_seconds)
        start_time = str(int(start.timestamp()))
        end_time = str(int(now.timestamp()))
        logger.info(
            "feishu message backfill started: reason=%s chat_count=%s start_time=%s end_time=%s",
            reason,
            len(chat_ids),
            start_time,
            end_time,
        )
        total = 0
        for chat_id in chat_ids:
            total += await self._backfill_chat(chat_id=chat_id, start_time=start_time, end_time=end_time)
        logger.info("feishu message backfill finished: reason=%s submitted_count=%s", reason, total)

    async def send_text(self, chat_id: str, text: str) -> None:
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id).msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False)).build()
            )
            .build()
        )
        response = await self.client.im.v1.message.acreate(request)
        if not response.success():
            raise RuntimeError(f"send text failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}")

    async def download(
        self,
        *,
        message_id: str,
        attachment: IncomingAttachment,
    ) -> DownloadedAttachment:
        request = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(attachment.resource_key)
            .type(attachment.kind)
            .build()
        )
        response = await self.client.im.v1.message.aget(request)
        if not response.success():
            raise RuntimeError(
                f"download attachment failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )
        content = _downloaded_content(response)
        file_name = attachment.file_name or _downloaded_file_name(response) or attachment.resource_key
        return DownloadedAttachment(file_name=file_name, content=content)

    def on_message(self, data: P2ImMessageReceiveV1) -> None:
        message = data.event.message
        logger.info(
            "feishu message received: message_id=%s chat_id=%s chat_type=%s message_type=%s content_len=%s",
            message.message_id,
            message.chat_id,
            message.chat_type,
            message.message_type,
            len(message.content) if isinstance(message.content, str) else None,
        )
        if message.chat_type != "p2p":
            logger.info(
                "feishu message ignored: message_id=%s chat_type=%s",
                message.message_id,
                message.chat_type,
            )
            return
        if message.message_id in self._seen_message_ids:
            logger.info("feishu message ignored: duplicate message_id=%s", message.message_id)
            return
        self._known_private_chat_ids.add(message.chat_id)
        try:
            text, attachments = parse_message_content(message.message_type, message.content)
        except Exception:
            logger.exception(
                "feishu message parse failed: message_id=%s message_type=%s",
                message.message_id,
                message.message_type,
            )
            raise
        logger.info(
            "feishu message parsed: message_id=%s text_len=%s attachment_count=%s",
            message.message_id,
            len(text),
            len(attachments),
        )
        incoming = IncomingMessage(
            message.message_id, message.chat_id, message.chat_type,
            data.event.sender.sender_id.open_id, text, attachments,
        )
        self._seen_message_ids.add(message.message_id)
        try:
            self._submit_with_logging(
                self.on_incoming_message(incoming),
                label="message",
                event_id=message.message_id,
            )
        except Exception:
            self._seen_message_ids.discard(message.message_id)
            raise

    def on_card_action(self, data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        event = data.event
        value = event.action.value
        if not isinstance(value, dict):
            raise TypeError("card action value must be a dict")
        logger.info(
            "feishu card action received: chat_id=%s user_id=%s value_keys=%s",
            event.context.open_chat_id,
            event.operator.open_id,
            sorted(value),
        )
        self._submit_with_logging(
            self.on_incoming_card_action(IncomingCardAction(event.context.open_chat_id, event.operator.open_id, value)),
            label="card_action",
            event_id=str(value.get("run_id") or value.get("pending_id") or ""),
        )
        return P2CardActionTriggerResponse()

    def on_bot_p2p_chat_entered(self, data: Any) -> None:
        chat_id = getattr(getattr(data, "event", None), "chat_id", None)
        if isinstance(chat_id, str) and chat_id:
            self._known_private_chat_ids.add(chat_id)
        logger.info("feishu bot p2p chat entered event noted: chat_id=%s", chat_id)

    def on_bot_menu(self, data: Any) -> None:
        logger.info("feishu bot menu event ignored")

    async def _backfill_chat(self, *, chat_id: str, start_time: str, end_time: str) -> int:
        submitted = 0
        page_token: str | None = None
        while True:
            request = (
                ListMessageRequest.builder()
                .container_id_type("chat")
                .container_id(chat_id)
                .start_time(start_time)
                .end_time(end_time)
                .sort_type("ByCreateTimeAsc")
                .page_size(self._backfill.page_size)
            )
            if page_token:
                request = request.page_token(page_token)
            response = await self.client.im.v1.message.alist(request.build())
            if not response.success():
                raise RuntimeError(
                    f"list messages failed: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
                )
            data = response.data
            items = tuple(getattr(data, "items", None) or ())
            logger.info(
                "feishu message backfill page received: chat_id=%s item_count=%s has_more=%s",
                chat_id,
                len(items),
                getattr(data, "has_more", False),
            )
            for item in items:
                if self._submit_history_message(item):
                    submitted += 1
            if not getattr(data, "has_more", False):
                return submitted
            page_token = getattr(data, "page_token", None)
            if not page_token:
                logger.warning("feishu message backfill stopped: chat_id=%s missing page_token", chat_id)
                return submitted

    def _submit_history_message(self, message: Any) -> bool:
        message_id = getattr(message, "message_id", None)
        if not isinstance(message_id, str) or not message_id:
            logger.warning("feishu history message ignored: missing message_id")
            return False
        if message_id in self._seen_message_ids:
            logger.info("feishu history message ignored: duplicate message_id=%s", message_id)
            return False
        chat_id = getattr(message, "chat_id", None)
        sender = getattr(message, "sender", None)
        sender_id = getattr(sender, "id", None)
        message_type = getattr(message, "msg_type", None)
        body = getattr(message, "body", None)
        content = getattr(body, "content", None)
        if not isinstance(chat_id, str) or not isinstance(sender_id, str):
            logger.warning("feishu history message ignored: message_id=%s missing chat_id or sender_id", message_id)
            return False
        if message_type not in BACKFILL_MESSAGE_TYPES:
            logger.info(
                "feishu history message ignored: message_id=%s unsupported message_type=%s",
                message_id,
                message_type,
            )
            return False
        if not isinstance(content, str):
            logger.warning("feishu history message ignored: message_id=%s missing content", message_id)
            return False
        try:
            text, attachments = parse_message_content(message_type, content)
        except Exception:
            logger.exception(
                "feishu history message parse failed: message_id=%s message_type=%s",
                message_id,
                message_type,
            )
            return False
        incoming = IncomingMessage(
            message_id=message_id,
            chat_id=chat_id,
            chat_type="p2p",
            user_id=sender_id,
            text=text,
            attachments=attachments,
        )
        self._known_private_chat_ids.add(chat_id)
        self._seen_message_ids.add(message_id)
        try:
            self._submit_with_logging(
                self.on_incoming_message(incoming),
                label="history_message",
                event_id=message_id,
            )
        except Exception:
            self._seen_message_ids.discard(message_id)
            raise
        return True

    def _on_reconnecting(self) -> None:
        logger.warning("feishu websocket reconnecting")

    def _on_reconnected(self) -> None:
        logger.info("feishu websocket reconnected; scheduling message backfill")
        self._submit_with_logging(
            self.backfill_recent_private_messages(reason="websocket_reconnected"),
            label="message_backfill",
            event_id="websocket_reconnected",
        )

    def _submit_with_logging(self, awaitable: Awaitable[None], *, label: str, event_id: str) -> None:
        try:
            future = self.submit(awaitable)
        except Exception:
            logger.exception("feishu %s submit failed: event_id=%s", label, event_id)
            raise
        logger.info("feishu %s submitted: event_id=%s", label, event_id)
        add_done_callback = getattr(future, "add_done_callback", None)
        if not callable(add_done_callback):
            return
        add_done_callback(lambda done: _log_submitted_exception(done, label, event_id))

    def _build_event_handler(self):
        return (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self.on_message)
            .register_p2_card_action_trigger(self.on_card_action)
            .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(self.on_bot_p2p_chat_entered)
            .register_p2_application_bot_menu_v6(self.on_bot_menu)
            .build()
        )


def _log_submitted_exception(future, label: str, event_id: str) -> None:
    try:
        exc = future.exception()
    except Exception:
        logger.exception("feishu %s future inspection failed: event_id=%s", label, event_id)
        return
    if exc is not None:
        logger.error("feishu %s handler failed: event_id=%s", label, event_id, exc_info=(type(exc), exc, exc.__traceback__))


def _downloaded_content(response) -> bytes:
    for attr in ("file", "content", "data"):
        value = getattr(response, attr, None)
        if isinstance(value, bytes):
            return value
    data = getattr(response, "data", None)
    if data is not None:
        for attr in ("file", "content"):
            value = getattr(data, attr, None)
            if isinstance(value, bytes):
                return value
    raise RuntimeError("download attachment response did not include bytes")


def _downloaded_file_name(response) -> str | None:
    data = getattr(response, "data", None)
    if data is None:
        return None
    for attr in ("file_name", "filename", "name"):
        value = getattr(data, attr, None)
        if isinstance(value, str):
            return value
    return None

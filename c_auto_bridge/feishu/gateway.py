import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageResourceRequest,
    P2ImMessageReceiveV1,
)
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger, P2CardActionTriggerResponse

from c_auto_bridge.feishu.message import IncomingMessage, parse_message_content
from c_auto_bridge.feishu.attachment_intake import DownloadedAttachment
from c_auto_bridge.feishu.message import IncomingAttachment


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncomingCardAction:
    chat_id: str
    user_id: str
    value: dict[str, Any]


class FeishuGateway:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        on_message: Callable[[IncomingMessage], Awaitable[None]],
        on_card_action: Callable[[IncomingCardAction], Awaitable[None]],
        submit: Callable[[Awaitable[None]], object],
    ):
        self.on_incoming_message = on_message
        self.on_incoming_card_action = on_card_action
        self.submit = submit
        self.client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
        self.ws_client = lark.ws.Client(
            app_id, app_secret, event_handler=self._build_event_handler(), log_level=lark.LogLevel.INFO,
        )

    def start(self) -> None:
        logger.info("starting Feishu websocket client")
        self.ws_client.start()

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
        self._submit_with_logging(
            self.on_incoming_message(incoming),
            label="message",
            event_id=message.message_id,
        )

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
        logger.info("feishu bot p2p chat entered event ignored")

    def on_bot_menu(self, data: Any) -> None:
        logger.info("feishu bot menu event ignored")

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

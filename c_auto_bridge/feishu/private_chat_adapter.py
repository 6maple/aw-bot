import logging

from c_auto_bridge.core.use_cases import CoreUseCases, PrivateChatTextMessage, RunViewAction
from c_auto_bridge.feishu.gateway import IncomingCardAction
from c_auto_bridge.feishu.message import IncomingMessage


logger = logging.getLogger(__name__)


class FeishuPrivateChatAdapter:
    def __init__(self, *, use_cases: CoreUseCases) -> None:
        self._use_cases = use_cases

    async def handle_message(self, incoming: IncomingMessage) -> None:
        if incoming.chat_type != "p2p":
            logger.info(
                "private chat adapter ignored non-p2p message: message_id=%s chat_type=%s",
                incoming.message_id,
                incoming.chat_type,
            )
            return
        logger.info(
            "private chat adapter forwarding message: message_id=%s chat_id=%s user_id=%s text_len=%s attachment_count=%s",
            incoming.message_id,
            incoming.chat_id,
            incoming.user_id,
            len(incoming.text),
            len(incoming.attachments),
        )
        await self._use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id=incoming.chat_id,
                user_id=incoming.user_id,
                text=incoming.text,
            )
        )

    async def handle_card_action(self, incoming: IncomingCardAction) -> None:
        action = incoming.value.get("cmd") or incoming.value.get("action")
        if not isinstance(action, str):
            raise TypeError("card action must include cmd or action")
        logger.info(
            "private chat adapter handling card action: chat_id=%s user_id=%s action=%s",
            incoming.chat_id,
            incoming.user_id,
            action,
        )
        if action == "stop":
            await self._use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id=incoming.chat_id,
                    user_id=incoming.user_id,
                    text="/stop",
                )
            )
            return
        pending_id = incoming.value.get("pending_id")
        if not isinstance(pending_id, str):
            raise TypeError("pending_id must be a string")
        await self._use_cases.handle_run_view_action(
            RunViewAction(
                private_chat_scope_id=incoming.chat_id,
                user_id=incoming.user_id,
                action=_approval_action(action),
                pending_request_id=pending_id,
            )
        )


def _approval_action(action: str) -> str:
    if action == "approve":
        return "accept"
    if action == "reject":
        return "deny"
    raise ValueError(f"unsupported card action: {action}")

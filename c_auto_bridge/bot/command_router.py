from c_auto_bridge.bot.pending_queue import PendingQueue
from c_auto_bridge.bot.run_controller import RunController
from c_auto_bridge.feishu.gateway import IncomingCardAction
from c_auto_bridge.feishu.message import IncomingMessage
from c_auto_bridge.react.pending import map_approval_decision
from c_auto_bridge.store.base import Store


class CommandRouter:
    def __init__(self, *, store: Store, controller: RunController):
        self.store = store
        self.controller = controller
        self.queue = PendingQueue(self.controller.start, is_active=self.controller.is_active)

    async def handle_message(self, incoming: IncomingMessage) -> None:
        pending = self.store.get_open_pending_by_user(incoming.user_id)
        if pending is not None:
            if pending.kind == "user_input":
                await self.controller.answer_user_input(incoming.chat_id, incoming.text)
                return
            decision = map_approval_decision(incoming.text)
            if decision is not None:
                await self.controller.answer_approval(incoming.chat_id, None, pending.pending_id, decision)
            return
        if incoming.text.strip() == "/stop":
            await self.controller.stop(incoming.chat_id, None)
            return
        self.queue.submit(incoming.chat_id, incoming.user_id, incoming.text)

    async def handle_card_action(self, incoming: IncomingCardAction) -> None:
        action = incoming.value.get("cmd") or incoming.value.get("action")
        if not isinstance(action, str):
            raise TypeError("card action must include cmd or action")
        run_id = incoming.value.get("run_id")
        if run_id is not None and not isinstance(run_id, str):
            raise TypeError("run_id must be a string")
        if action == "stop":
            await self.controller.stop(incoming.chat_id, run_id)
            return
        pending_id = incoming.value["pending_id"]
        if not isinstance(pending_id, str):
            raise TypeError("pending_id must be a string")
        if action == "approve":
            await self.controller.answer_approval(incoming.chat_id, run_id, pending_id, "accept")
        elif action == "reject":
            await self.controller.answer_approval(incoming.chat_id, run_id, pending_id, "deny")
        else:
            raise ValueError(f"unsupported card action: {action}")

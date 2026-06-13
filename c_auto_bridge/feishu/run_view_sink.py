import logging
from collections.abc import Awaitable, Callable

from c_auto_bridge.core.run_view import PendingRequestView, RunView, ToolCallView
from c_auto_bridge.feishu.stream_card import StreamCard
from c_auto_bridge.react.state import PendingState, RunState, ToolState, UsageState
from c_auto_bridge.react.text_renderer import render_text
from c_auto_bridge.store.models import StreamCardRef


TERMINAL_RUN_STATUSES = {"completed", "failed", "interrupted", "timed_out"}
logger = logging.getLogger(__name__)


class FeishuRunViewSink:
    def __init__(
        self,
        *,
        stream_card: StreamCard,
        send_text: Callable[[str, str], Awaitable[None]],
        clock: Callable[[], str],
    ) -> None:
        self._stream_card = stream_card
        self._send_text = send_text
        self._clock = clock
        self._cards: dict[str, StreamCardRef] = {}
        self._text_fallback_runs: set[str] = set()
        self._text_fallback_pending_ids: set[tuple[str, str]] = set()
        self._card_create_disabled_reason: str | None = None

    async def publish(self, *, private_chat_scope_id: str, run_view: RunView) -> None:
        state = _to_run_state(run_view)
        final = run_view.status in TERMINAL_RUN_STATUSES
        card = self._cards.get(run_view.run_id)
        if final:
            logger.info(
                "feishu run view final publish: run_id=%s status=%s text_len=%s thinking_len=%s card_exists=%s",
                run_view.run_id,
                run_view.status,
                len(run_view.text),
                len(run_view.thinking),
                card is not None,
            )
        if card is None:
            if self._card_create_disabled_reason is not None:
                await self._publish_text_fallback(
                    private_chat_scope_id=private_chat_scope_id,
                    run_view=run_view,
                    state=state,
                    final=final,
                )
                return
            if run_view.run_id in self._text_fallback_runs:
                await self._publish_text_fallback(
                    private_chat_scope_id=private_chat_scope_id,
                    run_view=run_view,
                    state=state,
                    final=final,
                )
                return
            try:
                card = await self._stream_card.create(
                    run_id=run_view.run_id,
                    chat_id=private_chat_scope_id,
                    state=state,
                    timestamp=self._clock(),
                )
            except Exception as exc:
                if _is_card_permission_error(exc):
                    self._card_create_disabled_reason = str(exc)
                    logger.warning(
                        "feishu cards disabled; missing card permission, falling back to text: run_id=%s error=%s",
                        run_view.run_id,
                        exc,
                    )
                else:
                    logger.exception("feishu card create failed: run_id=%s", run_view.run_id)
                await self._publish_text_fallback(
                    private_chat_scope_id=private_chat_scope_id,
                    run_view=run_view,
                    state=state,
                    final=final,
                    first=True,
                )
                return
            self._cards[run_view.run_id] = card
            if not final:
                return
        try:
            await self._stream_card.update(card, state, final=final)
        except Exception:
            logger.exception(
                "feishu card update failed: run_id=%s status=%s final=%s",
                run_view.run_id,
                run_view.status,
                final,
            )
            return
        if final:
            logger.info("feishu run view final card removed: run_id=%s", run_view.run_id)
            self._cards.pop(run_view.run_id, None)

    async def _publish_text_fallback(
        self,
        *,
        private_chat_scope_id: str,
        run_view: RunView,
        state: RunState,
        final: bool,
        first: bool = False,
    ) -> None:
        is_known_fallback = run_view.run_id in self._text_fallback_runs
        if first or not is_known_fallback:
            self._text_fallback_runs.add(run_view.run_id)
            await self._send_text(private_chat_scope_id, render_text(state))
            return
        if state.pending is not None:
            pending_key = (run_view.run_id, state.pending.pending_id)
            if pending_key not in self._text_fallback_pending_ids:
                self._text_fallback_pending_ids.add(pending_key)
                logger.info(
                    "feishu text fallback pending send: run_id=%s status=%s pending_id=%s",
                    run_view.run_id,
                    run_view.status,
                    state.pending.pending_id,
                )
                await self._send_text(private_chat_scope_id, render_text(state))
            return
        if final:
            logger.info(
                "feishu text fallback final send: run_id=%s status=%s",
                run_view.run_id,
                run_view.status,
            )
            await self._send_text(private_chat_scope_id, render_text(state))


def _to_run_state(run_view: RunView) -> RunState:
    return RunState(
        run_id=run_view.run_id,
        status=run_view.status,
        text=run_view.text,
        thinking=run_view.thinking,
        tools=tuple(_to_tool_state(tool) for tool in run_view.tools),
        pending=_to_pending_state(run_view.pending),
        usage=UsageState(
            input_tokens=run_view.usage.input_tokens,
            output_tokens=run_view.usage.output_tokens,
        ),
        error=run_view.error,
    )


def _to_tool_state(tool: ToolCallView) -> ToolState:
    return ToolState(
        tool_id=tool.tool_id,
        name=tool.name,
        input=tool.input,
        output=tool.output,
        status=tool.status,
    )


def _to_pending_state(pending: PendingRequestView | None) -> PendingState | None:
    if pending is None:
        return None
    return PendingState(
        pending_id=pending.pending_request_id,
        kind=pending.kind,
        prompt=pending.prompt,
        payload=pending.payload,
    )


def _is_card_permission_error(exc: Exception) -> bool:
    message = str(exc)
    return "cardkit:card:write" in message or "99991672" in message

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from c_auto_bridge.agent.base import AgentAdapter, AgentRun, AgentThreadNotFound
from c_auto_bridge.feishu.stream_card import StreamCard
from c_auto_bridge.react.events import (
    AgentEvent,
    ApprovalRequested,
    RunFailed,
    RunInterrupted,
    RunTimedOut,
    UserInputRequested,
)
from c_auto_bridge.react.reducer import reduce_run_state
from c_auto_bridge.react.state import RunState, initial_run_state
from c_auto_bridge.session.models import PendingRef, SessionRef
from c_auto_bridge.store.base import Store
from c_auto_bridge.store.models import RunRef, StreamCardRef
from c_auto_bridge.utils.ids import new_run_id


TERMINAL_STATUSES = {"completed", "failed", "interrupted", "timed_out"}


@dataclass
class ActiveRun:
    ref: RunRef
    agent_run: AgentRun
    state: RunState
    card: StreamCardRef | None
    task: asyncio.Task | None
    stop_requested: bool


class RunController:
    def __init__(
        self,
        *,
        store: Store,
        agent: AgentAdapter,
        stream_card: StreamCard,
        send_text,
        timeout_seconds: float = 300,
        clock: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[datetime], str] | None = None,
    ):
        self.store = store
        self.agent = agent
        self.stream_card = stream_card
        self.send_text = send_text
        self.timeout_seconds = timeout_seconds
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.run_id_factory = run_id_factory or new_run_id
        self._active: dict[str, ActiveRun] = {}

    def is_active(self, scope_id: str) -> bool:
        return scope_id in self._active

    async def fail_active_runs(self, error: str) -> None:
        active_runs = list(self._active.values())
        for active in active_runs:
            await self._apply(active, RunFailed(error))
            if active.task is not None and active.task is not asyncio.current_task():
                active.task.cancel()
        tasks = [
            active.task
            for active in active_runs
            if active.task is not None and active.task is not asyncio.current_task()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        scopes = list(self._active)
        await asyncio.gather(
            *(self.stop(scope_id, None) for scope_id in scopes),
            return_exceptions=True,
        )
        active_runs = list(self._active.values())
        for active in active_runs:
            if active.task is not None:
                active.task.cancel()
        tasks = [active.task for active in active_runs if active.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active.clear()

    async def start(self, scope_id: str, user_id: str, text: str) -> RunRef:
        if self.is_active(scope_id):
            raise RuntimeError(f"scope already has an active run: {scope_id}")
        session = await self._session(scope_id, user_id)
        try:
            agent_run = await self.agent.start_turn(session, text)
        except AgentThreadNotFound:
            session = await self.agent.create_session(owner_user_id=user_id, chat_id=scope_id, title=None)
            agent_run = await self.agent.start_turn(session, text)
        now = self.clock()
        timestamp = now.isoformat()
        run_id = self.run_id_factory(now)
        ref = RunRef(run_id, scope_id, session.bot_session_id, session.agent, agent_run.thread_id, agent_run.turn_id, "running", timestamp, timestamp)
        state = initial_run_state(run_id)
        self.store.save_run(ref)
        card = None
        try:
            card = await self.stream_card.create(run_id=run_id, chat_id=scope_id, state=state, timestamp=timestamp)
            self.store.save_card(card)
        except Exception as exc:
            self.store.append_run_error(run_id, str(exc))
        active = ActiveRun(ref, agent_run, state, card, None, False)
        self._active[scope_id] = active
        active.task = asyncio.create_task(self._consume(active))
        return ref

    async def stop(self, scope_id: str, run_id: str | None) -> bool:
        active = self._active.get(scope_id)
        if (
            active is None
            or active.stop_requested
            or (run_id is not None and active.ref.run_id != run_id)
        ):
            return False
        active.stop_requested = True
        try:
            await active.agent_run.stop()
            event: AgentEvent = RunInterrupted()
        except Exception as exc:
            self.store.append_run_error(active.ref.run_id, str(exc))
            event = RunFailed(str(exc))
        await self._apply(active, event)
        if active.task is not None and active.task is not asyncio.current_task():
            active.task.cancel()
            await asyncio.gather(active.task, return_exceptions=True)
        return True

    async def answer_user_input(self, scope_id: str, text: str) -> bool:
        active = self._active.get(scope_id)
        if active is None or active.state.pending is None or active.state.pending.kind != "user_input":
            return False
        await active.agent_run.answer_user_input(text)
        await self._resume(active, active.state.pending.pending_id)
        return True

    async def answer_approval(
        self,
        scope_id: str,
        run_id: str | None,
        pending_id: str,
        decision: str,
    ) -> bool:
        active = self._active.get(scope_id)
        if (
            active is None
            or (run_id is not None and active.ref.run_id != run_id)
            or active.state.pending is None
            or active.state.pending.pending_id != pending_id
        ):
            return False
        await active.agent_run.answer_approval(pending_id, decision)
        await self._resume(active, pending_id)
        return True

    async def _consume(self, active: ActiveRun) -> None:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async for event in active.agent_run.events:
                    await self._apply(active, event)
                    if active.state.status in TERMINAL_STATUSES:
                        return
                if active.stop_requested:
                    return
                await self._apply(active, RunFailed("agent event stream ended without terminal event"))
        except TimeoutError:
            try:
                await active.agent_run.stop()
            except Exception as exc:
                self.store.append_run_error(active.ref.run_id, str(exc))
            await self._apply(active, RunTimedOut())
        except Exception as exc:
            if active.stop_requested:
                return
            self.store.append_run_error(active.ref.run_id, str(exc))
            await self._apply(active, RunFailed(str(exc)))

    async def _apply(self, active: ActiveRun, event: AgentEvent) -> None:
        if active.state.status in TERMINAL_STATUSES:
            return
        pending_id = active.state.pending.pending_id if active.state.pending is not None else None
        self.store.append_run_event(active.ref.run_id, event)
        active.state = reduce_run_state(active.state, event)
        if isinstance(event, (UserInputRequested, ApprovalRequested)):
            self._save_pending(active, event)
            active.ref.status = "pending"
        elif active.state.status in TERMINAL_STATUSES:
            if pending_id is not None:
                self.store.close_pending(pending_id, "cancelled")
            active.ref.status = active.state.status
        active.ref.updated_at = self.clock().isoformat()
        self.store.save_run(active.ref)
        final = active.state.status in TERMINAL_STATUSES
        if active.card is not None:
            try:
                await self.stream_card.update(active.card, active.state, final=final)
            except Exception as exc:
                self.store.append_run_error(active.ref.run_id, str(exc))
                active.card.status = "failed"
            if final and active.card.status != "failed":
                active.card.status = "completed"
            active.card.updated_at = active.ref.updated_at
            self.store.save_card(active.card)
        elif final:
            try:
                await self.send_text(active.ref.scope_id, active.state.text or active.state.error or active.state.status)
            except Exception as exc:
                self.store.append_run_error(active.ref.run_id, str(exc))
        if final:
            self._active.pop(active.ref.scope_id, None)

    async def _resume(self, active: ActiveRun, pending_id: str) -> None:
        self.store.close_pending(pending_id, "resolved")
        active.state = replace(active.state, status="running", pending=None)
        active.ref.status = "running"
        active.ref.updated_at = self.clock().isoformat()
        self.store.save_run(active.ref)
        if active.card is None:
            return
        try:
            await self.stream_card.update(active.card, active.state, final=False)
        except Exception as exc:
            self.store.append_run_error(active.ref.run_id, str(exc))
            active.card.status = "failed"
            active.card.updated_at = active.ref.updated_at
            self.store.save_card(active.card)

    async def _session(self, scope_id: str, user_id: str) -> SessionRef:
        session = self.store.get_current_session(user_id)
        if session is None:
            return await self.agent.create_session(owner_user_id=user_id, chat_id=scope_id, title=None)
        return session

    def _save_pending(self, active: ActiveRun, event: UserInputRequested | ApprovalRequested) -> None:
        now = self.clock().isoformat()
        session = self.store.get_session(active.ref.bot_session_id)
        if session is None:
            raise RuntimeError(f"run session not found: {active.ref.bot_session_id}")
        pending = PendingRef(
            event.pending_id, active.ref.bot_session_id, session.owner_feishu_user_id,
            active.ref.scope_id, "user_input" if isinstance(event, UserInputRequested) else "approval",
            active.ref.thread_id, active.ref.turn_id, event.pending_id, event.prompt, event.payload,
            "open", now, now,
        )
        self.store.save_pending(pending)

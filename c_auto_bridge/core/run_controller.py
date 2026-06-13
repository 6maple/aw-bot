import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable

from c_auto_bridge.core.agent_events import ApprovalRequested, RunInterrupted, RunTimedOut, UserInputRequested
from c_auto_bridge.core.agent_session import AccessMode, AgentSession, HistoricalAgentSession, Workspace
from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.core.idle_timeout import AsyncioIdleTimeoutScheduler, IdleTimeoutHandle, IdleTimeoutScheduler
from c_auto_bridge.core.pending_request import PendingRequest
from c_auto_bridge.core.queue import QueuedMessage, pop_next_merged_prompt
from c_auto_bridge.core.run import Run, RunStatus
from c_auto_bridge.core.run_view import RunView, initial_run_view
from c_auto_bridge.core.run_view_reducer import reduce_run_view
from c_auto_bridge.ports.agent import AgentPort, AgentThreadNotFound, AgentTurnStreamPort
from c_auto_bridge.ports.persistence import RunPersistencePort
from c_auto_bridge.ports.run_view_sink import RunViewSinkPort


logger = logging.getLogger(__name__)


class RunController:
    merge_window_seconds = 1.5

    def __init__(
        self,
        *,
        agent: AgentPort,
        persistence: RunPersistencePort,
        run_view_sink: RunViewSinkPort,
        workspace: Workspace,
        access_mode: AccessMode,
        agent_name: str,
        clock: Callable[[], datetime],
        run_id_factory: Callable[[datetime], str],
        default_idle_timeout_seconds: float | None = None,
        idle_timeout_scheduler: IdleTimeoutScheduler | None = None,
    ) -> None:
        self._agent = agent
        self._persistence = persistence
        self._run_view_sink = run_view_sink
        self._workspace = workspace
        self._access_mode = access_mode
        self._agent_name = agent_name
        self._clock = clock
        self._run_id_factory = run_id_factory
        self._default_idle_timeout_seconds = default_idle_timeout_seconds
        self._idle_timeout_scheduler = idle_timeout_scheduler or AsyncioIdleTimeoutScheduler()
        self._active_runs: dict[str, ActiveRun] = {}
        self._fresh_session_scope_ids: set[str] = set()
        self._selected_sessions: dict[str, AgentSession] = {}
        self._idle_timeout_overrides: dict[str, float | None] = {}

    async def start_text_run(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        text: str,
        model: str | None = None,
        opencode_agent: str | None = None,
        attachments: tuple[Attachment, ...] = (),
    ) -> Run:
        if private_chat_scope_id in self._active_runs:
            raise RuntimeError(f"scope already has an active run: {private_chat_scope_id}")
        logger.info(
            "run start requested: chat_id=%s user_id=%s agent=%s text_len=%s",
            private_chat_scope_id,
            user_id,
            self._agent_name,
            len(text),
        )
        agent_session = await self._session_for_new_turn(
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
        )
        logger.info(
            "run using agent session: chat_id=%s session_id=%s agent=%s workspace=%s",
            private_chat_scope_id,
            agent_session.agent_session_id,
            agent_session.agent_name,
            agent_session.workspace.path,
        )
        agent_session, turn_stream = await self._start_turn_with_session_recovery(
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_session=agent_session,
            prompt=text,
            model=model,
            opencode_agent=opencode_agent,
            attachments=attachments,
        )
        logger.info(
            "agent turn started: chat_id=%s session_id=%s turn_id=%s",
            private_chat_scope_id,
            agent_session.agent_session_id,
            turn_stream.agent_turn.agent_turn_id,
        )
        now = self._clock().isoformat()
        run = Run(
            run_id=self._run_id_factory(self._clock()),
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_session_id=agent_session.agent_session_id,
            agent_name=agent_session.agent_name,
            agent_turn_id=turn_stream.agent_turn.agent_turn_id,
            status="running",
            created_at=now,
            updated_at=now,
        )
        run_view = initial_run_view(run.run_id)
        await self._persistence.record_run_created(run)
        logger.info(
            "run created: run_id=%s chat_id=%s session_id=%s turn_id=%s",
            run.run_id,
            private_chat_scope_id,
            run.agent_session_id,
            run.agent_turn_id,
        )
        await self._run_view_sink.publish(private_chat_scope_id=private_chat_scope_id, run_view=run_view)
        logger.info("initial run view published: run_id=%s chat_id=%s", run.run_id, private_chat_scope_id)
        active_run = ActiveRun(
            run=run,
            run_view=run_view,
            turn_stream=turn_stream,
            user_id=user_id,
            agent_session=agent_session,
            queued_messages=[],
            completion_future=asyncio.get_running_loop().create_future(),
        )
        self._active_runs[private_chat_scope_id] = active_run
        self._arm_idle_timeout(private_chat_scope_id)
        return await self._consume_until_pause_or_terminal(private_chat_scope_id)

    async def stop_run(self, *, private_chat_scope_id: str, user_id: str) -> Run:
        active_run = self._require_active_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        active_run.stop_requested = True
        active_run.queued_messages = []
        if active_run.run_view.pending is not None:
            await active_run.turn_stream.stop()
            active_run.run_view = reduce_run_view(active_run.run_view, RunInterrupted())
            await self._run_view_sink.publish(private_chat_scope_id=private_chat_scope_id, run_view=active_run.run_view)
            result = await self._finish(private_chat_scope_id=private_chat_scope_id, status="interrupted")
            if active_run.completion_future is not None and not active_run.completion_future.done():
                active_run.completion_future.set_result(result)
            return result
        await active_run.turn_stream.stop()
        return await active_run.completion_future

    async def reset_session(self, *, private_chat_scope_id: str, user_id: str) -> Run:
        if self.has_any_active_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id):
            run = await self._finish_run_for_session_reset(
                private_chat_scope_id=private_chat_scope_id,
                user_id=user_id,
            )
        else:
            run = self._interrupted_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        await self._clear_session_selection(private_chat_scope_id=private_chat_scope_id)
        await self._create_selected_session(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        return run

    async def clear_selected_session(self, *, private_chat_scope_id: str) -> None:
        await self._persistence.clear_current_session(private_chat_scope_id=private_chat_scope_id)
        self._fresh_session_scope_ids.add(private_chat_scope_id)
        self._selected_sessions.pop(private_chat_scope_id, None)

    async def change_workspace(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        workspace: Workspace,
    ) -> Run:
        if self.has_any_active_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id):
            run = await self.stop_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        else:
            run = self._interrupted_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        await self._clear_session_selection(private_chat_scope_id=private_chat_scope_id)
        self._workspace = workspace
        await self._create_selected_session(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        return run

    @property
    def workspace(self) -> Workspace:
        return self._workspace

    @property
    def access_mode(self) -> AccessMode:
        return self._access_mode

    @property
    def agent_name(self) -> str:
        return self._agent_name

    async def resume_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        historical_session: HistoricalAgentSession,
    ) -> None:
        self._fresh_session_scope_ids.discard(private_chat_scope_id)
        session = AgentSession(
            agent_session_id=historical_session.agent_session_id,
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=historical_session.agent_name,
            workspace=historical_session.workspace,
            access_mode=historical_session.access_mode or self._access_mode,
        )
        self._selected_sessions[private_chat_scope_id] = session
        await self._persistence.save_agent_session(
            agent_session=HistoricalAgentSession(
                agent_session_id=session.agent_session_id,
                private_chat_scope_id=session.private_chat_scope_id,
                user_id=session.user_id,
                agent_name=session.agent_name,
                workspace=session.workspace,
                access_mode=session.access_mode,
                updated_at=self._clock().isoformat(),
            )
        )

    def has_active_run(self, *, private_chat_scope_id: str, user_id: str) -> bool:
        active_run = self._active_runs.get(private_chat_scope_id)
        return active_run is not None and active_run.user_id == user_id and active_run.run_view.pending is None

    async def queue_message(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        text: str,
        model: str | None = None,
        opencode_agent: str | None = None,
        attachments: tuple[Attachment, ...] = (),
    ) -> Run:
        active_run = self._require_active_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        if active_run.run_view.pending is not None:
            raise RuntimeError(f"scope has a pending request and cannot queue text: {private_chat_scope_id}")
        active_run.queued_messages.append(
            QueuedMessage(
                user_id=user_id,
                text=text,
                attachments=attachments,
                queued_at=self._clock(),
                model=model,
                opencode_agent=opencode_agent,
            )
        )
        logger.info(
            "message queued for active run: run_id=%s chat_id=%s queued_count=%s text_len=%s",
            active_run.run.run_id,
            private_chat_scope_id,
            len(active_run.queued_messages),
            len(text),
        )
        return active_run.run

    def has_open_user_input_pending_request(self, *, private_chat_scope_id: str, user_id: str) -> bool:
        active_run = self._active_runs.get(private_chat_scope_id)
        return (
            active_run is not None
            and active_run.user_id == user_id
            and active_run.run_view.pending is not None
            and active_run.run_view.pending.kind == "user_input"
        )

    def open_approval_pending_request_id(self, *, private_chat_scope_id: str, user_id: str) -> str | None:
        active_run = self._active_runs.get(private_chat_scope_id)
        if (
            active_run is None
            or active_run.user_id != user_id
            or active_run.run_view.pending is None
            or active_run.run_view.pending.kind != "approval"
        ):
            return None
        return active_run.run_view.pending.pending_request_id

    async def answer_user_input(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        text: str,
    ) -> Run:
        active_run = self._require_active_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        pending = active_run.run_view.pending
        if pending is None or pending.kind != "user_input":
            raise RuntimeError(f"scope does not have an open user-input pending request: {private_chat_scope_id}")
        await active_run.turn_stream.answer_user_input(text)
        await self._resolve_pending_request(active_run=active_run)
        return await self._consume_until_pause_or_terminal(private_chat_scope_id)

    async def answer_approval(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        pending_request_id: str,
        decision: str,
    ) -> Run:
        active_run = self._require_active_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        pending = active_run.run_view.pending
        if pending is None or pending.kind != "approval" or pending.pending_request_id != pending_request_id:
            raise RuntimeError(f"scope does not have matching approval pending request: {private_chat_scope_id}")
        await active_run.turn_stream.answer_approval(pending_request_id, decision)
        await self._resolve_pending_request(active_run=active_run)
        return await self._consume_until_pause_or_terminal(private_chat_scope_id)

    def has_any_active_run(self, *, private_chat_scope_id: str, user_id: str) -> bool:
        active_run = self._active_runs.get(private_chat_scope_id)
        return active_run is not None and active_run.user_id == user_id

    def get_idle_timeout_seconds(self, *, private_chat_scope_id: str) -> float | None:
        if private_chat_scope_id in self._idle_timeout_overrides:
            return self._idle_timeout_overrides[private_chat_scope_id]
        return self._default_idle_timeout_seconds

    def set_idle_timeout_seconds(self, *, private_chat_scope_id: str, timeout_seconds: float) -> None:
        self._idle_timeout_overrides[private_chat_scope_id] = timeout_seconds
        self._arm_idle_timeout(private_chat_scope_id)

    def disable_idle_timeout(self, *, private_chat_scope_id: str) -> None:
        self._idle_timeout_overrides[private_chat_scope_id] = None
        self._cancel_idle_timeout(private_chat_scope_id)

    def clear_idle_timeout_override(self, *, private_chat_scope_id: str) -> None:
        self._idle_timeout_overrides.pop(private_chat_scope_id, None)
        self._arm_idle_timeout(private_chat_scope_id)

    async def _consume_until_pause_or_terminal(self, private_chat_scope_id: str) -> Run:
        active_run = self._active_runs[private_chat_scope_id]
        logger.info("run consumption started: run_id=%s chat_id=%s", active_run.run.run_id, private_chat_scope_id)
        async for event in active_run.turn_stream.events:
            if active_run.timed_out:
                continue
            if active_run.stop_requested:
                event = RunInterrupted()
            logger.info(
                "agent event consumed: run_id=%s event=%s",
                active_run.run.run_id,
                type(event).__name__,
            )
            await self._persistence.record_run_event(run_id=active_run.run.run_id, event=event)
            active_run.run_view = reduce_run_view(active_run.run_view, event)
            await self._run_view_sink.publish(private_chat_scope_id=private_chat_scope_id, run_view=active_run.run_view)
            if isinstance(event, UserInputRequested):
                self._cancel_idle_timeout(private_chat_scope_id)
                await self._open_pending_request(active_run=active_run, pending_kind="user_input")
                active_run.run = replace(active_run.run, status="pending_user_input")
                return active_run.run
            if isinstance(event, ApprovalRequested):
                self._cancel_idle_timeout(private_chat_scope_id)
                await self._open_pending_request(active_run=active_run, pending_kind="approval")
                active_run.run = replace(active_run.run, status="pending_approval")
                return active_run.run
            if active_run.run_view.status in TERMINAL_RUN_STATUSES:
                self._cancel_idle_timeout(private_chat_scope_id)
                if active_run.queued_messages:
                    return await self._start_queued_next_turn(private_chat_scope_id=private_chat_scope_id)
                result = await self._finish(private_chat_scope_id=private_chat_scope_id, status=active_run.run_view.status)
                if not active_run.completion_future.done():
                    active_run.completion_future.set_result(result)
                return result
            self._arm_idle_timeout(private_chat_scope_id)
        self._cancel_idle_timeout(private_chat_scope_id)
        if active_run.timed_out:
            active_run.run_view = reduce_run_view(active_run.run_view, RunTimedOut())
            await self._run_view_sink.publish(private_chat_scope_id=private_chat_scope_id, run_view=active_run.run_view)
            result = await self._finish(private_chat_scope_id=private_chat_scope_id, status="timed_out")
            if not active_run.completion_future.done():
                active_run.completion_future.set_result(result)
            return result
        if active_run.stop_requested:
            active_run.run_view = reduce_run_view(active_run.run_view, RunInterrupted())
            await self._run_view_sink.publish(private_chat_scope_id=private_chat_scope_id, run_view=active_run.run_view)
            result = await self._finish(private_chat_scope_id=private_chat_scope_id, status="interrupted")
            if not active_run.completion_future.done():
                active_run.completion_future.set_result(result)
            return result
        raise RuntimeError("agent turn ended without a terminal event")

    async def _finish(
        self,
        *,
        private_chat_scope_id: str,
        status: RunStatus,
    ) -> Run:
        active_run = self._active_runs[private_chat_scope_id]
        logger.info(
            "run finishing: run_id=%s chat_id=%s status=%s text_len=%s thinking_len=%s",
            active_run.run.run_id,
            private_chat_scope_id,
            status,
            len(active_run.run_view.text),
            len(active_run.run_view.thinking),
        )
        updated_at = self._clock().isoformat()
        if active_run.run_view.pending is not None:
            await self._persistence.close_pending_request(
                pending_request_id=active_run.run_view.pending.pending_request_id,
                status="cancelled",
            )
        completed_run = Run(
            run_id=active_run.run.run_id,
            private_chat_scope_id=active_run.run.private_chat_scope_id,
            user_id=active_run.run.user_id,
            agent_session_id=active_run.run.agent_session_id,
            agent_name=active_run.run.agent_name,
            agent_turn_id=active_run.run.agent_turn_id,
            status=status,
            created_at=active_run.run.created_at,
            updated_at=updated_at,
        )
        await self._persistence.record_run_terminal_status(
            run_id=completed_run.run_id,
            status=status,
            updated_at=updated_at,
        )
        self._cancel_idle_timeout(private_chat_scope_id)
        self._active_runs.pop(private_chat_scope_id, None)
        logger.info("run finished: run_id=%s status=%s", completed_run.run_id, completed_run.status)
        return completed_run

    async def _start_queued_next_turn(self, *, private_chat_scope_id: str) -> Run:
        active_run = self._active_runs[private_chat_scope_id]
        logger.info(
            "starting queued next turn check: previous_run_id=%s chat_id=%s queued_count=%s",
            active_run.run.run_id,
            private_chat_scope_id,
            len(active_run.queued_messages),
        )
        merged_prompt = pop_next_merged_prompt(
            active_run.queued_messages,
            merge_window_seconds=self.merge_window_seconds,
        )
        if merged_prompt is None:
            return await self._finish(
                private_chat_scope_id=private_chat_scope_id,
                status=active_run.run_view.status,
            )
        prompt, attachments, user_id, model, opencode_agent, remaining = merged_prompt
        active_run.queued_messages = remaining
        logger.info(
            "starting queued next turn: previous_run_id=%s chat_id=%s merged_text_len=%s remaining_count=%s",
            active_run.run.run_id,
            private_chat_scope_id,
            len(prompt),
            len(remaining),
        )
        agent_session, turn_stream = await self._start_turn_with_session_recovery(
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_session=await self._session_for_new_turn(
                private_chat_scope_id=private_chat_scope_id,
                user_id=user_id,
            ),
            prompt=prompt,
            model=model,
            opencode_agent=opencode_agent,
            attachments=attachments,
        )
        now = self._clock().isoformat()
        run = Run(
            run_id=self._run_id_factory(self._clock()),
            private_chat_scope_id=active_run.run.private_chat_scope_id,
            user_id=user_id,
            agent_session_id=agent_session.agent_session_id,
            agent_name=agent_session.agent_name,
            agent_turn_id=turn_stream.agent_turn.agent_turn_id,
            status="running",
            created_at=now,
            updated_at=now,
        )
        run_view = initial_run_view(run.run_id)
        active_run.run = run
        active_run.run_view = run_view
        active_run.turn_stream = turn_stream
        active_run.agent_session = agent_session
        active_run.user_id = user_id
        active_run.stop_requested = False
        await self._persistence.record_run_created(run)
        await self._run_view_sink.publish(private_chat_scope_id=private_chat_scope_id, run_view=run_view)
        logger.info(
            "queued run created: run_id=%s chat_id=%s turn_id=%s",
            run.run_id,
            private_chat_scope_id,
            run.agent_turn_id,
        )
        return await self._consume_until_pause_or_terminal(private_chat_scope_id)

    async def _session_for_new_turn(self, *, private_chat_scope_id: str, user_id: str) -> AgentSession:
        if private_chat_scope_id in self._fresh_session_scope_ids:
            logger.info("creating fresh agent session: chat_id=%s user_id=%s", private_chat_scope_id, user_id)
            agent_session = await self._agent.create_session(
                private_chat_scope_id=private_chat_scope_id,
                user_id=user_id,
                agent_name=self._agent_name,
                workspace=self._workspace,
                access_mode=self._access_mode,
            )
            self._fresh_session_scope_ids.discard(private_chat_scope_id)
            self._selected_sessions[private_chat_scope_id] = agent_session
            await self._record_agent_session(agent_session)
            return agent_session
        selected_session = self._selected_sessions.get(private_chat_scope_id)
        if selected_session is not None:
            logger.info(
                "using selected agent session: chat_id=%s session_id=%s",
                private_chat_scope_id,
                selected_session.agent_session_id,
            )
            return selected_session
        logger.info("getting or creating agent session: chat_id=%s user_id=%s", private_chat_scope_id, user_id)
        agent_session = await self._agent.get_or_create_session(
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=self._agent_name,
            workspace=self._workspace,
            access_mode=self._access_mode,
        )
        self._selected_sessions[private_chat_scope_id] = agent_session
        await self._record_agent_session(agent_session)
        return agent_session

    async def _start_turn_with_session_recovery(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_session: AgentSession,
        prompt: str,
        model: str | None = None,
        opencode_agent: str | None = None,
        attachments: tuple[Attachment, ...] = (),
    ) -> tuple[AgentSession, AgentTurnStreamPort]:
        try:
            return agent_session, await self._start_agent_turn(
                agent_session=agent_session,
                prompt=prompt,
                model=model,
                opencode_agent=opencode_agent,
                attachments=attachments,
            )
        except AgentThreadNotFound:
            logger.info(
                "agent session not found, creating replacement: chat_id=%s stale_session_id=%s",
                private_chat_scope_id,
                agent_session.agent_session_id,
            )
            replacement = await self._agent.create_session(
                private_chat_scope_id=private_chat_scope_id,
                user_id=user_id,
                agent_name=self._agent_name,
                workspace=self._workspace,
                access_mode=self._access_mode,
            )
            self._selected_sessions[private_chat_scope_id] = replacement
            await self._record_agent_session(replacement)
            logger.info(
                "replacement agent session created: chat_id=%s session_id=%s",
                private_chat_scope_id,
                replacement.agent_session_id,
            )
            return replacement, await self._start_agent_turn(
                agent_session=replacement,
                prompt=prompt,
                model=model,
                opencode_agent=opencode_agent,
                attachments=attachments,
            )

    async def _start_agent_turn(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
        model: str | None,
        opencode_agent: str | None,
        attachments: tuple[Attachment, ...],
    ) -> AgentTurnStreamPort:
        return await self._agent.start_turn(
            agent_session=agent_session,
            prompt=prompt,
            model=model,
            opencode_agent=opencode_agent,
            attachments=attachments,
        )

    async def _finish_run_for_session_reset(self, *, private_chat_scope_id: str, user_id: str) -> Run:
        active_run = self._require_active_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        pending = active_run.run_view.pending
        if pending is None or pending.kind != "approval":
            return await self.stop_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)
        logger.info(
            "declining pending approval before session reset: run_id=%s chat_id=%s pending_id=%s",
            active_run.run.run_id,
            private_chat_scope_id,
            pending.pending_request_id,
        )
        await active_run.turn_stream.answer_approval(pending.pending_request_id, "cancel")
        await self._resolve_pending_request(active_run=active_run)
        run = await self._consume_until_pause_or_terminal(private_chat_scope_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return run
        logger.warning(
            "session reset approval decline did not finish run; interrupting fallback: run_id=%s status=%s",
            run.run_id,
            run.status,
        )
        return await self.stop_run(private_chat_scope_id=private_chat_scope_id, user_id=user_id)

    async def _record_agent_session(self, agent_session: AgentSession) -> None:
        await self._persistence.save_agent_session(
            agent_session=HistoricalAgentSession(
                agent_session_id=agent_session.agent_session_id,
                private_chat_scope_id=agent_session.private_chat_scope_id,
                user_id=agent_session.user_id,
                agent_name=agent_session.agent_name,
                workspace=agent_session.workspace,
                access_mode=agent_session.access_mode,
                updated_at=self._clock().isoformat(),
            )
        )

    async def _clear_session_selection(self, *, private_chat_scope_id: str) -> None:
        await self._persistence.clear_current_session(private_chat_scope_id=private_chat_scope_id)
        self._selected_sessions.pop(private_chat_scope_id, None)
        self._fresh_session_scope_ids.discard(private_chat_scope_id)

    async def _create_selected_session(self, *, private_chat_scope_id: str, user_id: str) -> AgentSession:
        session = await self._agent.create_session(
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=self._agent_name,
            workspace=self._workspace,
            access_mode=self._access_mode,
        )
        self._selected_sessions[private_chat_scope_id] = session
        await self._record_agent_session(session)
        logger.info(
            "selected fresh agent session created: chat_id=%s session_id=%s agent=%s workspace=%s",
            private_chat_scope_id,
            session.agent_session_id,
            session.agent_name,
            session.workspace.path,
        )
        return session

    def _arm_idle_timeout(self, private_chat_scope_id: str) -> None:
        active_run = self._active_runs.get(private_chat_scope_id)
        if active_run is None:
            return
        self._cancel_idle_timeout(private_chat_scope_id)
        timeout_seconds = self.get_idle_timeout_seconds(private_chat_scope_id=private_chat_scope_id)
        if timeout_seconds is None:
            return
        active_run.idle_timeout_handle = self._idle_timeout_scheduler.schedule(
            delay_seconds=timeout_seconds,
            callback=lambda: self._handle_idle_timeout(private_chat_scope_id),
        )

    def _cancel_idle_timeout(self, private_chat_scope_id: str) -> None:
        active_run = self._active_runs.get(private_chat_scope_id)
        if active_run is None or active_run.idle_timeout_handle is None:
            return
        active_run.idle_timeout_handle.cancel()
        active_run.idle_timeout_handle = None

    async def _handle_idle_timeout(self, private_chat_scope_id: str) -> None:
        active_run = self._active_runs.get(private_chat_scope_id)
        if active_run is None or active_run.timed_out or active_run.run_view.pending is not None:
            return
        active_run.timed_out = True
        active_run.queued_messages = []
        await active_run.turn_stream.stop()

    async def _open_pending_request(self, *, active_run: "ActiveRun", pending_kind: str) -> None:
        pending = active_run.run_view.pending
        if pending is None:
            raise RuntimeError(f"run does not have a pending request: {active_run.run.run_id}")
        await self._persistence.open_pending_request(
            run_id=active_run.run.run_id,
            pending_request=PendingRequest(
                pending_request_id=pending.pending_request_id,
                run_id=active_run.run.run_id,
                kind=pending_kind,
                payload=pending.payload,
            ),
        )

    async def _resolve_pending_request(self, *, active_run: "ActiveRun") -> None:
        pending = active_run.run_view.pending
        if pending is None:
            raise RuntimeError(f"run does not have a pending request: {active_run.run.run_id}")
        await self._persistence.close_pending_request(
            pending_request_id=pending.pending_request_id,
            status="resolved",
        )
        active_run.run_view = replace(
            active_run.run_view,
            status="running",
            pending=None,
        )
        await self._run_view_sink.publish(
            private_chat_scope_id=active_run.run.private_chat_scope_id,
            run_view=active_run.run_view,
        )
        self._arm_idle_timeout(active_run.run.private_chat_scope_id)

    def _require_active_run(self, *, private_chat_scope_id: str, user_id: str) -> "ActiveRun":
        active_run = self._active_runs.get(private_chat_scope_id)
        if active_run is None or active_run.user_id != user_id:
            raise RuntimeError(f"scope does not have an active run for user: {private_chat_scope_id}")
        return active_run

    def _interrupted_run(self, *, private_chat_scope_id: str, user_id: str) -> Run:
        now = self._clock().isoformat()
        return Run(
            run_id="",
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_session_id="",
            agent_name=self._agent_name,
            agent_turn_id="",
            status="interrupted",
            created_at=now,
            updated_at=now,
        )


@dataclass
class ActiveRun:
    run: Run
    run_view: RunView
    turn_stream: object
    user_id: str
    agent_session: AgentSession
    queued_messages: list[QueuedMessage]
    stop_requested: bool = False
    completion_future: asyncio.Future | None = None
    idle_timeout_handle: IdleTimeoutHandle | None = None
    timed_out: bool = False


TERMINAL_RUN_STATUSES = {"completed", "failed", "interrupted", "timed_out"}

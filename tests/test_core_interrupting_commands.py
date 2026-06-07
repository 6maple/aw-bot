import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import unittest

from c_auto_bridge.core.agent_events import RunCompleted, RunInterrupted, TextDelta
from c_auto_bridge.core.agent_session import AgentSession, AgentTurn, Workspace
from c_auto_bridge.core.run_view import RunView
from c_auto_bridge.core.use_cases import CoreUseCases, PrivateChatTextMessage
from c_auto_bridge.core.workspace import WorkspaceValidator


class CoreInterruptingCommandsTest(unittest.IsolatedAsyncioTestCase):
    async def test_stop_bypasses_queue_and_interrupts_active_run(self) -> None:
        agent = FakeInterruptingAgentPort()
        persistence = FakeInterruptingPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink)

        run_task = asyncio.create_task(
            use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="work",
                )
            )
        )
        await agent.wait_for_active_turn()

        stop_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="/stop",
            )
        )
        completed_run = await run_task

        self.assertEqual(stop_run.status, "interrupted")
        self.assertEqual(completed_run.status, "interrupted")
        self.assertEqual(agent.stopped_turn_ids, ["turn_1"])
        self.assertEqual(persistence.cleared_session_scope_ids, [])

    async def test_stop_wins_over_completion_event_after_abort(self) -> None:
        agent = FakeInterruptingAgentPort(complete_after_stop=True)
        persistence = FakeInterruptingPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink)

        run_task = asyncio.create_task(
            use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="work",
                )
            )
        )
        await agent.wait_for_active_turn()

        stop_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="/stop",
            )
        )
        completed_run = await run_task

        self.assertEqual(stop_run.status, "interrupted")
        self.assertEqual(completed_run.status, "interrupted")
        self.assertIsInstance(persistence.run_events["run_1"][-1], RunInterrupted)
        self.assertEqual(run_view_sink.views[-1].status, "interrupted")

    async def test_new_bypasses_queue_stops_run_and_clears_session(self) -> None:
        agent = FakeInterruptingAgentPort()
        persistence = FakeInterruptingPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink)

        first_run_task = asyncio.create_task(
            use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="work",
                )
            )
        )
        await agent.wait_for_active_turn()
        interrupted_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="/new",
            )
        )
        await first_run_task

        next_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="fresh",
            )
        )

        self.assertEqual(interrupted_run.status, "interrupted")
        self.assertEqual(agent.created_sessions, ["session_1", "session_2"])
        self.assertEqual(agent.started_prompts, ["work", "fresh"])
        self.assertEqual(persistence.cleared_session_scope_ids, ["chat_1"])
        self.assertEqual(next_run.agent_session_id, "session_2")

    async def test_reset_behaves_like_new(self) -> None:
        agent = FakeInterruptingAgentPort()
        persistence = FakeInterruptingPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink)

        first_run_task = asyncio.create_task(
            use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="work",
                )
            )
        )
        await agent.wait_for_active_turn()
        await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="/reset",
            )
        )
        await first_run_task

        next_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="fresh",
            )
        )

        self.assertEqual(next_run.agent_session_id, "session_2")
        self.assertEqual(persistence.cleared_session_scope_ids, ["chat_1"])

    async def test_commands_are_handled_before_pending_and_queue_logic(self) -> None:
        agent = FakeInterruptingAgentPort(pending_mode=True)
        persistence = FakeInterruptingPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink)

        first_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="work",
            )
        )
        stop_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="/stop",
            )
        )

        self.assertEqual(first_run.status, "pending_user_input")
        self.assertEqual(stop_run.status, "interrupted")
        self.assertEqual(agent.user_input_answers, [])


def build_use_cases(agent, persistence, run_view_sink) -> CoreUseCases:
    return CoreUseCases(
        agent=agent,
        persistence=persistence,
        run_view_sink=run_view_sink,
        workspace=Workspace(path="D:/Workspace/ai-projects/aw-bot"),
        workspace_validator=WorkspaceValidator(
            home_directory=Path("D:/Users/Maple"),
            temp_directory=Path("D:/Temp"),
            system_directories=(),
        ),
        access_mode="workspace",
        agent_name="codex",
        clock=lambda: datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc),
        run_id_factory=RunIdFactory(),
    )


class RunIdFactory:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, now: datetime) -> str:
        self.value += 1
        return f"run_{self.value}"


class FakeInterruptingAgentPort:
    def __init__(self, pending_mode: bool = False, complete_after_stop: bool = False) -> None:
        self.pending_mode = pending_mode
        self.complete_after_stop = complete_after_stop
        self.created_sessions: list[str] = []
        self.started_prompts: list[str] = []
        self.stopped_turn_ids: list[str] = []
        self.user_input_answers: list[str] = []
        self._active_turn = asyncio.Event()
        self._stop_first_turn = asyncio.Event()
        self._session_counter = 0
        self._current_session: AgentSession | None = None

    async def get_or_create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        if self._current_session is None:
            self._current_session = await self.create_session(
                private_chat_scope_id=private_chat_scope_id,
                user_id=user_id,
                agent_name=agent_name,
                workspace=workspace,
                access_mode=access_mode,
            )
        return self._current_session

    async def create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        self._session_counter += 1
        session = AgentSession(
            agent_session_id=f"session_{self._session_counter}",
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=agent_name,
            workspace=workspace,
            access_mode=access_mode,
        )
        self.created_sessions.append(session.agent_session_id)
        self._current_session = session
        return session

    async def start_turn(self, *, agent_session: AgentSession, prompt: str) -> "FakeInterruptingTurn":
        self.started_prompts.append(prompt)
        turn_id = f"turn_{len(self.started_prompts)}"
        if self.pending_mode:
            return FakeInterruptingTurn(
                port=self,
                agent_turn=AgentTurn(agent_turn_id=turn_id),
                events=self._pending_events(),
            )
        if len(self.started_prompts) == 1:
            return FakeInterruptingTurn(
                port=self,
                agent_turn=AgentTurn(agent_turn_id=turn_id),
                events=self._blocking_events(),
            )
        return FakeInterruptingTurn(
            port=self,
            agent_turn=AgentTurn(agent_turn_id=turn_id),
            events=self._completed_events(prompt),
        )

    async def wait_for_active_turn(self) -> None:
        for _ in range(50):
            if self._active_turn.is_set():
                return
            await asyncio.sleep(0)
        raise AssertionError("active turn did not start")

    async def _blocking_events(self) -> AsyncIterator[object]:
        self._active_turn.set()
        yield TextDelta("working")
        await self._stop_first_turn.wait()
        if self.complete_after_stop:
            yield RunCompleted()

    async def _completed_events(self, prompt: str) -> AsyncIterator[object]:
        yield TextDelta(prompt)
        yield RunCompleted()

    async def _pending_events(self) -> AsyncIterator[object]:
        from c_auto_bridge.core.agent_events import UserInputRequested

        yield UserInputRequested("pending_1", "Which file?", {"field": "path"})


@dataclass
class FakeInterruptingTurn:
    port: FakeInterruptingAgentPort
    agent_turn: AgentTurn
    events: AsyncIterator[object]

    async def answer_user_input(self, text: str) -> None:
        self.port.user_input_answers.append(text)

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        raise AssertionError("approval is not used in these tests")

    async def stop(self) -> None:
        self.port.stopped_turn_ids.append(self.agent_turn.agent_turn_id)
        self.port._stop_first_turn.set()


class FakeInterruptingPersistence:
    def __init__(self) -> None:
        self.created_runs = []
        self.run_events: dict[str, list[object]] = {}
        self.terminal_statuses: list[tuple[str, str, str]] = []
        self.opened_pending_requests = []
        self.closed_pending_requests = []
        self.cleared_session_scope_ids: list[str] = []
        self.saved_agent_sessions = []

    async def record_run_created(self, run) -> None:
        self.created_runs.append(run)
        self.run_events[run.run_id] = []

    async def record_run_event(self, *, run_id: str, event: object) -> None:
        self.run_events[run_id].append(event)

    async def record_run_terminal_status(self, *, run_id: str, status: str, updated_at: str) -> None:
        self.terminal_statuses.append((run_id, status, updated_at))

    async def open_pending_request(self, *, run_id: str, pending_request) -> None:
        self.opened_pending_requests.append((run_id, pending_request.pending_request_id))

    async def close_pending_request(self, *, pending_request_id: str, status: str) -> None:
        self.closed_pending_requests.append((pending_request_id, status))

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        self.cleared_session_scope_ids.append(private_chat_scope_id)

    async def save_agent_session(self, *, agent_session) -> None:
        self.saved_agent_sessions.append(agent_session)

    async def list_agent_sessions(self, *, private_chat_scope_id: str, user_id: str) -> list:
        return []


class FakeRunViewSink:
    def __init__(self) -> None:
        self.views: list[RunView] = []

    async def publish(self, *, private_chat_scope_id: str, run_view: RunView) -> None:
        self.views.append(run_view)


if __name__ == "__main__":
    unittest.main()

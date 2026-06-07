from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import unittest

from c_auto_bridge.core.agent_events import (
    ApprovalRequested,
    RunCompleted,
    RunFailed,
    TextDelta,
    UserInputRequested,
)
from c_auto_bridge.core.agent_session import AgentSession, AgentTurn, Workspace
from c_auto_bridge.core.run_view import PendingRequestView, RunView, UsageView
from c_auto_bridge.core.use_cases import CoreUseCases, PrivateChatTextMessage, RunViewAction
from c_auto_bridge.core.workspace import WorkspaceValidator


class CorePendingRequestFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_owner_text_answers_open_user_input_pending_request(self) -> None:
        agent = FakePendingAgentPort(
            initial_events=[
                TextDelta("Need input: "),
                UserInputRequested("pending_1", "Which file?", {"field": "path"}),
            ],
            resumed_events=[
                TextDelta("main.py"),
                RunCompleted(),
            ],
        )
        persistence = FakePendingPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink)

        first_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="debug it",
            )
        )
        resumed_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="main.py",
            )
        )

        self.assertEqual(first_run.status, "pending_user_input")
        self.assertEqual(resumed_run.status, "completed")
        self.assertEqual(agent.started_prompts, ["debug it"])
        self.assertEqual(agent.user_input_answers, ["main.py"])
        self.assertEqual(
            persistence.opened_pending_requests,
            [("pending_1", "user_input", {"field": "path"})],
        )
        self.assertEqual(
            persistence.closed_pending_requests,
            [("pending_1", "resolved")],
        )
        self.assertEqual(
            run_view_sink.views[-3:],
            [
                RunView(
                    run_id="run_1",
                    status="running",
                    text="Need input: ",
                    thinking="",
                    tools=(),
                    pending=None,
                    usage=UsageView(input_tokens=0, output_tokens=0),
                    error=None,
                ),
                RunView(
                    run_id="run_1",
                    status="running",
                    text="Need input: main.py",
                    thinking="",
                    tools=(),
                    pending=None,
                    usage=UsageView(input_tokens=0, output_tokens=0),
                    error=None,
                ),
                RunView(
                    run_id="run_1",
                    status="completed",
                    text="Need input: main.py",
                    thinking="",
                    tools=(),
                    pending=None,
                    usage=UsageView(input_tokens=0, output_tokens=0),
                    error=None,
                ),
            ],
        )

    async def test_run_view_action_answers_open_approval_pending_request(self) -> None:
        agent = FakePendingAgentPort(
            initial_events=[
                ApprovalRequested("pending_1", "Run tests?", {"command": "pytest"}),
            ],
            resumed_events=[
                TextDelta("approved"),
                RunCompleted(),
            ],
        )
        persistence = FakePendingPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink)

        first_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="run tests",
            )
        )
        resumed_run = await use_cases.handle_run_view_action(
            RunViewAction(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                action="approve",
                pending_request_id="pending_1",
            )
        )

        self.assertEqual(first_run.status, "pending_approval")
        self.assertEqual(resumed_run.status, "completed")
        self.assertEqual(agent.approval_answers, [("pending_1", "approve")])
        self.assertEqual(
            persistence.opened_pending_requests,
            [("pending_1", "approval", {"command": "pytest"})],
        )
        self.assertEqual(persistence.closed_pending_requests[0], ("pending_1", "resolved"))

    async def test_resumed_terminal_run_clears_pending_state_and_records_error(self) -> None:
        agent = FakePendingAgentPort(
            initial_events=[
                UserInputRequested("pending_1", "Which file?", {"field": "path"}),
            ],
            resumed_events=[
                RunFailed("boom"),
            ],
        )
        persistence = FakePendingPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink)

        await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="debug it",
            )
        )
        resumed_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="main.py",
            )
        )

        self.assertEqual(resumed_run.status, "failed")
        self.assertEqual(persistence.closed_pending_requests, [("pending_1", "resolved")])
        self.assertEqual(run_view_sink.views[-1].pending, None)
        self.assertEqual(run_view_sink.views[-1].error, "boom")


FIXED_NOW = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


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
        clock=lambda: FIXED_NOW,
        run_id_factory=lambda now: "run_1",
    )


@dataclass
class FakeAgentTurnStream:
    agent_turn: AgentTurn
    _events: tuple[object, ...]

    @property
    def events(self) -> AsyncIterator[object]:
        async def _iterate() -> AsyncIterator[object]:
            for event in self._events:
                yield event

        return _iterate()


class FakePendingAgentPort:
    def __init__(self, *, initial_events: list[object], resumed_events: list[object]) -> None:
        self._initial_events = tuple(initial_events)
        self._resumed_events = tuple(resumed_events)
        self.sessions: list[AgentSession] = []
        self.started_prompts: list[str] = []
        self.user_input_answers: list[str] = []
        self.approval_answers: list[tuple[str, str]] = []
        self._current_phase = "initial"

    async def get_or_create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        session = AgentSession(
            agent_session_id="session_1",
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=agent_name,
            workspace=workspace,
            access_mode=access_mode,
        )
        self.sessions.append(session)
        return session

    async def create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        return await self.get_or_create_session(
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=agent_name,
            workspace=workspace,
            access_mode=access_mode,
        )

    async def start_turn(self, *, agent_session: AgentSession, prompt: str) -> "FakePendingTurn":
        self.started_prompts.append(prompt)
        return FakePendingTurn(self, agent_turn=AgentTurn(agent_turn_id="turn_1"))


class FakePendingTurn:
    def __init__(self, port: FakePendingAgentPort, *, agent_turn: AgentTurn) -> None:
        self._port = port
        self.agent_turn = agent_turn

    @property
    def events(self) -> AsyncIterator[object]:
        async def _iterate() -> AsyncIterator[object]:
            events = (
                self._port._initial_events
                if self._port._current_phase == "initial"
                else self._port._resumed_events
            )
            for event in events:
                yield event

        return _iterate()

    async def answer_user_input(self, text: str) -> None:
        self._port.user_input_answers.append(text)
        self._port._current_phase = "resumed"

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        self._port.approval_answers.append((pending_request_id, decision))
        self._port._current_phase = "resumed"

    async def stop(self) -> None:
        self._port._current_phase = "resumed"


class FakePendingPersistence:
    def __init__(self) -> None:
        self.created_runs = []
        self.run_events: dict[str, list[object]] = {}
        self.terminal_statuses: list[tuple[str, str, str]] = []
        self.opened_pending_requests: list[tuple[str, str, dict[str, object]]] = []
        self.closed_pending_requests: list[tuple[str, str]] = []
        self.saved_agent_sessions = []

    async def record_run_created(self, run) -> None:
        self.created_runs.append(run)
        self.run_events[run.run_id] = []

    async def record_run_event(self, *, run_id: str, event: object) -> None:
        self.run_events[run_id].append(event)

    async def record_run_terminal_status(self, *, run_id: str, status: str, updated_at: str) -> None:
        self.terminal_statuses.append((run_id, status, updated_at))

    async def open_pending_request(
        self,
        *,
        run_id: str,
        pending_request: PendingRequestView,
    ) -> None:
        self.opened_pending_requests.append(
            (pending_request.pending_request_id, pending_request.kind, pending_request.payload)
        )

    async def close_pending_request(self, *, pending_request_id: str, status: str) -> None:
        self.closed_pending_requests.append((pending_request_id, status))

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        raise AssertionError("pending flow should not clear sessions")

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

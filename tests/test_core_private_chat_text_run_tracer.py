import ast
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import unittest

from c_auto_bridge.core.agent_events import RunCompleted, TextDelta
from c_auto_bridge.core.agent_session import AgentSession, AgentTurn, Workspace
from c_auto_bridge.core.run import RunStatus
from c_auto_bridge.core.run_view import RunView, UsageView
from c_auto_bridge.core.use_cases import CoreUseCases, PrivateChatTextMessage
from c_auto_bridge.core.workspace import WorkspaceValidator
from c_auto_bridge.ports.agent import AgentThreadNotFound


class CorePrivateChatTextRunTracerTest(unittest.IsolatedAsyncioTestCase):
    async def test_private_chat_text_message_starts_run_and_records_progress(self) -> None:
        agent = FakeAgentPort(
            events=[
                TextDelta("hello"),
                TextDelta(" world"),
                RunCompleted(),
            ]
        )
        persistence = FakeRunPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = CoreUseCases(
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

        run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="ship it",
            )
        )

        self.assertEqual(run.run_id, "run_1")
        self.assertEqual(run.status, "completed")
        self.assertEqual(agent.started_prompts, ["ship it"])
        self.assertEqual(agent.sessions[0].workspace.path, "D:/Workspace/ai-projects/aw-bot")
        self.assertEqual(agent.sessions[0].access_mode, "workspace")
        self.assertEqual(persistence.created_runs[0].agent_session_id, "session_1")
        self.assertEqual(persistence.created_runs[0].agent_turn_id, "turn_1")
        self.assertEqual([event.kind for event in persistence.run_events["run_1"]], ["text_delta", "text_delta", "run_completed"])
        self.assertEqual(persistence.terminal_statuses, [("run_1", "completed", FIXED_NOW.isoformat())])
        self.assertEqual(
            run_view_sink.views,
            [
                RunView(
                    run_id="run_1",
                    status="running",
                    text="",
                    thinking="",
                    tools=(),
                    pending=None,
                    usage=UsageView(input_tokens=0, output_tokens=0),
                    error=None,
                ),
                RunView(
                    run_id="run_1",
                    status="running",
                    text="hello",
                    thinking="",
                    tools=(),
                    pending=None,
                    usage=UsageView(input_tokens=0, output_tokens=0),
                    error=None,
                ),
                RunView(
                    run_id="run_1",
                    status="running",
                    text="hello world",
                    thinking="",
                    tools=(),
                    pending=None,
                    usage=UsageView(input_tokens=0, output_tokens=0),
                    error=None,
                ),
                RunView(
                    run_id="run_1",
                    status="completed",
                    text="hello world",
                    thinking="",
                    tools=(),
                    pending=None,
                    usage=UsageView(input_tokens=0, output_tokens=0),
                    error=None,
                ),
            ],
        )

    async def test_stale_agent_session_is_replaced_and_turn_is_retried(self) -> None:
        agent = FakeStaleSessionAgentPort()
        persistence = FakeRunPersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = CoreUseCases(
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
            agent_name="opencode",
            clock=lambda: FIXED_NOW,
            run_id_factory=lambda now: "run_1",
        )

        run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="ship it",
            )
        )

        self.assertEqual(run.status, "completed")
        self.assertEqual(agent.started_session_ids, ["stale_session", "fresh_session"])
        self.assertEqual(persistence.created_runs[0].agent_session_id, "fresh_session")
        self.assertEqual(
            [session.agent_session_id for session in persistence.saved_agent_sessions],
            ["stale_session", "fresh_session"],
        )

    def test_core_modules_do_not_import_runtime_or_provider_adapters(self) -> None:
        forbidden_prefixes = (
            "c_auto_bridge.agent",
            "c_auto_bridge.feishu",
            "c_auto_bridge.runtime",
            "c_auto_bridge.store.file_store",
        )
        core_dir = Path("c_auto_bridge/core")

        for path in core_dir.glob("*.py"):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = []
            for node in ast.walk(module):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported.append(node.module)
            for name in imported:
                self.assertFalse(
                    name.startswith(forbidden_prefixes),
                    msg=f"{path} imports forbidden module {name}",
                )


FIXED_NOW = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


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

    async def answer_user_input(self, text: str) -> None:
        raise AssertionError("tracer flow should not answer user input")

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        raise AssertionError("tracer flow should not answer approval")

    async def stop(self) -> None:
        raise AssertionError("tracer flow should not stop turns")


class FakeAgentPort:
    def __init__(self, *, events: list[object]) -> None:
        self._events = tuple(events)
        self.sessions: list[AgentSession] = []
        self.started_prompts: list[str] = []

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

    async def start_turn(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
        model: str | None,
        opencode_agent: str | None = None,
    ) -> FakeAgentTurnStream:
        self.started_prompts.append(prompt)
        return FakeAgentTurnStream(
            agent_turn=AgentTurn(agent_turn_id="turn_1"),
            _events=self._events,
        )


class FakeStaleSessionAgentPort:
    def __init__(self) -> None:
        self.started_session_ids: list[str] = []

    async def get_or_create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        return AgentSession(
            agent_session_id="stale_session",
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=agent_name,
            workspace=workspace,
            access_mode=access_mode,
        )

    async def create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        return AgentSession(
            agent_session_id="fresh_session",
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=agent_name,
            workspace=workspace,
            access_mode=access_mode,
        )

    async def start_turn(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
        model: str | None,
        opencode_agent: str | None = None,
    ) -> FakeAgentTurnStream:
        self.started_session_ids.append(agent_session.agent_session_id)
        if agent_session.agent_session_id == "stale_session":
            raise AgentThreadNotFound("Session not found: stale_session")
        return FakeAgentTurnStream(
            agent_turn=AgentTurn(agent_turn_id="turn_1"),
            _events=(TextDelta("ok"), RunCompleted()),
        )


class FakeRunPersistence:
    def __init__(self) -> None:
        self.created_runs = []
        self.run_events: dict[str, list[object]] = {}
        self.terminal_statuses: list[tuple[str, RunStatus, str]] = []
        self.saved_agent_sessions = []

    async def record_run_created(self, run) -> None:
        self.created_runs.append(run)
        self.run_events[run.run_id] = []

    async def record_run_event(self, *, run_id: str, event: object) -> None:
        self.run_events[run_id].append(event)

    async def record_run_terminal_status(
        self,
        *,
        run_id: str,
        status: RunStatus,
        updated_at: str,
    ) -> None:
        self.terminal_statuses.append((run_id, status, updated_at))

    async def open_pending_request(self, *, run_id: str, pending_request) -> None:
        raise AssertionError("tracer flow should not open pending requests")

    async def close_pending_request(self, *, pending_request_id: str, status: str) -> None:
        raise AssertionError("tracer flow should not close pending requests")

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        raise AssertionError("tracer flow should not clear sessions")

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

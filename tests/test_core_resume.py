from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import unittest

from c_auto_bridge.core.agent_events import RunCompleted, TextDelta
from c_auto_bridge.core.agent_session import AgentSession, HistoricalAgentSession, Workspace
from c_auto_bridge.core.run_view import RunView
from c_auto_bridge.core.use_cases import (
    CoreUseCases,
    PrivateChatTextMessage,
    ResumeSessionList,
    ResumeSessionRestored,
)
from c_auto_bridge.core.workspace import WorkspaceValidator


class CoreResumeTest(unittest.IsolatedAsyncioTestCase):
    async def test_resume_lists_only_compatible_sessions(self) -> None:
        persistence = FakeResumePersistence(
            historical_sessions=[
                _historical("session_ok", "codex", "D:/repo", "workspace"),
                _historical("session_agent", "opencode", "D:/repo", "workspace"),
                _historical("session_workspace", "codex", "D:/other", "workspace"),
                _historical("session_access", "codex", "D:/repo", "read-only"),
            ]
        )
        use_cases = _build_use_cases(persistence)

        result = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="/resume",
            )
        )

        self.assertEqual(
            result,
            ResumeSessionList(
                sessions=(
                    _historical("session_ok", "codex", "D:/repo", "workspace"),
                )
            ),
        )

    async def test_resume_restores_selected_compatible_session(self) -> None:
        persistence = FakeResumePersistence(
            historical_sessions=[_historical("session_ok", "codex", "D:/repo", "workspace")]
        )
        use_cases = _build_use_cases(persistence)

        result = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="/resume session_ok",
            )
        )

        self.assertEqual(
            result,
            ResumeSessionRestored(
                session=_historical("session_ok", "codex", "D:/repo", "workspace")
            ),
        )
        self.assertEqual(persistence.resumed_session_ids, ["session_ok"])

    async def test_resume_rejects_different_agent_session(self) -> None:
        persistence = FakeResumePersistence(
            historical_sessions=[_historical("session_agent", "opencode", "D:/repo", "workspace")]
        )
        use_cases = _build_use_cases(persistence)

        with self.assertRaisesRegex(ValueError, "different agent"):
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/resume session_agent",
                )
            )

    async def test_resume_rejects_different_workspace_session(self) -> None:
        persistence = FakeResumePersistence(
            historical_sessions=[_historical("session_workspace", "codex", "D:/other", "workspace")]
        )
        use_cases = _build_use_cases(persistence)

        with self.assertRaisesRegex(ValueError, "different workspace"):
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/resume session_workspace",
                )
            )

    async def test_resume_rejects_incompatible_access_mode_session(self) -> None:
        persistence = FakeResumePersistence(
            historical_sessions=[_historical("session_access", "codex", "D:/repo", "read-only")]
        )
        use_cases = _build_use_cases(persistence)

        with self.assertRaisesRegex(ValueError, "incompatible access mode"):
            await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="/resume session_access",
                )
            )

    async def test_resumed_session_is_used_for_next_run(self) -> None:
        persistence = FakeResumePersistence(
            historical_sessions=[_historical("session_ok", "codex", "D:/repo", "workspace")]
        )
        agent = FakeAgentPort()
        use_cases = _build_use_cases(persistence, agent=agent)

        await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="/resume session_ok",
            )
        )
        run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="continue",
            )
        )

        self.assertEqual(agent.started_session_ids, ["session_ok"])
        self.assertEqual(run.agent_session_id, "session_ok")


def _build_use_cases(
    persistence: "FakeResumePersistence",
    agent: "FakeAgentPort | None" = None,
) -> CoreUseCases:
    return CoreUseCases(
        agent=agent or FakeAgentPort(),
        persistence=persistence,
        run_view_sink=FakeRunViewSink(),
        workspace=Workspace(path="D:/repo"),
        workspace_validator=WorkspaceValidator(
            home_directory=Path("D:/Users/Maple"),
            temp_directory=Path("D:/Temp"),
            system_directories=(),
        ),
        access_mode="workspace",
        agent_name="codex",
        clock=lambda: datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc),
        run_id_factory=lambda now: "run_1",
    )


def _historical(
    agent_session_id: str,
    agent_name: str,
    workspace_path: str,
    access_mode: str | None,
) -> HistoricalAgentSession:
    return HistoricalAgentSession(
        agent_session_id=agent_session_id,
        private_chat_scope_id="chat_1",
        user_id="user_1",
        agent_name=agent_name,
        workspace=Workspace(path=workspace_path),
        access_mode=access_mode,
        updated_at="2026-06-06T12:00:00+00:00",
    )


class FakeResumePersistence:
    def __init__(self, historical_sessions: list[HistoricalAgentSession]) -> None:
        self.historical_sessions = historical_sessions
        self.resumed_session_ids: list[str] = []
        self.created_runs = []
        self.run_events: dict[str, list[object]] = {}
        self.terminal_statuses: list[tuple[str, str, str]] = []

    async def record_run_created(self, run) -> None:
        self.created_runs.append(run)
        self.run_events[run.run_id] = []

    async def record_run_event(self, *, run_id: str, event: object) -> None:
        self.run_events[run_id].append(event)

    async def record_run_terminal_status(self, *, run_id: str, status: str, updated_at: str) -> None:
        self.terminal_statuses.append((run_id, status, updated_at))

    async def open_pending_request(self, *, run_id: str, pending_request) -> None:
        raise AssertionError("resume tests should not open pending requests")

    async def close_pending_request(self, *, pending_request_id: str, status: str) -> None:
        raise AssertionError("resume tests should not close pending requests")

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        raise AssertionError("resume tests should not clear current session")

    async def save_named_workspace(self, *, workspace) -> None:
        raise AssertionError("resume tests should not save named workspaces")

    async def get_named_workspace(self, *, name: str):
        raise AssertionError("resume tests should not get named workspaces")

    async def list_named_workspaces(self) -> list:
        raise AssertionError("resume tests should not list named workspaces")

    async def remove_named_workspace(self, *, name: str) -> None:
        raise AssertionError("resume tests should not remove named workspaces")

    async def save_agent_session(self, *, agent_session: HistoricalAgentSession) -> None:
        self.resumed_session_ids.append(agent_session.agent_session_id)

    async def list_agent_sessions(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
    ) -> list[HistoricalAgentSession]:
        return [
            session
            for session in self.historical_sessions
            if session.private_chat_scope_id == private_chat_scope_id and session.user_id == user_id
        ]


class FakeAgentPort:
    def __init__(self) -> None:
        self.started_session_ids: list[str] = []

    async def create_session(self, **kwargs) -> AgentSession:
        raise AssertionError("resume tests should not create sessions")

    async def get_or_create_session(self, **kwargs) -> AgentSession:
        raise AssertionError("resume tests should not get sessions")

    async def start_turn(self, **kwargs):
        agent_session = kwargs["agent_session"]
        self.started_session_ids.append(agent_session.agent_session_id)
        return FakeTurnStream(agent_session.agent_session_id)


@dataclass
class FakeRunViewSink:
    async def publish(self, *, private_chat_scope_id: str, run_view: RunView) -> None:
        return None


@dataclass
class FakeTurn:
    agent_turn_id: str


class FakeTurnStream:
    def __init__(self, agent_session_id: str) -> None:
        self.agent_turn = FakeTurn(agent_turn_id=f"turn_{agent_session_id}")

    @property
    def events(self) -> AsyncIterator[object]:
        return self._events()

    async def _events(self) -> AsyncIterator[object]:
        yield TextDelta("continued")
        yield RunCompleted()

    async def answer_user_input(self, text: str) -> None:
        raise AssertionError("resume tests should not answer user input")

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        raise AssertionError("resume tests should not answer approval")

    async def stop(self) -> None:
        raise AssertionError("resume tests should not stop turns")


if __name__ == "__main__":
    unittest.main()

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from c_auto_bridge.core.agent_events import RunCompleted, TextDelta
from c_auto_bridge.core.agent_session import AgentSession, AgentTurn, Workspace
from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.core.run_view import RunView
from c_auto_bridge.core.use_cases import CoreUseCases, PrivateChatTextMessage
from c_auto_bridge.core.workspace import WorkspaceValidator


class CoreQueueNextTurnFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_messages_during_active_run_queue_and_merge_for_next_turn(self) -> None:
        clock = AdjustableClock(datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc))
        agent = FakeQueuedAgentPort()
        persistence = FakeQueuePersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink, clock)

        first_run_task = asyncio.create_task(
            use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="first",
                )
            )
        )
        await agent.wait_for_started_prompts(1)

        queued_result = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="second",
            )
        )
        clock.advance(seconds=1)
        await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="third",
            )
        )

        self.assertEqual(queued_result.status, "running")
        self.assertEqual(agent.started_prompts, ["first"])

        agent.release_first_turn()
        final_run = await first_run_task

        self.assertEqual(final_run.status, "completed")
        self.assertEqual(agent.started_prompts, ["first", "second\nthird"])
        self.assertEqual(agent.started_attachments, [(), ()])
        self.assertEqual(
            [run.run_id for run in persistence.created_runs],
            ["run_1", "run_2"],
        )

    async def test_queue_is_scoped_per_private_chat_scope(self) -> None:
        clock = AdjustableClock(datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc))
        agent = FakeQueuedAgentPort()
        persistence = FakeQueuePersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink, clock)

        first_run_task = asyncio.create_task(
            use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="first",
                )
            )
        )
        await agent.wait_for_started_prompts(1)

        other_scope_run = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_2",
                user_id="user_1",
                text="other scope",
            )
        )

        self.assertEqual(other_scope_run.status, "completed")
        self.assertEqual(agent.started_prompts, ["first", "other scope"])

        agent.release_first_turn()
        await first_run_task

    async def test_queued_next_turn_preserves_merged_attachments(self) -> None:
        clock = AdjustableClock(datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc))
        agent = FakeQueuedAgentPort()
        persistence = FakeQueuePersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink, clock)

        first_run_task = asyncio.create_task(
            use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="first",
                )
            )
        )
        await agent.wait_for_started_prompts(1)
        image = Attachment(kind="image", path="D:/cache/a.png", name="a.png")
        file = Attachment(kind="file", path="D:/cache/b.txt", name="b.txt")

        await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="second",
                attachments=(image,),
            )
        )
        clock.advance(seconds=1)
        await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="",
                attachments=(file,),
            )
        )

        agent.release_first_turn()
        final_run = await first_run_task

        self.assertEqual(final_run.status, "completed")
        self.assertEqual(agent.started_prompts, ["first", "second"])
        self.assertEqual(agent.started_attachments, [(), (image, file)])

    async def test_attachment_only_queued_message_starts_next_turn_without_prompt_newline(self) -> None:
        clock = AdjustableClock(datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc))
        agent = FakeQueuedAgentPort()
        persistence = FakeQueuePersistence()
        run_view_sink = FakeRunViewSink()
        use_cases = build_use_cases(agent, persistence, run_view_sink, clock)

        first_run_task = asyncio.create_task(
            use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    text="first",
                )
            )
        )
        await agent.wait_for_started_prompts(1)
        image = Attachment(kind="image", path="D:/cache/only.png", name="only.png")

        queued_result = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="",
                attachments=(image,),
            )
        )

        self.assertEqual(queued_result.status, "running")
        agent.release_first_turn()
        final_run = await first_run_task

        self.assertEqual(final_run.status, "completed")
        self.assertEqual(agent.started_prompts, ["first", ""])
        self.assertEqual(agent.started_attachments, [(), (image,)])
        self.assertEqual(
            [run.run_id for run in persistence.created_runs],
            ["run_1", "run_2"],
        )


def build_use_cases(agent, persistence, run_view_sink, clock) -> CoreUseCases:
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
        clock=clock.now,
        run_id_factory=RunIdFactory(),
    )


class AdjustableClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, *, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class RunIdFactory:
    def __init__(self) -> None:
        self._value = 0

    def __call__(self, now: datetime) -> str:
        self._value += 1
        return f"run_{self._value}"


class FakeQueuedAgentPort:
    def __init__(self) -> None:
        self.sessions: list[AgentSession] = []
        self.started_prompts: list[str] = []
        self.started_attachments: list[tuple[Attachment, ...]] = []
        self._first_turn_complete = asyncio.Event()

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
            agent_session_id=f"session_{private_chat_scope_id}",
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
        attachments: tuple[Attachment, ...] = (),
    ) -> "FakeQueuedTurn":
        self.started_prompts.append(prompt)
        self.started_attachments.append(attachments)
        if len(self.started_prompts) == 1 and agent_session.private_chat_scope_id == "chat_1":
            return FakeQueuedTurn(
                agent_turn=AgentTurn(agent_turn_id="turn_1"),
                _events=self._first_turn_events(),
            )
        return FakeQueuedTurn(
            agent_turn=AgentTurn(agent_turn_id=f"turn_{len(self.started_prompts)}"),
            _events=self._immediate_events(prompt),
        )

    async def wait_for_started_prompts(self, count: int) -> None:
        for _ in range(50):
            if len(self.started_prompts) >= count:
                return
            await asyncio.sleep(0)
        raise AssertionError(f"expected at least {count} started prompts, got {self.started_prompts}")

    def release_first_turn(self) -> None:
        self._first_turn_complete.set()

    async def _first_turn_events(self) -> AsyncIterator[object]:
        yield TextDelta("working")
        await self._first_turn_complete.wait()
        yield RunCompleted()

    async def _immediate_events(self, prompt: str) -> AsyncIterator[object]:
        yield TextDelta(prompt)
        yield RunCompleted()


@dataclass
class FakeQueuedTurn:
    agent_turn: AgentTurn
    _events: AsyncIterator[object]

    @property
    def events(self) -> AsyncIterator[object]:
        return self._events

    async def answer_user_input(self, text: str) -> None:
        raise AssertionError("queue flow should not answer user input")

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        raise AssertionError("queue flow should not answer approval")

    async def stop(self) -> None:
        raise AssertionError("queue flow should not stop turns")


class FakeQueuePersistence:
    def __init__(self) -> None:
        self.created_runs = []
        self.run_events: dict[str, list[object]] = {}
        self.terminal_statuses: list[tuple[str, str, str]] = []
        self.saved_agent_sessions = []

    async def record_run_created(self, run) -> None:
        self.created_runs.append(run)
        self.run_events[run.run_id] = []

    async def record_run_event(self, *, run_id: str, event: object) -> None:
        self.run_events[run_id].append(event)

    async def record_run_terminal_status(self, *, run_id: str, status: str, updated_at: str) -> None:
        self.terminal_statuses.append((run_id, status, updated_at))

    async def open_pending_request(self, *, run_id: str, pending_request) -> None:
        raise AssertionError("queue flow should not open pending requests")

    async def close_pending_request(self, *, pending_request_id: str, status: str) -> None:
        raise AssertionError("queue flow should not close pending requests")

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        raise AssertionError("queue flow should not clear sessions")

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

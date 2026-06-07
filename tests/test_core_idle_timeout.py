import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import unittest

from c_auto_bridge.core.agent_events import RunCompleted, TextDelta
from c_auto_bridge.core.agent_session import AgentSession, AgentTurn, Workspace
from c_auto_bridge.core.idle_timeout import IdleTimeoutHandle
from c_auto_bridge.core.run_view import RunView
from c_auto_bridge.core.use_cases import CoreUseCases, IdleTimeoutStatus, PrivateChatTextMessage
from c_auto_bridge.core.workspace import WorkspaceValidator


class CoreIdleTimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_default_idle_timeout_is_off(self) -> None:
        use_cases = build_use_cases(
            agent=FakeIdleAgentPort(),
            persistence=FakeIdlePersistence(),
            run_view_sink=FakeRunViewSink(),
            scheduler=FakeIdleTimeoutScheduler(),
        )

        result = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id="chat_1",
                user_id="user_1",
                text="/timeout default",
            )
        )

        self.assertEqual(result, IdleTimeoutStatus(scope_timeout_minutes=None))

    async def test_timeout_commands_set_off_and_default_scope_override(self) -> None:
        use_cases = build_use_cases(
            agent=FakeIdleAgentPort(),
            persistence=FakeIdlePersistence(),
            run_view_sink=FakeRunViewSink(),
            scheduler=FakeIdleTimeoutScheduler(),
            default_idle_timeout_seconds=120,
        )

        set_result = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage("chat_1", "user_1", "/timeout 5")
        )
        off_result = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage("chat_1", "user_1", "/timeout off")
        )
        default_result = await use_cases.handle_private_chat_text(
            PrivateChatTextMessage("chat_1", "user_1", "/timeout default")
        )

        self.assertEqual(set_result, IdleTimeoutStatus(scope_timeout_minutes=5))
        self.assertEqual(off_result, IdleTimeoutStatus(scope_timeout_minutes=None))
        self.assertEqual(default_result, IdleTimeoutStatus(scope_timeout_minutes=2))

    async def test_idle_timeout_resets_on_output_and_times_out_when_idle(self) -> None:
        agent = FakeIdleAgentPort()
        persistence = FakeIdlePersistence()
        run_view_sink = FakeRunViewSink()
        scheduler = FakeIdleTimeoutScheduler()
        use_cases = build_use_cases(
            agent=agent,
            persistence=persistence,
            run_view_sink=run_view_sink,
            scheduler=scheduler,
            default_idle_timeout_seconds=60,
        )

        run_task = asyncio.create_task(
            use_cases.handle_private_chat_text(
                PrivateChatTextMessage("chat_1", "user_1", "work")
            )
        )
        await agent.wait_for_active_turn()

        await scheduler.advance(30)
        await agent.emit(TextDelta("still working"))
        await scheduler.advance(30)
        await scheduler.advance(61)
        result = await run_task

        self.assertEqual(result.status, "timed_out")
        self.assertEqual(agent.stopped_turn_ids, ["turn_1"])
        self.assertEqual(run_view_sink.views[-1].status, "timed_out")


def build_use_cases(
    *,
    agent,
    persistence,
    run_view_sink,
    scheduler,
    default_idle_timeout_seconds: float | None = None,
) -> CoreUseCases:
    return CoreUseCases(
        agent=agent,
        persistence=persistence,
        run_view_sink=run_view_sink,
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
        default_idle_timeout_seconds=default_idle_timeout_seconds,
        idle_timeout_scheduler=scheduler,
    )


class FakeIdleTimeoutScheduler:
    def __init__(self) -> None:
        self.now = 0.0
        self._entries: list[ScheduledEntry] = []

    def schedule(
        self,
        *,
        delay_seconds: float,
        callback: Callable[[], Awaitable[None]],
    ) -> IdleTimeoutHandle:
        entry = ScheduledEntry(due_at=self.now + delay_seconds, callback=callback)
        self._entries.append(entry)
        return entry

    async def advance(self, seconds: float) -> None:
        self.now += seconds
        while True:
            ready = [entry for entry in self._entries if not entry.cancelled and entry.due_at <= self.now]
            if not ready:
                return
            ready.sort(key=lambda entry: entry.due_at)
            entry = ready[0]
            entry.cancelled = True
            await entry.callback()
            await asyncio.sleep(0)


@dataclass
class ScheduledEntry:
    due_at: float
    callback: Callable[[], Awaitable[None]]
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeIdleAgentPort:
    def __init__(self) -> None:
        self._current_session: AgentSession | None = None
        self._active_turn = asyncio.Event()
        self._queue: asyncio.Queue[object] | None = None
        self.stopped_turn_ids: list[str] = []

    async def get_or_create_session(self, **kwargs) -> AgentSession:
        if self._current_session is None:
            self._current_session = await self.create_session(**kwargs)
        return self._current_session

    async def create_session(self, **kwargs) -> AgentSession:
        self._current_session = AgentSession(
            agent_session_id="session_1",
            private_chat_scope_id=kwargs["private_chat_scope_id"],
            user_id=kwargs["user_id"],
            agent_name=kwargs["agent_name"],
            workspace=kwargs["workspace"],
            access_mode=kwargs["access_mode"],
        )
        return self._current_session

    async def start_turn(self, **kwargs) -> "FakeIdleTurnStream":
        self._queue = asyncio.Queue()
        self._active_turn.set()
        return FakeIdleTurnStream(port=self, queue=self._queue)

    async def emit(self, event: object) -> None:
        if self._queue is None:
            raise AssertionError("turn is not active")
        await self._queue.put(event)

    async def wait_for_active_turn(self) -> None:
        await self._active_turn.wait()


@dataclass
class FakeIdleTurnStream:
    port: FakeIdleAgentPort
    queue: asyncio.Queue[object]

    @property
    def agent_turn(self) -> AgentTurn:
        return AgentTurn(agent_turn_id="turn_1")

    @property
    def events(self) -> AsyncIterator[object]:
        return self._events()

    async def _events(self) -> AsyncIterator[object]:
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def answer_user_input(self, text: str) -> None:
        raise AssertionError("idle timeout tests should not answer user input")

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        raise AssertionError("idle timeout tests should not answer approval")

    async def stop(self) -> None:
        self.port.stopped_turn_ids.append("turn_1")
        await self.queue.put(None)


class FakeIdlePersistence:
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
        raise AssertionError("idle timeout tests should not open pending requests")

    async def close_pending_request(self, *, pending_request_id: str, status: str) -> None:
        raise AssertionError("idle timeout tests should not close pending requests")

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        raise AssertionError("idle timeout tests should not clear current session")

    async def save_named_workspace(self, *, workspace) -> None:
        raise AssertionError("idle timeout tests should not save named workspaces")

    async def get_named_workspace(self, *, name: str):
        raise AssertionError("idle timeout tests should not get named workspaces")

    async def list_named_workspaces(self) -> list:
        raise AssertionError("idle timeout tests should not list named workspaces")

    async def remove_named_workspace(self, *, name: str) -> None:
        raise AssertionError("idle timeout tests should not remove named workspaces")

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

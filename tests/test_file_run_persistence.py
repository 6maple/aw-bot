from datetime import datetime, timezone
import json
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from c_auto_bridge.core.agent_events import TextDelta
from c_auto_bridge.core.agent_session import HistoricalAgentSession, Workspace
from c_auto_bridge.core.pending_request import PendingRequest
from c_auto_bridge.core.run import Run
from c_auto_bridge.core.run_view import RunView
from c_auto_bridge.core.use_cases import CoreUseCases, PrivateChatTextMessage, WorkspaceListResult, WorkspaceSaved
from c_auto_bridge.core.workspace import NamedWorkspace, WorkspaceValidator
from c_auto_bridge.session.models import SessionRef
from c_auto_bridge.store.file_run_persistence import FileRunPersistence
from c_auto_bridge.store.file_store import FileStore


FIXED_NOW = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


class FileRunPersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_records_run_events_pending_and_terminal_status(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            persistence = FileRunPersistence(store)
            session = _session()
            store.save_session(session)
            store.set_current_session(session.owner_feishu_user_id, session.bot_session_id)
            run = _run()

            await persistence.record_run_created(run)
            await persistence.record_run_event(run_id=run.run_id, event=TextDelta("hello"))
            await persistence.open_pending_request(
                run_id=run.run_id,
                pending_request=PendingRequest(
                    pending_request_id="pending_1",
                    run_id=run.run_id,
                    kind="user_input",
                    payload={"field": "path"},
                ),
            )
            await persistence.close_pending_request(
                pending_request_id="pending_1",
                status="resolved",
            )
            await persistence.record_run_terminal_status(
                run_id=run.run_id,
                status="completed",
                updated_at="2026-06-06T12:05:00+00:00",
            )

            stored_run = store.get_run(run.run_id)
            self.assertIsNotNone(stored_run)
            self.assertEqual(stored_run.status, "completed")
            self.assertEqual(store.get_open_pending_by_user(session.owner_feishu_user_id), None)
            lines = (store.logs_dir / f"{run.run_id}.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertIn('"kind": "text_delta"', lines[0])

    async def test_clear_current_session_by_scope_removes_matching_binding_only(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            persistence = FileRunPersistence(store)
            matching_session = _session()
            other_session = SessionRef(
                bot_session_id="s_2",
                owner_feishu_user_id="owner_2",
                owner_chat_id="chat_2",
                agent="codex",
                codex_thread_id="thr_2",
                title="other",
                cwd="D:/repo-2",
                access_mode="workspace",
                status="idle",
                created_at="2026-06-06T12:00:00+00:00",
                updated_at="2026-06-06T12:00:00+00:00",
            )
            store.save_session(matching_session)
            store.save_session(other_session)
            store.set_current_session("owner_1", "s_1")
            store.set_current_session("owner_2", "s_2")

            await persistence.clear_current_session(private_chat_scope_id="chat_1")

            self.assertIsNone(store.get_current_session("owner_1"))
            self.assertIsNotNone(store.get_current_session("owner_2"))

    async def test_named_workspace_methods_delegate_to_store(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            persistence = FileRunPersistence(store)
            workspace = NamedWorkspace(
                name="repo",
                workspace=Workspace(path="D:/repo"),
                updated_at="2026-06-06T12:00:00+00:00",
            )

            await persistence.save_named_workspace(workspace=workspace)

            self.assertEqual(await persistence.get_named_workspace(name="repo"), workspace)
            self.assertEqual(await persistence.list_named_workspaces(), [workspace])

            await persistence.remove_named_workspace(name="repo")

            self.assertIsNone(await persistence.get_named_workspace(name="repo"))

    async def test_saves_and_lists_historical_agent_sessions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            persistence = FileRunPersistence(store)
            older = HistoricalAgentSession(
                agent_session_id="session_old",
                private_chat_scope_id="chat_1",
                user_id="owner_1",
                agent_name="codex",
                workspace=Workspace(path="D:/repo"),
                access_mode="workspace",
                updated_at="2026-06-06T11:00:00+00:00",
            )
            newer = HistoricalAgentSession(
                agent_session_id="session_new",
                private_chat_scope_id="chat_1",
                user_id="owner_1",
                agent_name="codex",
                workspace=Workspace(path="D:/repo"),
                access_mode="workspace",
                updated_at="2026-06-06T12:00:00+00:00",
            )

            await persistence.save_agent_session(agent_session=older)
            await persistence.save_agent_session(agent_session=newer)

            self.assertEqual(
                await persistence.list_agent_sessions(
                    private_chat_scope_id="chat_1",
                    user_id="owner_1",
                ),
                [newer, older],
            )

    async def test_writes_core_vocabulary_records(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            persistence = FileRunPersistence(store)
            session = HistoricalAgentSession(
                agent_session_id="s_1",
                private_chat_scope_id="chat_1",
                user_id="owner_1",
                agent_name="codex",
                workspace=Workspace(path="D:/repo"),
                access_mode="workspace",
                updated_at="2026-06-06T12:00:00+00:00",
            )
            run = _run()

            await persistence.save_agent_session(agent_session=session)
            await persistence.record_run_created(run)
            await persistence.open_pending_request(
                run_id=run.run_id,
                pending_request=PendingRequest(
                    pending_request_id="pending_1",
                    run_id=run.run_id,
                    kind="approval",
                    payload={"command": "pytest"},
                ),
            )

            session_record = json.loads(
                (Path(tmpdir) / "core_agent_sessions" / "s_1.json").read_text(encoding="utf-8")
            )
            run_record = json.loads(
                (Path(tmpdir) / "core_runs" / "run_1.json").read_text(encoding="utf-8")
            )
            pending_record = json.loads(
                (Path(tmpdir) / "core_pending_requests" / "pending_1.json").read_text(encoding="utf-8")
            )

            self.assertEqual(session_record["agent_session_id"], "s_1")
            self.assertEqual(session_record["private_chat_scope_id"], "chat_1")
            self.assertEqual(run_record["agent_session_id"], "s_1")
            self.assertEqual(run_record["private_chat_scope_id"], "chat_1")
            self.assertEqual(pending_record["pending_request_id"], "pending_1")
            self.assertEqual(pending_record["kind"], "approval")

    async def test_appends_core_run_logs_and_startup_diagnostics(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            persistence = FileRunPersistence(store)

            await persistence.record_run_error(run_id="run_1", error="boom")
            await persistence.record_startup_diagnostic(
                level="error",
                message="missing env",
                details={"name": "CODEX_HOME"},
            )

            run_log = (Path(tmpdir) / "core_logs" / "runs" / "run_1.jsonl").read_text(encoding="utf-8").splitlines()
            startup_log = (Path(tmpdir) / "core_logs" / "startup.jsonl").read_text(encoding="utf-8").splitlines()

            self.assertEqual(json.loads(run_log[0])["kind"], "run_error")
            self.assertEqual(json.loads(run_log[0])["error"], "boom")
            self.assertEqual(json.loads(startup_log[0])["kind"], "startup_diagnostic")
            self.assertEqual(json.loads(startup_log[0])["details"], {"name": "CODEX_HOME"})

    async def test_recover_incomplete_updates_core_records(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            persistence = FileRunPersistence(store)
            session = _session()
            store.save_session(session)
            await persistence.record_run_created(_run())
            await persistence.open_pending_request(
                run_id="run_1",
                pending_request=PendingRequest(
                    pending_request_id="pending_1",
                    run_id="run_1",
                    kind="user_input",
                    payload={"field": "path"},
                ),
            )

            await persistence.recover_incomplete(updated_at="2026-06-06T12:05:00+00:00")

            run_record = json.loads((Path(tmpdir) / "core_runs" / "run_1.json").read_text(encoding="utf-8"))
            pending_record = json.loads(
                (Path(tmpdir) / "core_pending_requests" / "pending_1.json").read_text(encoding="utf-8")
            )

            self.assertEqual(run_record["status"], "interrupted")
            self.assertEqual(run_record["updated_at"], "2026-06-06T12:05:00+00:00")
            self.assertEqual(pending_record["status"], "cancelled")
            self.assertEqual(pending_record["updated_at"], "2026-06-06T12:05:00+00:00")

    async def test_core_use_cases_persist_named_workspaces_with_file_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir) / "repo"
            home_dir = Path(tmpdir) / "home"
            workspace_dir.mkdir()
            home_dir.mkdir()
            store = FileStore(tmpdir)
            persistence = FileRunPersistence(store)
            use_cases = CoreUseCases(
                agent=FakeAgentPort(),
                persistence=persistence,
                run_view_sink=FakeRunViewSink(),
                workspace=Workspace(path=str(workspace_dir.resolve())),
                workspace_validator=WorkspaceValidator(
                    home_directory=home_dir,
                    temp_directory=Path(tmpdir) / "temp",
                    system_directories=(),
                ),
                access_mode="workspace",
                agent_name="codex",
                clock=lambda: FIXED_NOW,
                run_id_factory=lambda now: "run_1",
            )

            saved = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="owner_1",
                    text="/ws save repo",
                )
            )
            listed = await use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id="chat_1",
                    user_id="owner_1",
                    text="/ws list",
                )
            )

            expected = NamedWorkspace(
                name="repo",
                workspace=Workspace(path=str(workspace_dir.resolve())),
                updated_at="2026-06-06T12:00:00+00:00",
            )
            self.assertEqual(saved, WorkspaceSaved(named_workspace=expected))
            self.assertEqual(listed, WorkspaceListResult(workspaces=(expected,)))


def _session() -> SessionRef:
    return SessionRef(
        bot_session_id="s_1",
        owner_feishu_user_id="owner_1",
        owner_chat_id="chat_1",
        agent="codex",
        codex_thread_id="thr_1",
        title="session",
        cwd="D:/repo",
        access_mode="workspace",
        status="idle",
        created_at="2026-06-06T12:00:00+00:00",
        updated_at="2026-06-06T12:00:00+00:00",
    )


def _run() -> Run:
    return Run(
        run_id="run_1",
        private_chat_scope_id="chat_1",
        user_id="owner_1",
        agent_session_id="s_1",
        agent_name="codex",
        agent_turn_id="turn_1",
        status="running",
        created_at="2026-06-06T12:00:00+00:00",
        updated_at="2026-06-06T12:00:00+00:00",
    )

class FakeAgentPort:
    async def create_session(self, **kwargs):
        raise AssertionError("workspace commands should not create sessions")

    async def get_or_create_session(self, **kwargs):
        raise AssertionError("workspace commands should not create sessions")

    async def start_turn(self, **kwargs):
        raise AssertionError("workspace commands should not start turns")


class FakeRunViewSink:
    async def publish(self, *, private_chat_scope_id: str, run_view: RunView) -> None:
        raise AssertionError("workspace commands should not publish run views")


if __name__ == "__main__":
    unittest.main()

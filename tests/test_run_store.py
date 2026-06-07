import json
from tempfile import TemporaryDirectory
import unittest

from c_auto_bridge.core.agent_session import Workspace
from c_auto_bridge.core.workspace import NamedWorkspace
from c_auto_bridge.react.events import TextDelta
from c_auto_bridge.store.file_store import FileStore
from c_auto_bridge.store.models import RunRef, StreamCardRef, WorkspaceBinding


class RunStoreTest(unittest.TestCase):
    def test_saves_lists_and_appends_run_data(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            older = _run("run_old", "2026-06-05T10:00:00+08:00")
            newer = _run("run_new", "2026-06-05T11:00:00+08:00")

            store.save_run(older)
            store.save_run(newer)
            store.save_card(_card())
            store.save_workspace(_workspace())
            store.append_run_event("run_new", TextDelta("hello"))
            store.append_run_error("run_new", "boom")

            self.assertEqual(
                [item.run_id for item in store.list_runs("chat_1", 10)],
                ["run_new", "run_old"],
            )
            self.assertEqual(store.get_card("card_1"), _card())
            self.assertEqual(store.get_workspace("chat_1"), _workspace())
            lines = (store.logs_dir / "run_new.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(lines[0])["event"]["kind"], "text_delta")
            self.assertEqual(json.loads(lines[1])["error"], "boom")

    def test_saves_lists_gets_and_removes_named_workspaces(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            older = _named_workspace("repo_old", "D:/repo-old", "2026-06-05T10:00:00+08:00")
            newer = _named_workspace("repo_new", "D:/repo-new", "2026-06-05T11:00:00+08:00")

            store.save_named_workspace(older)
            store.save_named_workspace(newer)

            self.assertEqual(store.get_named_workspace("repo_new"), newer)
            self.assertEqual(store.list_named_workspaces(), [newer, older])

            store.remove_named_workspace("repo_old")

            self.assertIsNone(store.get_named_workspace("repo_old"))
            self.assertEqual(store.list_named_workspaces(), [newer])

    def test_recover_incomplete_marks_runs_and_pending(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            store.save_run(_run("run_1", "2026-06-05T10:00:00+08:00"))
            store.save_card(_card())
            pending = _pending()
            store.save_pending(pending)

            store.recover_incomplete("2026-06-05T12:00:00+08:00")

            self.assertEqual(store.get_run("run_1").status, "interrupted")
            self.assertEqual(store.get_card("card_1").status, "failed")
            self.assertIsNone(store.get_open_pending_by_user("owner_1"))


def _run(run_id: str, updated_at: str) -> RunRef:
    return RunRef(
        run_id=run_id,
        scope_id="chat_1",
        bot_session_id="s_1",
        agent="codex",
        thread_id="thr_1",
        turn_id="turn_1",
        status="running",
        created_at="2026-06-05T10:00:00+08:00",
        updated_at=updated_at,
    )


def _card() -> StreamCardRef:
    return StreamCardRef(
        card_id="card_1",
        run_id="run_new",
        chat_id="chat_1",
        message_id="msg_1",
        status="streaming",
        created_at="2026-06-05T10:00:00+08:00",
        updated_at="2026-06-05T10:00:00+08:00",
    )


def _workspace() -> WorkspaceBinding:
    return WorkspaceBinding(
        scope_id="chat_1",
        cwd="D:/repo",
        updated_at="2026-06-05T10:00:00+08:00",
    )


def _named_workspace(name: str, path: str, updated_at: str) -> NamedWorkspace:
    return NamedWorkspace(
        name=name,
        workspace=Workspace(path=path),
        updated_at=updated_at,
    )


def _pending():
    from c_auto_bridge.session.models import PendingRef

    return PendingRef(
        pending_id="p_1",
        bot_session_id="s_1",
        feishu_user_id="owner_1",
        chat_id="chat_1",
        kind="approval",
        codex_thread_id="thr_1",
        codex_turn_id="turn_1",
        codex_request_id="req_1",
        prompt_text="Approve?",
        payload={},
        status="open",
        created_at="2026-06-05T10:00:00+08:00",
        updated_at="2026-06-05T10:00:00+08:00",
    )


if __name__ == "__main__":
    unittest.main()

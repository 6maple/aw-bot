from tempfile import TemporaryDirectory
import unittest
import json
from unittest.mock import patch
from pathlib import Path

from c_auto_bridge.session.models import PendingRef, SessionRef
from c_auto_bridge.store.file_store import FileStore
from c_auto_bridge.utils.atomic_file import write_json_atomic


class FileStoreTest(unittest.TestCase):
    def test_save_list_and_get_current_session(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            older = _session("s_old", "owner_1", "2026-06-02T09:00:00+08:00")
            newer = _session("s_new", "owner_1", "2026-06-02T10:00:00+08:00")
            other = _session("s_other", "owner_2", "2026-06-02T11:00:00+08:00")

            store.save_session(older)
            store.save_session(newer)
            store.save_session(other)
            store.set_current_session("owner_1", "s_new")

            listed = store.list_sessions("owner_1", 10)
            current = store.get_current_session("owner_1")

            self.assertEqual([item.bot_session_id for item in listed], ["s_new", "s_old"])
            self.assertIsNotNone(current)
            self.assertEqual(current.bot_session_id, "s_new")

    def test_get_session_reads_legacy_codex_session_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            session_dir = Path(tmpdir) / "sessions"
            session_dir.mkdir()
            (session_dir / "s_legacy.json").write_text(
                json.dumps(
                    {
                        "bot_session_id": "s_legacy",
                        "owner_feishu_user_id": "owner_1",
                        "owner_chat_id": "chat_1",
                        "agent": "codex",
                        "codex_session_id": "thr_legacy",
                        "codex_thread_id": "thr_legacy",
                        "parent_bot_session_id": None,
                        "role": None,
                        "title": "test",
                        "cwd": "D:/Workspace/ai-projects/aw-bot",
                        "access_mode": "workspace",
                        "status": "idle",
                        "created_at": "2026-06-02T09:00:00+08:00",
                        "updated_at": "2026-06-02T09:00:00+08:00",
                    }
                ),
                encoding="utf-8",
            )

            session = FileStore(tmpdir).get_session("s_legacy")

            self.assertIsNotNone(session)
            self.assertEqual(session.codex_thread_id, "thr_legacy")

    def test_get_open_pending_by_user_and_resolve(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = FileStore(tmpdir)
            pending = PendingRef(
                pending_id="p_1",
                bot_session_id="s_1",
                feishu_user_id="owner_1",
                chat_id="chat_1",
                kind="approval",
                codex_thread_id="thr_1",
                codex_turn_id=None,
                codex_request_id="req_1",
                prompt_text="Approve?",
                payload={},
                status="open",
                created_at="2026-06-02T10:00:00+08:00",
                updated_at="2026-06-02T10:00:00+08:00",
            )

            store.save_pending(pending)
            open_pending = store.get_open_pending_by_user("owner_1")
            store.close_pending("p_1", "resolved")
            resolved = store.get_open_pending_by_user("owner_1")

            self.assertIsNotNone(open_pending)
            self.assertEqual(open_pending.pending_id, "p_1")
            self.assertIsNone(resolved)

    def test_atomic_write_retries_transient_permission_error(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            original_replace = __import__("os").replace
            calls = 0

            def replace_once_denied(src, dst):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError("locked")
                original_replace(src, dst)

            with patch("c_auto_bridge.utils.atomic_file.os.replace", replace_once_denied):
                write_json_atomic(path, {"ok": True})

            self.assertEqual(calls, 2)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"ok": True})


def _session(
    bot_session_id: str,
    owner_feishu_user_id: str,
    updated_at: str,
) -> SessionRef:
    return SessionRef(
        bot_session_id=bot_session_id,
        owner_feishu_user_id=owner_feishu_user_id,
        owner_chat_id="chat_1",
        agent="codex",
        codex_thread_id="thr_1",
        title="test",
        cwd="D:/Workspace/ai-projects/aw-bot",
        access_mode="workspace",
        status="idle",
        created_at="2026-06-02T09:00:00+08:00",
        updated_at=updated_at,
    )


if __name__ == "__main__":
    unittest.main()

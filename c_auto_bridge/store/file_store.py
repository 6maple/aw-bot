import json
from datetime import datetime
from pathlib import Path
from threading import RLock

from c_auto_bridge.core.agent_session import Workspace
from c_auto_bridge.core.workspace import NamedWorkspace
from c_auto_bridge.react.events import AgentEvent, event_to_dict
from c_auto_bridge.session.models import PendingRef, PendingStatus, SessionRef
from c_auto_bridge.store.base import Store
from c_auto_bridge.store.models import RunRef, StreamCardRef, WorkspaceBinding
from c_auto_bridge.utils.atomic_file import read_json, write_json_atomic


class FileStore(Store):
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.sessions_dir = self.data_dir / "sessions"
        self.bindings_dir = self.data_dir / "bindings"
        self.pending_dir = self.data_dir / "pending"
        self.runs_dir = self.data_dir / "runs"
        self.cards_dir = self.data_dir / "cards"
        self.workspaces_dir = self.data_dir / "workspaces"
        self.named_workspaces_dir = self.data_dir / "named_workspaces"
        self.logs_dir = self.data_dir / "logs"
        self._lock = RLock()

    def initialize(self) -> None:
        with self._lock:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            self.bindings_dir.mkdir(parents=True, exist_ok=True)
            self.pending_dir.mkdir(parents=True, exist_ok=True)
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            self.cards_dir.mkdir(parents=True, exist_ok=True)
            self.workspaces_dir.mkdir(parents=True, exist_ok=True)
            self.named_workspaces_dir.mkdir(parents=True, exist_ok=True)
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            if not self.index_path.exists():
                write_json_atomic(self.index_path, {"sessions": []})
            if not self.run_index_path.exists():
                write_json_atomic(self.run_index_path, {"runs": []})

    @property
    def index_path(self) -> Path:
        return self.sessions_dir / "index.json"

    @property
    def run_index_path(self) -> Path:
        return self.runs_dir / "index.json"

    def save_session(self, session: SessionRef) -> None:
        with self._lock:
            self.initialize()
            write_json_atomic(self._session_path(session.bot_session_id), session.to_dict())
            index = self._read_index()
            summary = self._session_summary(session)
            sessions = [
                item
                for item in index["sessions"]
                if item["bot_session_id"] != session.bot_session_id
            ]
            sessions.append(summary)
            sessions.sort(key=lambda item: item["updated_at"], reverse=True)
            write_json_atomic(self.index_path, {"sessions": sessions})

    def get_session(self, bot_session_id: str) -> SessionRef | None:
        with self._lock:
            path = self._session_path(bot_session_id)
            if not path.exists():
                return None
            return SessionRef.from_dict(read_json(path))

    def list_sessions(self, owner_feishu_user_id: str, limit: int) -> list[SessionRef]:
        with self._lock:
            self.initialize()
            summaries = [
                item
                for item in self._read_index()["sessions"]
                if item["owner_feishu_user_id"] == owner_feishu_user_id
            ]
            summaries.sort(key=lambda item: item["updated_at"], reverse=True)
            sessions: list[SessionRef] = []
            for item in summaries[:limit]:
                session = self.get_session(item["bot_session_id"])
                if session is not None:
                    sessions.append(session)
            return sessions

    def set_current_session(self, feishu_user_id: str, bot_session_id: str) -> None:
        with self._lock:
            self.initialize()
            write_json_atomic(
                self._binding_path(feishu_user_id),
                {
                    "feishu_user_id": feishu_user_id,
                    "current_bot_session_id": bot_session_id,
                },
            )

    def get_current_session(self, feishu_user_id: str) -> SessionRef | None:
        with self._lock:
            path = self._binding_path(feishu_user_id)
            if not path.exists():
                return None
            binding = read_json(path)
            return self.get_session(binding["current_bot_session_id"])

    def save_pending(self, pending: PendingRef) -> None:
        with self._lock:
            self.initialize()
            write_json_atomic(self._pending_path(pending.pending_id), pending.to_dict())

    def get_open_pending_by_user(self, feishu_user_id: str) -> PendingRef | None:
        with self._lock:
            self.initialize()
            pending_items = []
            for path in self.pending_dir.glob("*.json"):
                pending = PendingRef.from_dict(read_json(path))
                if pending.feishu_user_id == feishu_user_id and pending.status == "open":
                    pending_items.append(pending)
            pending_items.sort(key=lambda item: item.created_at)
            if not pending_items:
                return None
            return pending_items[0]

    def close_pending(self, pending_id: str, status: PendingStatus) -> None:
        if status == "open":
            raise ValueError("closed pending status cannot be open")
        with self._lock:
            pending = PendingRef.from_dict(read_json(self._pending_path(pending_id)))
            now = datetime.now().astimezone().isoformat()
            pending.status = status
            pending.updated_at = now
            self.save_pending(pending)

    def save_run(self, run: RunRef) -> None:
        with self._lock:
            self.initialize()
            write_json_atomic(self._run_path(run.run_id), run.to_dict())
            index = read_json(self.run_index_path)
            runs = [item for item in index["runs"] if item["run_id"] != run.run_id]
            runs.append(run.to_dict())
            runs.sort(key=lambda item: item["updated_at"], reverse=True)
            write_json_atomic(self.run_index_path, {"runs": runs})

    def get_run(self, run_id: str) -> RunRef | None:
        with self._lock:
            path = self._run_path(run_id)
            if not path.exists():
                return None
            return RunRef.from_dict(read_json(path))

    def list_runs(self, scope_id: str, limit: int) -> list[RunRef]:
        with self._lock:
            self.initialize()
            runs = [
                RunRef.from_dict(item)
                for item in read_json(self.run_index_path)["runs"]
                if item["scope_id"] == scope_id
            ]
            runs.sort(key=lambda item: item.updated_at, reverse=True)
            return runs[:limit]

    def list_private_chat_scope_ids(self, limit: int) -> list[str]:
        with self._lock:
            self.initialize()
            scope_ids: dict[str, str] = {}
            for item in read_json(self.run_index_path)["runs"]:
                scope_id = item.get("scope_id")
                updated_at = item.get("updated_at", "")
                if not isinstance(scope_id, str) or not scope_id:
                    continue
                if scope_id not in scope_ids or updated_at > scope_ids[scope_id]:
                    scope_ids[scope_id] = updated_at
            for item in self._read_index()["sessions"]:
                session = self.get_session(item["bot_session_id"])
                if session is None:
                    continue
                if session.owner_chat_id not in scope_ids or session.updated_at > scope_ids[session.owner_chat_id]:
                    scope_ids[session.owner_chat_id] = session.updated_at
            return [
                scope_id
                for scope_id, _ in sorted(scope_ids.items(), key=lambda item: item[1], reverse=True)[:limit]
            ]

    def save_card(self, card: StreamCardRef) -> None:
        with self._lock:
            self.initialize()
            write_json_atomic(self._card_path(card.card_id), card.to_dict())

    def get_card(self, card_id: str) -> StreamCardRef | None:
        with self._lock:
            path = self._card_path(card_id)
            if not path.exists():
                return None
            return StreamCardRef.from_dict(read_json(path))

    def save_workspace(self, workspace: WorkspaceBinding) -> None:
        with self._lock:
            self.initialize()
            write_json_atomic(self._workspace_path(workspace.scope_id), workspace.to_dict())

    def get_workspace(self, scope_id: str) -> WorkspaceBinding | None:
        with self._lock:
            path = self._workspace_path(scope_id)
            if not path.exists():
                return None
            return WorkspaceBinding.from_dict(read_json(path))

    def save_named_workspace(self, workspace: NamedWorkspace) -> None:
        with self._lock:
            self.initialize()
            write_json_atomic(self._named_workspace_path(workspace.name), self._named_workspace_dict(workspace))

    def get_named_workspace(self, name: str) -> NamedWorkspace | None:
        with self._lock:
            path = self._named_workspace_path(name)
            if not path.exists():
                return None
            return self._named_workspace_from_dict(read_json(path))

    def list_named_workspaces(self) -> list[NamedWorkspace]:
        with self._lock:
            self.initialize()
            workspaces = [
                self._named_workspace_from_dict(read_json(path))
                for path in self.named_workspaces_dir.glob("*.json")
            ]
            workspaces.sort(key=lambda item: item.updated_at, reverse=True)
            return workspaces

    def remove_named_workspace(self, name: str) -> None:
        with self._lock:
            path = self._named_workspace_path(name)
            if path.exists():
                path.unlink()

    def append_run_event(self, run_id: str, event: AgentEvent) -> None:
        self._append_log(run_id, {"event": event_to_dict(event)})

    def append_run_error(self, run_id: str, error: str) -> None:
        self._append_log(run_id, {"error": error})

    def recover_incomplete(self, updated_at: str) -> None:
        with self._lock:
            self.initialize()
            for item in read_json(self.run_index_path)["runs"]:
                run = RunRef.from_dict(item)
                if run.status not in {"running", "pending"}:
                    continue
                run.status = "interrupted"
                run.updated_at = updated_at
                self.save_run(run)
            for path in self.pending_dir.glob("*.json"):
                pending = PendingRef.from_dict(read_json(path))
                if pending.status != "open":
                    continue
                pending.status = "cancelled"
                pending.updated_at = updated_at
                self.save_pending(pending)
            for path in self.cards_dir.glob("*.json"):
                card = StreamCardRef.from_dict(read_json(path))
                if card.status != "streaming":
                    continue
                card.status = "failed"
                card.updated_at = updated_at
                self.save_card(card)

    def _append_log(self, run_id: str, payload: dict) -> None:
        with self._lock:
            self.initialize()
            with self._log_path(run_id).open("a", encoding="utf-8") as log:
                log.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _read_index(self) -> dict:
        with self._lock:
            self.initialize()
            return read_json(self.index_path)

    def _session_path(self, bot_session_id: str) -> Path:
        return self.sessions_dir / f"{bot_session_id}.json"

    def _binding_path(self, feishu_user_id: str) -> Path:
        return self.bindings_dir / f"{feishu_user_id}.json"

    def _pending_path(self, pending_id: str) -> Path:
        return self.pending_dir / f"{pending_id}.json"

    def _run_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def _card_path(self, card_id: str) -> Path:
        return self.cards_dir / f"{card_id}.json"

    def _workspace_path(self, scope_id: str) -> Path:
        return self.workspaces_dir / f"{scope_id}.json"

    def _named_workspace_path(self, name: str) -> Path:
        return self.named_workspaces_dir / f"{name}.json"

    def _log_path(self, run_id: str) -> Path:
        return self.logs_dir / f"{run_id}.jsonl"

    def _session_summary(self, session: SessionRef) -> dict[str, str | None]:
        return {
            "bot_session_id": session.bot_session_id,
            "owner_feishu_user_id": session.owner_feishu_user_id,
            "title": session.title,
            "agent": session.agent,
            "codex_thread_id": session.codex_thread_id,
            "status": session.status,
            "updated_at": session.updated_at,
        }

    def _named_workspace_dict(self, workspace: NamedWorkspace) -> dict[str, str | dict[str, str]]:
        return {
            "name": workspace.name,
            "workspace": {"path": workspace.workspace.path},
            "updated_at": workspace.updated_at,
        }

    def _named_workspace_from_dict(self, payload: dict) -> NamedWorkspace:
        return NamedWorkspace(
            name=payload["name"],
            workspace=Workspace(path=payload["workspace"]["path"]),
            updated_at=payload["updated_at"],
        )

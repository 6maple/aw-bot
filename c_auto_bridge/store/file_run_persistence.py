import json
from datetime import datetime
from pathlib import Path

from c_auto_bridge.core.agent_events import (
    AgentEvent,
    ApprovalRequested,
    RunCompleted,
    RunFailed,
    RunInterrupted,
    RunTimedOut,
    TextDelta,
    ThinkingDelta,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
    UserInputRequested,
)
from c_auto_bridge.core.agent_session import HistoricalAgentSession, Workspace
from c_auto_bridge.core.pending_request import PendingRequest, PendingRequestStatus
from c_auto_bridge.core.run import Run, RunStatus
from c_auto_bridge.core.workspace import NamedWorkspace
from c_auto_bridge.react.events import (
    ApprovalRequested as ReactApprovalRequested,
    RunCompleted as ReactRunCompleted,
    RunFailed as ReactRunFailed,
    RunInterrupted as ReactRunInterrupted,
    RunTimedOut as ReactRunTimedOut,
    TextDelta as ReactTextDelta,
    ThinkingDelta as ReactThinkingDelta,
    ToolFinished as ReactToolFinished,
    ToolStarted as ReactToolStarted,
    UsageUpdated as ReactUsageUpdated,
    UserInputRequested as ReactUserInputRequested,
)
from c_auto_bridge.session.models import PendingRef, SessionRef
from c_auto_bridge.store.file_store import FileStore
from c_auto_bridge.store.models import RunRef
from c_auto_bridge.utils.atomic_file import read_json, write_json_atomic


class FileRunPersistence:
    def __init__(self, store: FileStore) -> None:
        self._store = store
        self._agent_sessions_dir = self._store.data_dir / "core_agent_sessions"
        self._runs_dir = self._store.data_dir / "core_runs"
        self._pending_requests_dir = self._store.data_dir / "core_pending_requests"
        self._named_workspaces_dir = self._store.data_dir / "core_named_workspaces"
        self._run_logs_dir = self._store.data_dir / "core_logs" / "runs"
        self._startup_log_path = self._store.data_dir / "core_logs" / "startup.jsonl"

    async def record_run_created(self, run: Run) -> None:
        self._store.save_run(
            RunRef(
                run_id=run.run_id,
                scope_id=run.private_chat_scope_id,
                bot_session_id=run.agent_session_id,
                agent=run.agent_name,
                thread_id=run.agent_session_id,
                turn_id=run.agent_turn_id,
                status=_run_status(run.status),
                created_at=run.created_at,
                updated_at=run.updated_at,
            )
        )
        self._write_json(self._run_path(run.run_id), _run_record(run))

    async def record_run_event(self, *, run_id: str, event: AgentEvent) -> None:
        self._store.append_run_event(run_id, _react_event(event))
        self._append_jsonl(
            self._run_log_path(run_id),
            {
                "kind": "run_event",
                "run_id": run_id,
                "event": _event_record(event),
            },
        )

    async def record_run_terminal_status(
        self,
        *,
        run_id: str,
        status: RunStatus,
        updated_at: str,
    ) -> None:
        run = self._require_run(run_id)
        run.status = _run_status(status)
        run.updated_at = updated_at
        self._store.save_run(run)
        run_record = self._require_core_run(run_id)
        run_record["status"] = status
        run_record["updated_at"] = updated_at
        self._write_json(self._run_path(run_id), run_record)

    async def open_pending_request(
        self,
        *,
        run_id: str,
        pending_request: PendingRequest,
    ) -> None:
        run = self._require_run(run_id)
        session = self._require_session(run.bot_session_id)
        self._store.save_pending(
            PendingRef(
                pending_id=pending_request.pending_request_id,
                bot_session_id=run.bot_session_id,
                feishu_user_id=session.owner_feishu_user_id,
                chat_id=run.scope_id,
                kind=pending_request.kind,
                codex_thread_id=run.thread_id,
                codex_turn_id=run.turn_id,
                codex_request_id=pending_request.pending_request_id,
                prompt_text="",
                payload=pending_request.payload,
                status="open",
                created_at=run.updated_at,
                updated_at=run.updated_at,
            )
        )
        self._write_json(
            self._pending_request_path(pending_request.pending_request_id),
            {
                "pending_request_id": pending_request.pending_request_id,
                "run_id": pending_request.run_id,
                "kind": pending_request.kind,
                "payload": pending_request.payload,
                "status": "open",
                "created_at": run.updated_at,
                "updated_at": run.updated_at,
            },
        )

    async def close_pending_request(
        self,
        *,
        pending_request_id: str,
        status: PendingRequestStatus,
    ) -> None:
        self._store.close_pending(pending_request_id, status)
        pending_request = self._require_core_pending_request(pending_request_id)
        pending_request["status"] = status
        pending_request["updated_at"] = datetime.now().astimezone().isoformat()
        self._write_json(self._pending_request_path(pending_request_id), pending_request)

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        self._store.initialize()
        for path in self._store.bindings_dir.glob("*.json"):
            binding = read_json(path)
            session = self._store.get_session(binding["current_bot_session_id"])
            if session is None or session.owner_chat_id != private_chat_scope_id:
                continue
            path.unlink()

    async def save_named_workspace(self, *, workspace: NamedWorkspace) -> None:
        self._store.save_named_workspace(workspace)
        self._write_json(
            self._named_workspace_path(workspace.name),
            {
                "name": workspace.name,
                "workspace": {"path": workspace.workspace.path},
                "updated_at": workspace.updated_at,
            },
        )

    async def get_named_workspace(self, *, name: str) -> NamedWorkspace | None:
        path = self._named_workspace_path(name)
        if not path.exists():
            return None
        payload = read_json(path)
        return NamedWorkspace(
            name=payload["name"],
            workspace=Workspace(path=payload["workspace"]["path"]),
            updated_at=payload["updated_at"],
        )

    async def list_named_workspaces(self) -> list[NamedWorkspace]:
        self._ensure_dirs()
        workspaces = [
            NamedWorkspace(
                name=payload["name"],
                workspace=Workspace(path=payload["workspace"]["path"]),
                updated_at=payload["updated_at"],
            )
            for payload in (read_json(path) for path in self._named_workspaces_dir.glob("*.json"))
        ]
        workspaces.sort(key=lambda item: item.updated_at, reverse=True)
        return workspaces

    async def remove_named_workspace(self, *, name: str) -> None:
        self._store.remove_named_workspace(name)
        path = self._named_workspace_path(name)
        if path.exists():
            path.unlink()

    async def save_agent_session(
        self,
        *,
        agent_session: HistoricalAgentSession,
    ) -> None:
        self._store.save_session(
            SessionRef(
                bot_session_id=agent_session.agent_session_id,
                owner_feishu_user_id=agent_session.user_id,
                owner_chat_id=agent_session.private_chat_scope_id,
                agent=agent_session.agent_name,
                codex_thread_id=agent_session.agent_session_id,
                title=agent_session.agent_session_id,
                cwd=agent_session.workspace.path,
                access_mode=agent_session.access_mode,
                status="idle",
                created_at=agent_session.updated_at,
                updated_at=agent_session.updated_at,
            )
        )
        self._write_json(self._agent_session_path(agent_session.agent_session_id), _agent_session_record(agent_session))

    async def list_agent_sessions(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
    ) -> list[HistoricalAgentSession]:
        self._ensure_dirs()
        historical_sessions = []
        for path in self._agent_sessions_dir.glob("*.json"):
            payload = read_json(path)
            if payload["private_chat_scope_id"] != private_chat_scope_id or payload["user_id"] != user_id:
                continue
            historical_sessions.append(
                HistoricalAgentSession(
                    agent_session_id=payload["agent_session_id"],
                    private_chat_scope_id=payload["private_chat_scope_id"],
                    user_id=payload["user_id"],
                    agent_name=payload["agent_name"],
                    workspace=Workspace(path=payload["workspace"]["path"]),
                    access_mode=payload["access_mode"],
                    updated_at=payload["updated_at"],
                )
            )
        historical_sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return historical_sessions

    async def record_run_error(self, *, run_id: str, error: str) -> None:
        self._store.append_run_error(run_id, error)
        self._append_jsonl(
            self._run_log_path(run_id),
            {
                "kind": "run_error",
                "run_id": run_id,
                "error": error,
            },
        )

    async def record_startup_diagnostic(
        self,
        *,
        level: str,
        message: str,
        details: dict[str, object],
    ) -> None:
        self._append_jsonl(
            self._startup_log_path,
            {
                "kind": "startup_diagnostic",
                "level": level,
                "message": message,
                "details": details,
            },
        )

    async def recover_incomplete(self, *, updated_at: str) -> None:
        self._store.recover_incomplete(updated_at)
        self._ensure_dirs()
        for path in self._runs_dir.glob("*.json"):
            payload = read_json(path)
            if payload["status"] not in {"running", "pending_user_input", "pending_approval"}:
                continue
            payload["status"] = "interrupted"
            payload["updated_at"] = updated_at
            self._write_json(path, payload)
        for path in self._pending_requests_dir.glob("*.json"):
            payload = read_json(path)
            if payload["status"] != "open":
                continue
            payload["status"] = "cancelled"
            payload["updated_at"] = updated_at
            self._write_json(path, payload)

    def _require_run(self, run_id: str) -> RunRef:
        run = self._store.get_run(run_id)
        if run is None:
            raise RuntimeError(f"run not found: {run_id}")
        return run

    def _require_core_run(self, run_id: str) -> dict:
        path = self._run_path(run_id)
        if not path.exists():
            raise RuntimeError(f"core run not found: {run_id}")
        return read_json(path)

    def _require_core_pending_request(self, pending_request_id: str) -> dict:
        path = self._pending_request_path(pending_request_id)
        if not path.exists():
            raise RuntimeError(f"core pending request not found: {pending_request_id}")
        return read_json(path)

    def _require_session(self, bot_session_id: str):
        session = self._store.get_session(bot_session_id)
        if session is None:
            raise RuntimeError(f"session not found: {bot_session_id}")
        return session

    def _ensure_dirs(self) -> None:
        self._store.initialize()
        self._agent_sessions_dir.mkdir(parents=True, exist_ok=True)
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._pending_requests_dir.mkdir(parents=True, exist_ok=True)
        self._named_workspaces_dir.mkdir(parents=True, exist_ok=True)
        self._run_logs_dir.mkdir(parents=True, exist_ok=True)
        self._startup_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        self._ensure_dirs()
        write_json_atomic(path, payload)

    def _append_jsonl(self, path: Path, payload: dict[str, object]) -> None:
        self._ensure_dirs()
        with path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _agent_session_path(self, agent_session_id: str) -> Path:
        return self._agent_sessions_dir / f"{agent_session_id}.json"

    def _run_path(self, run_id: str) -> Path:
        return self._runs_dir / f"{run_id}.json"

    def _pending_request_path(self, pending_request_id: str) -> Path:
        return self._pending_requests_dir / f"{pending_request_id}.json"

    def _named_workspace_path(self, name: str) -> Path:
        return self._named_workspaces_dir / f"{name}.json"

    def _run_log_path(self, run_id: str) -> Path:
        return self._run_logs_dir / f"{run_id}.jsonl"


def _run_status(status: RunStatus) -> str:
    if status in {"pending_user_input", "pending_approval"}:
        return "pending"
    return status


def _react_event(event: AgentEvent):
    if isinstance(event, TextDelta):
        return ReactTextDelta(event.text)
    if isinstance(event, ThinkingDelta):
        return ReactThinkingDelta(event.text)
    if isinstance(event, ToolStarted):
        return ReactToolStarted(event.tool_id, event.name, event.input)
    if isinstance(event, ToolFinished):
        return ReactToolFinished(event.tool_id, event.output, event.is_error)
    if isinstance(event, UserInputRequested):
        return ReactUserInputRequested(event.pending_request_id, event.prompt, event.payload)
    if isinstance(event, ApprovalRequested):
        return ReactApprovalRequested(event.pending_request_id, event.prompt, event.payload)
    if isinstance(event, UsageUpdated):
        return ReactUsageUpdated(event.input_tokens, event.output_tokens)
    if isinstance(event, RunCompleted):
        return ReactRunCompleted()
    if isinstance(event, RunFailed):
        return ReactRunFailed(event.error)
    if isinstance(event, RunInterrupted):
        return ReactRunInterrupted()
    if isinstance(event, RunTimedOut):
        return ReactRunTimedOut()
    raise TypeError(f"unsupported event: {type(event).__name__}")


def _agent_session_record(agent_session: HistoricalAgentSession) -> dict[str, object]:
    return {
        "agent_session_id": agent_session.agent_session_id,
        "private_chat_scope_id": agent_session.private_chat_scope_id,
        "user_id": agent_session.user_id,
        "agent_name": agent_session.agent_name,
        "workspace": {"path": agent_session.workspace.path},
        "access_mode": agent_session.access_mode,
        "updated_at": agent_session.updated_at,
    }


def _run_record(run: Run) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "private_chat_scope_id": run.private_chat_scope_id,
        "user_id": run.user_id,
        "agent_session_id": run.agent_session_id,
        "agent_name": run.agent_name,
        "agent_turn_id": run.agent_turn_id,
        "status": run.status,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _event_record(event: AgentEvent) -> dict[str, object]:
    if isinstance(event, TextDelta):
        return {"kind": event.kind, "text": event.text}
    if isinstance(event, ThinkingDelta):
        return {"kind": event.kind, "text": event.text}
    if isinstance(event, ToolStarted):
        return {"kind": event.kind, "tool_id": event.tool_id, "name": event.name, "input": event.input}
    if isinstance(event, ToolFinished):
        return {"kind": event.kind, "tool_id": event.tool_id, "output": event.output, "is_error": event.is_error}
    if isinstance(event, UserInputRequested):
        return {
            "kind": event.kind,
            "pending_request_id": event.pending_request_id,
            "prompt": event.prompt,
            "payload": event.payload,
        }
    if isinstance(event, ApprovalRequested):
        return {
            "kind": event.kind,
            "pending_request_id": event.pending_request_id,
            "prompt": event.prompt,
            "payload": event.payload,
        }
    if isinstance(event, UsageUpdated):
        return {"kind": event.kind, "input_tokens": event.input_tokens, "output_tokens": event.output_tokens}
    if isinstance(event, RunCompleted):
        return {"kind": event.kind}
    if isinstance(event, RunFailed):
        return {"kind": event.kind, "error": event.error}
    if isinstance(event, RunInterrupted):
        return {"kind": event.kind}
    if isinstance(event, RunTimedOut):
        return {"kind": event.kind}
    raise TypeError(f"unsupported event: {type(event).__name__}")

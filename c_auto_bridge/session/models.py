from dataclasses import asdict, dataclass
from typing import Any, Literal


AgentName = Literal["codex", "opencode"]
AccessMode = Literal["full", "workspace", "read-only"]
SessionStatus = Literal[
    "idle",
    "running",
    "pending_user_input",
    "pending_approval",
    "error",
]
PendingKind = Literal["user_input", "approval"]
PendingStatus = Literal["open", "resolved", "cancelled"]


@dataclass
class SessionRef:
    bot_session_id: str
    owner_feishu_user_id: str
    owner_chat_id: str
    agent: AgentName
    codex_thread_id: str | None
    title: str
    cwd: str
    access_mode: AccessMode | None
    status: SessionStatus
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionRef":
        payload = dict(payload)
        if any(key in payload for key in ("codex_session_id", "parent_bot_session_id", "role")):
            codex_session_id = payload.pop("codex_session_id", None)
            payload.pop("parent_bot_session_id", None)
            payload.pop("role", None)
            if "codex_thread_id" not in payload:
                payload["codex_thread_id"] = codex_session_id
        if "access_mode" not in payload:
            payload["access_mode"] = None
        return cls(**payload)


@dataclass
class PendingRef:
    pending_id: str
    bot_session_id: str
    feishu_user_id: str
    chat_id: str
    kind: PendingKind
    codex_thread_id: str
    codex_turn_id: str | None
    codex_request_id: str | None
    prompt_text: str
    payload: dict[str, Any]
    status: PendingStatus
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PendingRef":
        return cls(**payload)

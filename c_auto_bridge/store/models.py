from dataclasses import asdict, dataclass
from typing import Any, Literal


RunStatus = Literal[
    "running",
    "pending",
    "completed",
    "failed",
    "interrupted",
    "cancelled",
    "timed_out",
]
CardStatus = Literal["streaming", "completed", "failed"]


@dataclass
class RunRef:
    run_id: str
    scope_id: str
    bot_session_id: str
    agent: str
    thread_id: str
    turn_id: str
    status: RunStatus
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunRef":
        return cls(**payload)


@dataclass
class StreamCardRef:
    card_id: str
    run_id: str
    chat_id: str
    message_id: str
    status: CardStatus
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StreamCardRef":
        return cls(**payload)


@dataclass
class WorkspaceBinding:
    scope_id: str
    cwd: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkspaceBinding":
        return cls(**payload)

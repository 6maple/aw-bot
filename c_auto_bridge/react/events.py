from dataclasses import asdict, dataclass
from typing import Any, ClassVar, TypeAlias


@dataclass(frozen=True)
class TextDelta:
    text: str
    kind: ClassVar[str] = "text_delta"


@dataclass(frozen=True)
class ThinkingDelta:
    text: str
    kind: ClassVar[str] = "thinking_delta"


@dataclass(frozen=True)
class ToolStarted:
    tool_id: str
    name: str
    input: dict[str, Any]
    kind: ClassVar[str] = "tool_started"


@dataclass(frozen=True)
class ToolFinished:
    tool_id: str
    output: str
    is_error: bool
    kind: ClassVar[str] = "tool_finished"


@dataclass(frozen=True)
class UserInputRequested:
    pending_id: str
    prompt: str
    payload: dict[str, Any]
    kind: ClassVar[str] = "user_input_requested"


@dataclass(frozen=True)
class ApprovalRequested:
    pending_id: str
    prompt: str
    payload: dict[str, Any]
    kind: ClassVar[str] = "approval_requested"


@dataclass(frozen=True)
class UsageUpdated:
    input_tokens: int
    output_tokens: int
    kind: ClassVar[str] = "usage_updated"


@dataclass(frozen=True)
class RunCompleted:
    kind: ClassVar[str] = "run_completed"


@dataclass(frozen=True)
class RunFailed:
    error: str
    kind: ClassVar[str] = "run_failed"


@dataclass(frozen=True)
class RunInterrupted:
    kind: ClassVar[str] = "run_interrupted"


@dataclass(frozen=True)
class RunTimedOut:
    kind: ClassVar[str] = "run_timed_out"


AgentEvent: TypeAlias = (
    TextDelta
    | ThinkingDelta
    | ToolStarted
    | ToolFinished
    | UserInputRequested
    | ApprovalRequested
    | UsageUpdated
    | RunCompleted
    | RunFailed
    | RunInterrupted
    | RunTimedOut
)


def event_to_dict(event: AgentEvent) -> dict[str, Any]:
    return {"kind": event.kind, **asdict(event)}

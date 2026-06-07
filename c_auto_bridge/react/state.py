from dataclasses import dataclass
from typing import Any, Literal


RunStatus = Literal[
    "running",
    "pending_user_input",
    "pending_approval",
    "completed",
    "failed",
    "interrupted",
    "timed_out",
]
ToolStatus = Literal["running", "completed", "failed"]
PendingKind = Literal["user_input", "approval"]


@dataclass(frozen=True)
class ToolState:
    tool_id: str
    name: str
    input: dict[str, Any]
    output: str | None
    status: ToolStatus


@dataclass(frozen=True)
class PendingState:
    pending_id: str
    kind: PendingKind
    prompt: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class UsageState:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class RunState:
    run_id: str
    status: RunStatus
    text: str
    thinking: str
    tools: tuple[ToolState, ...]
    pending: PendingState | None
    usage: UsageState
    error: str | None


def initial_run_state(run_id: str) -> RunState:
    return RunState(
        run_id=run_id,
        status="running",
        text="",
        thinking="",
        tools=(),
        pending=None,
        usage=UsageState(input_tokens=0, output_tokens=0),
        error=None,
    )

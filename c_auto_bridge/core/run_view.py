from dataclasses import dataclass

from c_auto_bridge.core.run import RunStatus


@dataclass(frozen=True)
class ToolCallView:
    tool_id: str
    name: str
    input: dict[str, object]
    output: str | None
    status: str


@dataclass(frozen=True)
class PendingRequestView:
    pending_request_id: str
    kind: str
    prompt: str
    payload: dict[str, object]


@dataclass(frozen=True)
class UsageView:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class RunView:
    run_id: str
    status: RunStatus
    text: str
    thinking: str
    tools: tuple[ToolCallView, ...]
    pending: PendingRequestView | None
    usage: UsageView
    error: str | None


def initial_run_view(run_id: str) -> RunView:
    return RunView(
        run_id=run_id,
        status="running",
        text="",
        thinking="",
        tools=(),
        pending=None,
        usage=UsageView(input_tokens=0, output_tokens=0),
        error=None,
    )

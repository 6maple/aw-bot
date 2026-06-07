from dataclasses import replace

from c_auto_bridge.react.events import (
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
from c_auto_bridge.react.state import PendingState, RunState, ToolState, UsageState


def reduce_run_state(state: RunState, event: AgentEvent) -> RunState:
    if isinstance(event, TextDelta):
        return replace(state, text=state.text + event.text)
    if isinstance(event, ThinkingDelta):
        return replace(state, thinking=state.thinking + event.text)
    if isinstance(event, ToolStarted):
        tool = ToolState(
            tool_id=event.tool_id,
            name=event.name,
            input=event.input,
            output=None,
            status="running",
        )
        return replace(state, tools=state.tools + (tool,))
    if isinstance(event, ToolFinished):
        tools = tuple(
            replace(
                tool,
                output=event.output,
                status="failed" if event.is_error else "completed",
            )
            if tool.tool_id == event.tool_id
            else tool
            for tool in state.tools
        )
        return replace(state, tools=tools)
    if isinstance(event, UserInputRequested):
        return replace(
            state,
            status="pending_user_input",
            pending=PendingState(event.pending_id, "user_input", event.prompt, event.payload),
        )
    if isinstance(event, ApprovalRequested):
        return replace(
            state,
            status="pending_approval",
            pending=PendingState(event.pending_id, "approval", event.prompt, event.payload),
        )
    if isinstance(event, UsageUpdated):
        return replace(
            state,
            usage=UsageState(event.input_tokens, event.output_tokens),
        )
    if isinstance(event, RunCompleted):
        return replace(state, status="completed", pending=None)
    if isinstance(event, RunFailed):
        return replace(state, status="failed", pending=None, error=event.error)
    if isinstance(event, RunInterrupted):
        return replace(state, status="interrupted", pending=None)
    if isinstance(event, RunTimedOut):
        return replace(state, status="timed_out", pending=None)
    raise TypeError(f"unsupported agent event: {type(event).__name__}")

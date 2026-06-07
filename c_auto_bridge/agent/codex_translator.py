import json
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class TranslatedCodexEvent:
    turn_id: str
    thread_id: str
    event: AgentEvent
    request_id: int | str | None = None


def translate_codex_event(raw: dict[str, Any]) -> TranslatedCodexEvent | None:
    method = _required_str(raw, "method")
    if method not in {
        "item/agentMessage/delta",
        "item/reasoning/textDelta",
        "item/reasoning/summaryTextDelta",
        "item/started",
        "item/completed",
        "item/tool/requestUserInput",
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "thread/tokenUsage/updated",
        "turn/completed",
        "error",
    }:
        return None
    params = _required_dict(raw, "params")
    turn_id = _required_str(params, "turnId")
    thread_id = _required_str(params, "threadId")
    request_id = raw.get("id")

    if method == "item/agentMessage/delta":
        event: AgentEvent = TextDelta(_required_str(params, "delta"))
    elif method in {"item/reasoning/textDelta", "item/reasoning/summaryTextDelta"}:
        event = ThinkingDelta(_required_str(params, "delta"))
    elif method == "item/started":
        event = _tool_started(_required_dict(params, "item"))
        if event is None:
            return None
    elif method == "item/completed":
        event = _tool_finished(_required_dict(params, "item"))
        if event is None:
            return None
    elif method == "item/tool/requestUserInput":
        if request_id is None:
            raise KeyError("id")
        questions = _required_list(params, "questions")
        prompt = "\n".join(_required_str(question, "question") for question in questions)
        event = UserInputRequested(str(request_id), prompt, params)
    elif method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }:
        if request_id is None:
            raise KeyError("id")
        prompt = params.get("reason") or params.get("command") or "Approval required"
        if not isinstance(prompt, str):
            raise TypeError("approval prompt must be a string")
        event = ApprovalRequested(str(request_id), prompt, params)
    elif method == "thread/tokenUsage/updated":
        last = _required_dict(_required_dict(params, "tokenUsage"), "last")
        event = UsageUpdated(
            _required_int(last, "inputTokens"),
            _required_int(last, "outputTokens"),
        )
    elif method == "turn/completed":
        turn = _required_dict(params, "turn")
        status = _required_str(turn, "status")
        if status == "completed":
            event = RunCompleted()
        elif status == "interrupted":
            event = RunInterrupted()
        elif status == "timed_out":
            event = RunTimedOut()
        elif status == "failed":
            error = _required_dict(turn, "error")
            event = RunFailed(_required_str(error, "message"))
        else:
            raise ValueError(f"unsupported completed turn status: {status}")
    elif method == "error":
        if _required_bool(params, "willRetry"):
            return None
        event = RunFailed(_required_str(_required_dict(params, "error"), "message"))
    return TranslatedCodexEvent(turn_id, thread_id, event, request_id)


def _tool_started(item: dict[str, Any]) -> ToolStarted | None:
    item_type = _required_str(item, "type")
    item_id = _required_str(item, "id")
    if item_type == "commandExecution":
        return ToolStarted(item_id, "command", {"command": _required_str(item, "command")})
    if item_type == "fileChange":
        return ToolStarted(item_id, "file_change", {"changes": _required_list(item, "changes")})
    if item_type == "mcpToolCall":
        return ToolStarted(item_id, _required_str(item, "tool"), _as_dict(item["arguments"]))
    if item_type == "dynamicToolCall":
        return ToolStarted(item_id, _required_str(item, "tool"), _as_dict(item["arguments"]))
    return None


def _tool_finished(item: dict[str, Any]) -> ToolFinished | None:
    item_type = _required_str(item, "type")
    item_id = _required_str(item, "id")
    if item_type == "commandExecution":
        status = _required_str(item, "status")
        return ToolFinished(item_id, item.get("aggregatedOutput") or "", status != "completed")
    if item_type == "fileChange":
        status = _required_str(item, "status")
        return ToolFinished(item_id, json.dumps(item["changes"], ensure_ascii=False), status != "completed")
    if item_type in {"mcpToolCall", "dynamicToolCall"}:
        status = _required_str(item, "status")
        return ToolFinished(item_id, json.dumps(item, ensure_ascii=False), status != "completed")
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"value": value}


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _required_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be a dict")
    return value


def _required_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value


def _required_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a bool")
    return value


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an int")
    return value

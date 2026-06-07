from dataclasses import dataclass
from typing import Any

from c_auto_bridge.core.agent_events import (
    AgentEvent,
    ApprovalRequested,
    RunCompleted,
    RunFailed,
    TextDelta,
    ToolFinished,
    ToolStarted,
    ThinkingDelta,
)


@dataclass(frozen=True)
class TranslatedOpenCodeEvent:
    session_id: str
    message_id: str | None
    event: AgentEvent


def translate_opencode_event(raw: dict[str, Any]) -> TranslatedOpenCodeEvent | None:
    event_type = _required_str(raw, "type")
    properties = _required_dict(raw, "properties")
    session_id = _optional_session_id(properties)
    if session_id is None:
        return None
    message_id = _optional_message_id(properties)

    if event_type in {"session.next.text.delta", "session.next.reasoning.delta"}:
        text = _required_str(properties, "delta")
        if text == "":
            return None
        message_id = _required_str(properties, "assistantMessageID")
        if event_type == "session.next.reasoning.delta":
            event: AgentEvent = ThinkingDelta(text)
        else:
            event = TextDelta(text)
    elif event_type in {"message.part.delta", "message.part.updated"}:
        text = properties.get("delta")
        part = properties.get("part")
        if event_type == "message.part.updated" and _is_tool_part(part):
            event = _tool_part_event(part)
            if event is None:
                return None
            return TranslatedOpenCodeEvent(session_id, message_id, event)
        if text is None and event_type == "message.part.delta" and isinstance(part, dict):
            text = part.get("text")
        if not isinstance(text, str) or text == "":
            return None
        event: AgentEvent
        if _is_reasoning_delta(properties, part):
            event = ThinkingDelta(text)
        else:
            event = TextDelta(text)
    elif event_type == "tool.execute.before":
        event = ToolStarted(
            _required_str(properties, "callID"),
            _required_str(properties, "tool"),
            _required_dict(properties, "args"),
        )
    elif event_type == "tool.execute.after":
        event = ToolFinished(
            _required_str(properties, "callID"),
            _required_str(properties, "output"),
            False,
        )
    elif event_type == "permission.asked":
        event = ApprovalRequested(
            _required_str(properties, "id"),
            _required_str(properties, "permission"),
            properties,
        )
    elif event_type == "session.idle":
        event = RunCompleted()
    elif event_type == "session.status":
        status = _required_dict(properties, "status")
        status_type = _required_str(status, "type")
        if status_type != "idle":
            return None
        event = RunCompleted()
    elif event_type == "session.turn.close":
        event = RunCompleted()
    elif event_type == "session.error":
        event = RunFailed(_error_message(_required_dict(properties, "error")))
    else:
        return None
    return TranslatedOpenCodeEvent(session_id, message_id, event)


def _optional_message_id(properties: dict[str, Any]) -> str | None:
    value = properties.get("messageID")
    if value is None:
        part = properties.get("part")
        if isinstance(part, dict):
            value = part.get("messageID")
    if value is None:
        tool = properties.get("tool")
        if isinstance(tool, dict):
            value = tool.get("messageID")
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("messageID must be a string")
    return value


def _optional_session_id(properties: dict[str, Any]) -> str | None:
    value = properties.get("sessionID")
    if value is None:
        part = properties.get("part")
        if isinstance(part, dict):
            value = part.get("sessionID")
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("sessionID must be a string")
    return value


def _is_reasoning_part(part: Any) -> bool:
    if not isinstance(part, dict):
        return False
    part_type = part.get("type")
    return isinstance(part_type, str) and part_type in {"reasoning", "thinking"}


def _is_reasoning_delta(properties: dict[str, Any], part: Any) -> bool:
    if _is_reasoning_part(part):
        return True
    part_type = properties.get("_partType")
    if isinstance(part_type, str) and part_type in {"reasoning", "thinking"}:
        return True
    field = properties.get("field")
    return isinstance(field, str) and field in {"reasoning", "thinking"}


def _is_tool_part(part: Any) -> bool:
    return isinstance(part, dict) and part.get("type") == "tool"


def _tool_part_event(part: dict[str, Any]) -> AgentEvent | None:
    state = _required_dict(part, "state")
    status = _required_str(state, "status")
    if status == "running":
        return ToolStarted(
            _required_str(part, "id"),
            _required_str(part, "tool"),
            _required_dict(state, "input"),
        )
    if status == "completed":
        return ToolFinished(_required_str(part, "id"), _required_str(state, "output"), False)
    if status == "error":
        return ToolFinished(_required_str(part, "id"), _required_str(state, "error"), True)
    return None


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


def _error_message(error: dict[str, Any]) -> str:
    name = _required_str(error, "name")
    data = _required_dict(error, "data")
    message = data.get("message")
    if message is None:
        return name
    if not isinstance(message, str):
        raise TypeError("message must be a string")
    return message

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class IncomingAttachment:
    kind: str
    resource_key: str
    file_name: str | None


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    chat_id: str
    chat_type: str
    user_id: str
    text: str
    attachments: tuple[IncomingAttachment, ...] = ()


@dataclass(frozen=True)
class IncomingMenuEvent:
    user_id: str
    event_key: str


def parse_text_content(content: str) -> str:
    payload = json.loads(content)
    text = payload["text"]
    if not isinstance(text, str):
        raise TypeError("message text must be a string")
    return text


def parse_message_content(message_type: str, content: str) -> tuple[str, tuple[IncomingAttachment, ...]]:
    if message_type == "text":
        return parse_text_content(content), ()
    payload = json.loads(content)
    if message_type == "image":
        return "", (IncomingAttachment(kind="image", resource_key=_required_str(payload, "image_key"), file_name=None),)
    if message_type == "file":
        return "", (
            IncomingAttachment(
                kind="file",
                resource_key=_required_str(payload, "file_key"),
                file_name=_optional_str(payload, "file_name"),
            ),
        )
    if message_type in {"audio", "media", "sticker", "folder"}:
        return "", (
            IncomingAttachment(
                kind=message_type,
                resource_key=_required_str(payload, "file_key"),
                file_name=_optional_str(payload, "file_name"),
            ),
        )
    raise ValueError(f"unsupported message type: {message_type}")


def _required_str(payload: dict, key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _optional_str(payload: dict, key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value

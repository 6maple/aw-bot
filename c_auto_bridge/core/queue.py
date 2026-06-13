from dataclasses import dataclass
from datetime import datetime

from c_auto_bridge.core.attachments import Attachment


@dataclass(frozen=True)
class QueuedMessage:
    user_id: str
    text: str
    queued_at: datetime
    attachments: tuple[Attachment, ...] = ()


def pop_next_merged_prompt(
    queued_messages: list[QueuedMessage],
    *,
    merge_window_seconds: float,
) -> tuple[str, tuple[Attachment, ...], str, list[QueuedMessage]] | None:
    if not queued_messages:
        return None
    merged_items = [queued_messages[0]]
    remaining = queued_messages[1:]
    while remaining:
        candidate = remaining[0]
        previous = merged_items[-1]
        if (candidate.queued_at - previous.queued_at).total_seconds() > merge_window_seconds:
            break
        merged_items.append(candidate)
        remaining = remaining[1:]
    prompt = "\n".join(item.text for item in merged_items if item.text)
    attachments = tuple(attachment for item in merged_items for attachment in item.attachments)
    user_id = merged_items[-1].user_id
    return prompt, attachments, user_id, remaining

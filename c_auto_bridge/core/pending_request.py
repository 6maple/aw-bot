from dataclasses import dataclass
from typing import Literal


PendingRequestKind = Literal["user_input", "approval"]
PendingRequestStatus = Literal["open", "resolved", "cancelled"]


@dataclass(frozen=True)
class PendingRequest:
    pending_request_id: str
    run_id: str
    kind: PendingRequestKind
    payload: dict[str, object]

from dataclasses import dataclass
from typing import Literal


RunStatus = Literal[
    "running",
    "pending_user_input",
    "pending_approval",
    "completed",
    "failed",
    "interrupted",
    "timed_out",
]


@dataclass(frozen=True)
class Run:
    run_id: str
    private_chat_scope_id: str
    user_id: str
    agent_session_id: str
    agent_name: str
    agent_turn_id: str
    status: RunStatus
    created_at: str
    updated_at: str

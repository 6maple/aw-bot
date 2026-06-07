from dataclasses import dataclass
from typing import Literal


AccessMode = Literal["full", "workspace", "read-only"]


@dataclass(frozen=True)
class Workspace:
    path: str


@dataclass(frozen=True)
class AgentSession:
    agent_session_id: str
    private_chat_scope_id: str
    user_id: str
    agent_name: str
    workspace: Workspace
    access_mode: AccessMode


@dataclass(frozen=True)
class AgentTurn:
    agent_turn_id: str


@dataclass(frozen=True)
class HistoricalAgentSession:
    agent_session_id: str
    private_chat_scope_id: str
    user_id: str
    agent_name: str
    workspace: Workspace
    access_mode: AccessMode | None
    updated_at: str

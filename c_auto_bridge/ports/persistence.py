from typing import Protocol

from c_auto_bridge.core.agent_events import AgentEvent
from c_auto_bridge.core.agent_session import HistoricalAgentSession
from c_auto_bridge.core.pending_request import PendingRequest, PendingRequestStatus
from c_auto_bridge.core.run import Run, RunStatus
from c_auto_bridge.core.workspace import NamedWorkspace


class RunPersistencePort(Protocol):
    async def record_run_created(self, run: Run) -> None:
        ...

    async def record_run_event(self, *, run_id: str, event: AgentEvent) -> None:
        ...

    async def record_run_terminal_status(
        self,
        *,
        run_id: str,
        status: RunStatus,
        updated_at: str,
    ) -> None:
        ...

    async def open_pending_request(
        self,
        *,
        run_id: str,
        pending_request: PendingRequest,
    ) -> None:
        ...

    async def close_pending_request(
        self,
        *,
        pending_request_id: str,
        status: PendingRequestStatus,
    ) -> None:
        ...

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        ...

    async def save_named_workspace(self, *, workspace: NamedWorkspace) -> None:
        ...

    async def get_named_workspace(self, *, name: str) -> NamedWorkspace | None:
        ...

    async def list_named_workspaces(self) -> list[NamedWorkspace]:
        ...

    async def remove_named_workspace(self, *, name: str) -> None:
        ...

    async def save_agent_session(
        self,
        *,
        agent_session: HistoricalAgentSession,
    ) -> None:
        ...

    async def list_agent_sessions(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
    ) -> list[HistoricalAgentSession]:
        ...

from collections.abc import AsyncIterator
from typing import Protocol

from c_auto_bridge.core.agent_events import AgentEvent
from c_auto_bridge.core.agent_session import AccessMode, AgentSession, Workspace


class AgentThreadNotFound(RuntimeError):
    pass


class AgentTurnStreamPort(Protocol):
    @property
    def agent_turn(self):
        ...

    @property
    def events(self) -> AsyncIterator[AgentEvent]:
        ...

    async def answer_user_input(self, text: str) -> None:
        ...

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        ...

    async def stop(self) -> None:
        ...


class AgentPort(Protocol):
    async def create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: AccessMode,
    ) -> AgentSession:
        ...

    async def get_or_create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: AccessMode,
    ) -> AgentSession:
        ...

    async def start_turn(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
    ) -> AgentTurnStreamPort:
        ...

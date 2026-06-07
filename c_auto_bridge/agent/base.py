from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from c_auto_bridge.react.events import AgentEvent
from c_auto_bridge.session.models import SessionRef
from c_auto_bridge.ports.agent import AgentThreadNotFound


class AgentRun(ABC):
    @property
    @abstractmethod
    def thread_id(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def turn_id(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def events(self) -> AsyncIterator[AgentEvent]:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def answer_user_input(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def answer_approval(self, request_id: str, decision: str) -> None:
        raise NotImplementedError


class AgentAdapter(ABC):
    @abstractmethod
    async def create_session(
        self,
        *,
        owner_user_id: str,
        chat_id: str,
        title: str | None,
    ) -> SessionRef:
        raise NotImplementedError

    @abstractmethod
    async def start_turn(self, session: SessionRef, user_text: str) -> AgentRun:
        raise NotImplementedError

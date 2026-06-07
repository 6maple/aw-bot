from abc import ABC, abstractmethod

from c_auto_bridge.core.workspace import NamedWorkspace
from c_auto_bridge.react.events import AgentEvent
from c_auto_bridge.session.models import PendingRef, PendingStatus, SessionRef
from c_auto_bridge.store.models import RunRef, StreamCardRef, WorkspaceBinding


class Store(ABC):
    @abstractmethod
    def save_session(self, session: SessionRef) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_session(self, bot_session_id: str) -> SessionRef | None:
        raise NotImplementedError

    @abstractmethod
    def list_sessions(self, owner_feishu_user_id: str, limit: int) -> list[SessionRef]:
        raise NotImplementedError

    @abstractmethod
    def set_current_session(self, feishu_user_id: str, bot_session_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_current_session(self, feishu_user_id: str) -> SessionRef | None:
        raise NotImplementedError

    @abstractmethod
    def save_pending(self, pending: PendingRef) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_open_pending_by_user(self, feishu_user_id: str) -> PendingRef | None:
        raise NotImplementedError

    @abstractmethod
    def close_pending(self, pending_id: str, status: PendingStatus) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_run(self, run: RunRef) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_run(self, run_id: str) -> RunRef | None:
        raise NotImplementedError

    @abstractmethod
    def list_runs(self, scope_id: str, limit: int) -> list[RunRef]:
        raise NotImplementedError

    @abstractmethod
    def save_card(self, card: StreamCardRef) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_card(self, card_id: str) -> StreamCardRef | None:
        raise NotImplementedError

    @abstractmethod
    def save_workspace(self, workspace: WorkspaceBinding) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_workspace(self, scope_id: str) -> WorkspaceBinding | None:
        raise NotImplementedError

    @abstractmethod
    def save_named_workspace(self, workspace: NamedWorkspace) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_named_workspace(self, name: str) -> NamedWorkspace | None:
        raise NotImplementedError

    @abstractmethod
    def list_named_workspaces(self) -> list[NamedWorkspace]:
        raise NotImplementedError

    @abstractmethod
    def remove_named_workspace(self, name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def append_run_event(self, run_id: str, event: AgentEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def append_run_error(self, run_id: str, error: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def recover_incomplete(self, updated_at: str) -> None:
        raise NotImplementedError

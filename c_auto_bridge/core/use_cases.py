import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from c_auto_bridge.core.agent_session import AccessMode, HistoricalAgentSession, Workspace
from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.core.idle_timeout import IdleTimeoutScheduler
from c_auto_bridge.core.run import Run
from c_auto_bridge.core.run_controller import RunController
from c_auto_bridge.core.workspace import NamedWorkspace, WorkspaceValidator
from c_auto_bridge.ports.agent import AgentPort
from c_auto_bridge.ports.persistence import RunPersistencePort
from c_auto_bridge.ports.run_view_sink import RunViewSinkPort
from c_auto_bridge.react.pending import map_approval_decision


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrivateChatTextMessage:
    private_chat_scope_id: str
    user_id: str
    text: str
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class RunViewAction:
    private_chat_scope_id: str
    user_id: str
    action: str
    pending_request_id: str


@dataclass(frozen=True)
class WorkspaceChanged:
    workspace: Workspace


@dataclass(frozen=True)
class WorkspaceSaved:
    named_workspace: NamedWorkspace


@dataclass(frozen=True)
class WorkspaceListResult:
    workspaces: tuple[NamedWorkspace, ...]


@dataclass(frozen=True)
class WorkspaceRemoved:
    name: str


@dataclass(frozen=True)
class ResumeSessionList:
    sessions: tuple[HistoricalAgentSession, ...]


@dataclass(frozen=True)
class ResumeSessionRestored:
    session: HistoricalAgentSession


@dataclass(frozen=True)
class IdleTimeoutStatus:
    scope_timeout_minutes: int | None


@dataclass(frozen=True)
class ApprovalDecisionRequired:
    pending_request_id: str
    message: str = "审批等待中，请回复“同意”继续，或回复“拒绝”取消。"


class CoreUseCases:
    def __init__(
        self,
        *,
        agent: AgentPort,
        persistence: RunPersistencePort,
        run_view_sink: RunViewSinkPort,
        workspace: Workspace,
        workspace_validator: WorkspaceValidator,
        access_mode: AccessMode,
        agent_name: str,
        clock: Callable[[], datetime],
        run_id_factory: Callable[[datetime], str],
        default_idle_timeout_seconds: float | None = None,
        idle_timeout_scheduler: IdleTimeoutScheduler | None = None,
    ) -> None:
        self._clock = clock
        self._workspace_validator = workspace_validator
        self._persistence = persistence
        self._run_controller = RunController(
            agent=agent,
            persistence=persistence,
            run_view_sink=run_view_sink,
            workspace=workspace,
            access_mode=access_mode,
            agent_name=agent_name,
            clock=clock,
            run_id_factory=run_id_factory,
            default_idle_timeout_seconds=default_idle_timeout_seconds,
            idle_timeout_scheduler=idle_timeout_scheduler,
        )

    async def handle_private_chat_text(self, message: PrivateChatTextMessage) -> Run:
        command = message.text.strip()
        logger.info(
            "core private chat text received: chat_id=%s user_id=%s text_len=%s command=%s",
            message.private_chat_scope_id,
            message.user_id,
            len(message.text),
            _command_name(command),
        )
        if command == "/stop":
            logger.info("core routing command: chat_id=%s command=/stop", message.private_chat_scope_id)
            return await self._run_controller.stop_run(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
            )
        if command in {"/new", "/reset"}:
            logger.info("core routing command: chat_id=%s command=%s", message.private_chat_scope_id, command)
            return await self._run_controller.reset_session(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
            )
        if command == "/timeout":
            raise ValueError("timeout value is required")
        if command.startswith("/timeout "):
            value = command.removeprefix("/timeout ").strip()
            if value == "off":
                self._run_controller.disable_idle_timeout(private_chat_scope_id=message.private_chat_scope_id)
                return IdleTimeoutStatus(scope_timeout_minutes=None)
            if value == "default":
                self._run_controller.clear_idle_timeout_override(private_chat_scope_id=message.private_chat_scope_id)
                timeout_seconds = self._run_controller.get_idle_timeout_seconds(
                    private_chat_scope_id=message.private_chat_scope_id
                )
                return IdleTimeoutStatus(
                    scope_timeout_minutes=None if timeout_seconds is None else int(timeout_seconds / 60)
                )
            minutes = int(value)
            if minutes <= 0:
                raise ValueError("timeout minutes must be positive")
            self._run_controller.set_idle_timeout_seconds(
                private_chat_scope_id=message.private_chat_scope_id,
                timeout_seconds=minutes * 60,
            )
            return IdleTimeoutStatus(scope_timeout_minutes=minutes)
        if command == "/cd":
            raise ValueError("workspace path is required")
        if command.startswith("/cd "):
            workspace = self._workspace_validator.validate(command.removeprefix("/cd ").strip())
            await self._run_controller.change_workspace(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
                workspace=workspace,
            )
            return WorkspaceChanged(workspace=workspace)
        if command == "/ws":
            raise ValueError("workspace subcommand is required")
        if command == "/ws list":
            workspaces = await self._persistence.list_named_workspaces()
            return WorkspaceListResult(workspaces=tuple(workspaces))
        if command == "/ws save":
            raise ValueError("workspace name is required")
        if command.startswith("/ws save "):
            workspace = self._workspace_validator.validate(self._run_controller.workspace.path)
            name = command.removeprefix("/ws save ").strip()
            named_workspace = NamedWorkspace(
                name=name,
                workspace=workspace,
                updated_at=self._clock().isoformat(),
            )
            await self._persistence.save_named_workspace(workspace=named_workspace)
            return WorkspaceSaved(named_workspace=named_workspace)
        if command == "/ws use":
            raise ValueError("workspace name is required")
        if command.startswith("/ws use "):
            name = command.removeprefix("/ws use ").strip()
            named_workspace = await self._persistence.get_named_workspace(name=name)
            if named_workspace is None:
                raise ValueError(f"workspace is not saved: {name}")
            workspace = self._workspace_validator.validate(named_workspace.workspace.path)
            await self._run_controller.change_workspace(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
                workspace=workspace,
            )
            return WorkspaceChanged(workspace=workspace)
        if command == "/ws remove":
            raise ValueError("workspace name is required")
        if command.startswith("/ws remove "):
            name = command.removeprefix("/ws remove ").strip()
            await self._persistence.remove_named_workspace(name=name)
            return WorkspaceRemoved(name=name)
        if self._run_controller.has_open_user_input_pending_request(
            private_chat_scope_id=message.private_chat_scope_id,
            user_id=message.user_id,
        ):
            logger.info("core routing text to pending user input: chat_id=%s", message.private_chat_scope_id)
            return await self._run_controller.answer_user_input(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
                text=message.text,
            )
        pending_approval_id = self._run_controller.open_approval_pending_request_id(
            private_chat_scope_id=message.private_chat_scope_id,
            user_id=message.user_id,
        )
        if pending_approval_id is not None:
            decision = map_approval_decision(message.text)
            if decision is None:
                logger.info(
                    "core received non-decision text while approval pending: chat_id=%s text_len=%s",
                    message.private_chat_scope_id,
                    len(message.text),
                )
                return ApprovalDecisionRequired(pending_request_id=pending_approval_id)
            logger.info(
                "core routing text to pending approval: chat_id=%s decision=%s",
                message.private_chat_scope_id,
                decision,
            )
            return await self._run_controller.answer_approval(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
                pending_request_id=pending_approval_id,
                decision=decision,
            )
        if self._run_controller.has_active_run(
            private_chat_scope_id=message.private_chat_scope_id,
            user_id=message.user_id,
        ):
            logger.info("core routing text to active run queue: chat_id=%s", message.private_chat_scope_id)
            return await self._run_controller.queue_message(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
                text=message.text,
                attachments=message.attachments,
            )
        if command == "/resume":
            logger.info("core routing command: chat_id=%s command=/resume", message.private_chat_scope_id)
            sessions = await self._persistence.list_agent_sessions(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
            )
            compatible_sessions = tuple(
                session for session in sessions if self._resume_compatibility_error(session) is None
            )
            return ResumeSessionList(sessions=compatible_sessions)
        if command.startswith("/resume "):
            session_id = command.removeprefix("/resume ").strip()
            sessions = await self._persistence.list_agent_sessions(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
            )
            session = next((item for item in sessions if item.agent_session_id == session_id), None)
            if session is None:
                raise ValueError(f"historical session was not found: {session_id}")
            error = self._resume_compatibility_error(session)
            if error is not None:
                raise ValueError(error)
            await self._run_controller.resume_session(
                private_chat_scope_id=message.private_chat_scope_id,
                user_id=message.user_id,
                historical_session=session,
            )
            return ResumeSessionRestored(session=session)
        logger.info("core routing text to new run: chat_id=%s", message.private_chat_scope_id)
        return await self._run_controller.start_text_run(
            private_chat_scope_id=message.private_chat_scope_id,
            user_id=message.user_id,
            text=message.text,
            attachments=message.attachments,
        )

    async def handle_run_view_action(self, action: RunViewAction) -> Run:
        return await self._run_controller.answer_approval(
            private_chat_scope_id=action.private_chat_scope_id,
            user_id=action.user_id,
            pending_request_id=action.pending_request_id,
            decision=action.action,
        )

    def _resume_compatibility_error(self, session: HistoricalAgentSession) -> str | None:
        if session.agent_name != self._run_controller.agent_name:
            return "historical session has a different agent"
        if session.workspace.path != self._run_controller.workspace.path:
            return "historical session has a different workspace"
        if session.access_mode != self._run_controller.access_mode:
            return "historical session has an incompatible access mode"
        return None


def _command_name(command: str) -> str:
    if not command.startswith("/"):
        return "text"
    return command.split(maxsplit=1)[0]

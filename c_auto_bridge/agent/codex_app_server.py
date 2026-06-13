import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any, Protocol

from c_auto_bridge.agent.codex_jsonrpc import JsonRpcError
from c_auto_bridge.agent.codex_translator import translate_codex_event
from c_auto_bridge.config_codex import CodexConfig
from c_auto_bridge.core.agent_events import AgentEvent, RunCompleted, RunFailed, RunInterrupted, RunTimedOut
from c_auto_bridge.core.agent_session import AgentSession, AgentTurn, Workspace
from c_auto_bridge.core.use_cases import SkillInfo
from c_auto_bridge.ports.agent import AgentThreadNotFound, AgentTurnStreamPort
from c_auto_bridge.store.base import Store
from c_auto_bridge.session.models import SessionRef


class CodexRpc(Protocol):
    async def connect(self) -> None:
        raise NotImplementedError

    async def initialize(self) -> dict[str, Any]:
        raise NotImplementedError

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        raise NotImplementedError

    async def listen(self):
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class CodexAppServerAdapter:
    def __init__(
        self,
        *,
        config: CodexConfig,
        store: Store,
        rpc: CodexRpc,
        event_router: "CodexEventRouter | None" = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.rpc = rpc
        self.event_router = event_router if event_router is not None else CodexEventRouter()
        self.clock = clock or (lambda: datetime.now().astimezone())

    async def list_models(self, *, workspace: Workspace) -> tuple[str, ...]:
        return self.config.models

    async def list_skills(self, *, workspace: Workspace) -> tuple[SkillInfo, ...]:
        payload = await self.rpc.request("skill/list", {"cwd": workspace.path})
        skills = payload.get("skills")
        if not isinstance(skills, list):
            raise TypeError("skills must be a list")
        return tuple(_skill_info(item) for item in skills)

    async def create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        thread_id = await self._start_thread(workspace=workspace)
        self.store.save_session(
            SessionRef(
                bot_session_id=thread_id,
                owner_feishu_user_id=user_id,
                owner_chat_id=private_chat_scope_id,
                agent=agent_name,
                codex_thread_id=thread_id,
                title=thread_id,
                cwd=workspace.path,
                access_mode=access_mode,
                status="idle",
                created_at=self.clock().isoformat(),
                updated_at=self.clock().isoformat(),
            )
        )
        self.store.set_current_session(user_id, thread_id)
        return AgentSession(
            agent_session_id=thread_id,
            private_chat_scope_id=private_chat_scope_id,
            user_id=user_id,
            agent_name=agent_name,
            workspace=workspace,
            access_mode=access_mode,
        )

    async def get_or_create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        current = self.store.get_current_session(user_id)
        if current is None:
            return await self.create_session(
                private_chat_scope_id=private_chat_scope_id,
                user_id=user_id,
                agent_name=agent_name,
                workspace=workspace,
                access_mode=access_mode,
            )
        if (
            current.owner_chat_id != private_chat_scope_id
            or current.agent != agent_name
            or current.cwd != workspace.path
            or current.access_mode != access_mode
        ):
            return await self.create_session(
                private_chat_scope_id=private_chat_scope_id,
                user_id=user_id,
                agent_name=agent_name,
                workspace=workspace,
                access_mode=access_mode,
            )
        return AgentSession(
            agent_session_id=current.bot_session_id,
            private_chat_scope_id=current.owner_chat_id,
            user_id=current.owner_feishu_user_id,
            agent_name=current.agent,
            workspace=Workspace(path=current.cwd),
            access_mode=current.access_mode or access_mode,
        )

    async def start_turn(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
        model: str | None,
        opencode_agent: str | None = None,
    ) -> AgentTurnStreamPort:
        try:
            result = await self.rpc.request(
                "turn/start",
                {
                    "threadId": agent_session.agent_session_id,
                    "cwd": agent_session.workspace.path,
                    "input": [{"type": "text", "text": prompt}],
                    "model": model if model is not None else self.config.model,
                    "approvalPolicy": self.config.approval_policy,
                    "sandboxPolicy": self._sandbox_policy(agent_session.workspace),
                },
            )
        except JsonRpcError as exc:
            if _is_thread_not_found(exc):
                raise AgentThreadNotFound(str(exc)) from exc
            raise
        session = self.store.get_session(agent_session.agent_session_id)
        if session is not None:
            session.status = "running"
            session.updated_at = self.clock().isoformat()
            self.store.save_session(session)
        turn_id = result["turn"]["id"]
        queue = self.event_router.register(turn_id, agent_session.agent_session_id)
        return CodexTurnStream(
            rpc=self.rpc,
            event_router=self.event_router,
            agent_session_id=agent_session.agent_session_id,
            agent_turn=AgentTurn(agent_turn_id=turn_id),
            queue=queue,
        )

    async def _start_thread(self, *, workspace: Workspace) -> str:
        result = await self.rpc.request(
            "thread/start",
            {
                "cwd": workspace.path,
                "model": self.config.model,
                "approvalPolicy": self.config.approval_policy,
                "sandbox": self.config.sandbox,
            },
        )
        return result["thread"]["id"]

    def _sandbox_policy(self, workspace: Workspace) -> dict[str, Any]:
        if self.config.sandbox != "workspace-write":
            raise ValueError(f"unsupported Codex sandbox: {self.config.sandbox}")
        return {
            "type": "workspaceWrite",
            "writableRoots": [workspace.path],
            "networkAccess": False,
        }


def _is_thread_not_found(exc: JsonRpcError) -> bool:
    message = exc.error.get("message")
    return isinstance(message, str) and message.startswith("thread not found:")


def _skill_info(payload: Any) -> SkillInfo:
    if not isinstance(payload, dict):
        raise TypeError("skill must be a dict")
    name = payload.get("name")
    if not isinstance(name, str):
        raise TypeError("skill name must be a string")
    description = payload.get("description")
    if description is not None and not isinstance(description, str):
        raise TypeError("skill description must be a string")
    return SkillInfo(name=name, description=description)


class CodexEventRouter:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[AgentEvent]] = {}
        self._thread_turns: dict[str, str] = {}
        self._early_events: dict[str, list[AgentEvent]] = {}
        self._requests: dict[str, tuple[int | str, str, dict[str, Any], str]] = {}

    def register(self, turn_id: str, thread_id: str) -> asyncio.Queue[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._queues[turn_id] = queue
        self._thread_turns[thread_id] = turn_id
        for event in self._early_events.pop(turn_id, []):
            queue.put_nowait(event)
        for event in self._early_events.pop(thread_id, []):
            queue.put_nowait(event)
        return queue

    def unregister(self, turn_id: str, thread_id: str) -> None:
        self._queues.pop(turn_id, None)
        if self._thread_turns.get(thread_id) == turn_id:
            self._thread_turns.pop(thread_id, None)

    async def handle_event(self, raw: dict[str, Any]) -> None:
        translated = translate_codex_event(raw)
        if translated is None:
            return
        if translated.request_id is not None:
            self._requests[str(translated.request_id)] = (
                translated.request_id,
                raw["method"],
                raw["params"],
                translated.turn_id,
            )
        route_id = translated.turn_id
        if route_id is None and translated.thread_id is not None:
            route_id = self._thread_turns.get(translated.thread_id)
        queue = self._queues.get(route_id) if route_id is not None else None
        if queue is None:
            early_id = translated.turn_id or translated.thread_id
            if early_id is not None:
                self._early_events.setdefault(early_id, []).append(translated.event)
            return
        await queue.put(translated.event)

    def take_request(
        self,
        *,
        turn_id: str,
        request_id: str | None = None,
        method: str | None = None,
    ) -> tuple[int | str, str, dict[str, Any]]:
        for pending_id, (raw_id, pending_method, params, pending_turn_id) in self._requests.items():
            if pending_turn_id != turn_id:
                continue
            if request_id is not None and pending_id != request_id:
                continue
            if method is not None and pending_method != method:
                continue
            self._requests.pop(pending_id)
            return raw_id, pending_method, params
        raise KeyError(request_id or method or turn_id)


class CodexTurnStream:
    def __init__(
        self,
        *,
        rpc: CodexRpc,
        event_router: CodexEventRouter,
        agent_session_id: str,
        agent_turn: AgentTurn,
        queue: asyncio.Queue[AgentEvent],
    ) -> None:
        self.rpc = rpc
        self.event_router = event_router
        self._agent_session_id = agent_session_id
        self._agent_turn = agent_turn
        self.queue = queue

    @property
    def agent_turn(self) -> AgentTurn:
        return self._agent_turn

    @property
    def events(self) -> AsyncIterator[AgentEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[AgentEvent]:
        while True:
            event = await self.queue.get()
            if isinstance(event, (RunCompleted, RunFailed, RunInterrupted, RunTimedOut)):
                self.event_router.unregister(self.agent_turn.agent_turn_id, self._agent_session_id)
                yield event
                return
            yield event

    async def stop(self) -> None:
        await self.rpc.request(
            "turn/interrupt",
            {"threadId": self._agent_session_id, "turnId": self.agent_turn.agent_turn_id},
        )

    async def answer_user_input(self, text: str) -> None:
        request_id, _, params = self.event_router.take_request(
            turn_id=self.agent_turn.agent_turn_id,
            method="item/tool/requestUserInput",
        )
        questions = params["questions"]
        await self.rpc.respond(
            request_id,
            {"answers": {question["id"]: {"answers": [text]} for question in questions}},
        )

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        raw_id, _, _ = self.event_router.take_request(
            turn_id=self.agent_turn.agent_turn_id,
            request_id=pending_request_id,
        )
        await self.rpc.respond(raw_id, {"decision": _approval_decision(decision)})


def _approval_decision(decision: str) -> str:
    if decision == "accept":
        return "accept"
    if decision == "deny":
        return "decline"
    raise ValueError(f"unsupported Codex approval decision: {decision}")

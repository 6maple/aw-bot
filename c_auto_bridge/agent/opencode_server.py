import asyncio
import logging
import secrets
import string
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from c_auto_bridge.agent.opencode_http import OpencodeHttpError
from c_auto_bridge.agent.opencode_translator import translate_opencode_event
from c_auto_bridge.config_opencode import OpenCodeConfig, opencode_model_payload
from c_auto_bridge.core.agent_events import (
    AgentEvent,
    ApprovalRequested,
    RunCompleted,
    RunFailed,
    RunInterrupted,
    RunTimedOut,
    TextDelta,
    ThinkingDelta,
    UserInputRequested,
)
from c_auto_bridge.core.agent_session import AgentSession, AgentTurn, Workspace
from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.core.use_cases import SkillInfo
from c_auto_bridge.ports.agent import AgentThreadNotFound, AgentTurnStreamPort
from c_auto_bridge.session.models import SessionRef
from c_auto_bridge.store.base import Store


logger = logging.getLogger(__name__)
_last_message_id_millis = 0
_message_id_counter = 0


@dataclass(frozen=True)
class OpenCodeQuestionCapability:
    request_event: str
    reply_endpoint: str


class OpencodeClient(Protocol):
    async def list_providers(self, *, workspace: str) -> dict[str, Any]: ...
    async def list_skills(self, *, workspace: str) -> list[dict[str, Any]]: ...
    async def create_session(self, *, title: str, workspace: str) -> dict[str, Any]: ...
    async def session_messages(self, *, session_id: str, workspace: str) -> list[dict[str, Any]]: ...
    async def prompt_async(
        self, *, session_id: str, message_id: str, text: str,
        model: dict[str, str] | None, agent: str | None, workspace: str,
    ) -> bool: ...
    async def answer_question(
        self, *, question_id: str, answers: list[list[str]], workspace: str,
    ) -> bool: ...
    async def answer_permission(
        self, *, session_id: str, permission_id: str, decision: str, workspace: str,
    ) -> bool: ...
    async def abort_session(self, *, session_id: str, workspace: str) -> bool: ...
    async def events(self, *, workspace: str): ...


class OpenCodeServerAdapter:
    def __init__(
        self,
        *,
        config: OpenCodeConfig,
        store: Store,
        client: OpencodeClient,
        event_router: "OpenCodeEventRouter | None" = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.client = client
        self.event_router = event_router if event_router is not None else OpenCodeEventRouter()
        self.clock = clock or (lambda: datetime.now().astimezone())

    async def list_models(self, *, workspace: Workspace) -> tuple[str, ...]:
        providers = await self.client.list_providers(workspace=workspace.path)
        return _provider_model_ids(providers)

    async def list_skills(self, *, workspace: Workspace) -> tuple[SkillInfo, ...]:
        payload = await self.client.list_skills(workspace=workspace.path)
        if not isinstance(payload, list):
            raise TypeError("skills must be a list")
        return tuple(_skill_info(item) for item in payload)

    async def create_session(
        self,
        *,
        private_chat_scope_id: str,
        user_id: str,
        agent_name: str,
        workspace: Workspace,
        access_mode: str,
    ) -> AgentSession:
        result = await self.client.create_session(title=_new_session_title(self.clock()), workspace=workspace.path)
        session_id = _required_str(result, "id")
        self.store.save_session(
            SessionRef(
                bot_session_id=session_id,
                owner_feishu_user_id=user_id,
                owner_chat_id=private_chat_scope_id,
                agent=agent_name,
                codex_thread_id=session_id,
                title=session_id,
                cwd=workspace.path,
                access_mode=access_mode,
                status="idle",
                created_at=self.clock().isoformat(),
                updated_at=self.clock().isoformat(),
            )
        )
        self.store.set_current_session(user_id, session_id)
        return AgentSession(
            agent_session_id=session_id,
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
        model: str | None = None,
        opencode_agent: str | None = None,
        attachments: tuple[Attachment, ...] = (),
    ) -> AgentTurnStreamPort:
        if attachments:
            raise ValueError("OpenCode attachments are not supported")
        message_id = _new_message_id(self.clock())
        queue = self.event_router.register(agent_session.agent_session_id, message_id)
        try:
            await self.client.prompt_async(
                session_id=agent_session.agent_session_id,
                message_id=message_id,
                text=prompt,
                model=opencode_model_payload(model if model is not None else self.config.model),
                agent=opencode_agent if opencode_agent is not None else self.config.agent,
                workspace=agent_session.workspace.path,
            )
        except OpencodeHttpError as exc:
            self.event_router.unregister(agent_session.agent_session_id, message_id)
            if exc.status == 404:
                raise AgentThreadNotFound(str(exc)) from exc
            raise
        session = self.store.get_session(agent_session.agent_session_id)
        if session is not None:
            session.status = "running"
            session.updated_at = self.clock().isoformat()
            self.store.save_session(session)
        return OpenCodeTurnStream(
            client=self.client,
            router=self.event_router,
            agent_session_id=agent_session.agent_session_id,
            workspace=agent_session.workspace.path,
            agent_turn=AgentTurn(agent_turn_id=message_id),
            queue=queue,
        )


class OpenCodeEventRouter:
    def __init__(self, *, question_capability: OpenCodeQuestionCapability | None = None) -> None:
        self.question_capability = question_capability
        self._queues: dict[tuple[str, str], asyncio.Queue[AgentEvent]] = {}
        self._session_messages: dict[str, str] = {}
        self._session_assistants: dict[str, str] = {}
        self._early: dict[tuple[str, str | None], list[AgentEvent]] = {}
        self._message_roles: dict[tuple[str, str], str] = {}
        self._message_parents: dict[tuple[str, str], str] = {}
        self._part_types: dict[tuple[str, str, str], str] = {}
        self._part_texts: dict[tuple[str, str, str], str] = {}
        self._part_conflicts: set[tuple[str, str, str]] = set()
        self._tool_part_statuses: dict[tuple[str, str, str], str] = {}

    def register(self, session_id: str, message_id: str) -> asyncio.Queue[AgentEvent]:
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._queues[(session_id, message_id)] = queue
        self._session_messages[session_id] = message_id
        self._session_assistants.pop(session_id, None)
        keys = [key for key in self._early if key[0] == session_id and isinstance(key[1], str)]
        for key in keys:
            early_message_id = key[1]
            if self._message_parents.get((session_id, early_message_id)) != message_id:
                continue
            self._session_assistants[session_id] = early_message_id
            for event in self._early.pop(key, []):
                queue.put_nowait(event)
        return queue

    def unregister(self, session_id: str, message_id: str) -> None:
        self._queues.pop((session_id, message_id), None)
        if self._session_messages.get(session_id) == message_id:
            self._session_messages.pop(session_id, None)
            self._session_assistants.pop(session_id, None)

    async def handle_stream_interruption(self, reason: str) -> None:
        event = RunFailed(f"OpenCode event stream interrupted: {reason}")
        for queue in list(self._queues.values()):
            await queue.put(event)

    async def handle_event(self, raw: dict[str, Any]) -> None:
        logger.debug("opencode event received: %s", _raw_event_summary(raw))
        if await self._handle_question_event(raw):
            return
        if await self._handle_unsupported_question_event(raw):
            return
        self._remember_part_delta(raw)
        raw = self._with_part_update_delta(raw)
        if self._is_duplicate_tool_part_status(raw):
            logger.debug("opencode event ignored: %s", _raw_event_summary(raw))
            return
        self._remember_message_context(raw)
        self._replay_bound_assistant_events(raw)
        translated = translate_opencode_event(self._with_known_part_type(raw))
        if translated is None:
            if _is_known_ignored_event(raw):
                logger.debug("opencode event ignored: %s", _raw_event_summary(raw))
                return
            active_turn_match = self._active_turn_match(raw)
            if active_turn_match == "active_turn" and _is_interactive_unknown_event(raw):
                self._log_unknown_event(raw, logging.WARNING, "run_failed", active_turn_match)
                queue = self._queue_for_active_turn(_required_active_session_id(raw))
                if queue is not None:
                    await queue.put(RunFailed(f"Unsupported OpenCode interactive event: {raw.get('type')}"))
                return
            level = logging.DEBUG if active_turn_match == "unrelated" else logging.WARNING
            self._log_unknown_event(raw, level, "ignored", active_turn_match)
            return
        if self._is_user_text_event(translated):
            logger.debug(
                "ignored OpenCode user text event: session_id=%s message_id=%s event=%s",
                translated.session_id,
                translated.message_id,
                type(translated.event).__name__,
            )
            return
        logger.info(
            "opencode event translated: session_id=%s message_id=%s event=%s",
            translated.session_id,
            translated.message_id,
            type(translated.event).__name__,
        )
        if translated.message_id is None and isinstance(translated.event, ApprovalRequested):
            logger.debug(
                "ignored unbound OpenCode interactive event: session_id=%s message_id=%s event=%s",
                translated.session_id,
                translated.message_id,
                type(translated.event).__name__,
            )
            return
        if translated.message_id is None:
            queue = self._queue_for_active_turn(translated.session_id)
            if queue is None:
                logger.debug(
                    "queued early OpenCode event: session_id=%s message_id=%s event=%s",
                    translated.session_id,
                    translated.message_id,
                    type(translated.event).__name__,
                )
                self._early.setdefault((translated.session_id, translated.message_id), []).append(translated.event)
                return
            await queue.put(translated.event)
            return
        queue = self._queue_for_message(translated.session_id, translated.message_id)
        if queue is None:
            logger.debug(
                "queued early OpenCode event: session_id=%s message_id=%s event=%s",
                translated.session_id,
                translated.message_id,
                type(translated.event).__name__,
            )
            self._early.setdefault((translated.session_id, translated.message_id), []).append(translated.event)
            return
        await queue.put(translated.event)

    async def _handle_question_event(self, raw: dict[str, Any]) -> bool:
        if not _question_capability_enabled(self.question_capability):
            return False
        if raw.get("type") != "question.asked":
            return False
        properties = raw.get("properties")
        if not isinstance(properties, dict):
            return False
        session_id = properties.get("sessionID")
        if not isinstance(session_id, str):
            return False
        event = _question_request_event(properties)
        message_id = _event_message_id(properties)
        if message_id is None:
            logger.debug(
                "ignored unbound OpenCode question event: session_id=%s type=%s",
                session_id,
                raw.get("type"),
            )
            return True
        elif isinstance(message_id, str):
            queue = self._queue_for_message(session_id, message_id)
        else:
            raise TypeError("messageID must be a string")
        if queue is None:
            self._early.setdefault((session_id, message_id), []).append(event)
            return True
        await queue.put(event)
        return True

    async def _handle_unsupported_question_event(self, raw: dict[str, Any]) -> bool:
        if raw.get("type") not in {"question.asked", "question.v2.asked"}:
            return False
        properties = raw.get("properties")
        if not isinstance(properties, dict):
            return False
        session_id = properties.get("sessionID")
        if not isinstance(session_id, str):
            return False
        message_id = _event_message_id(properties)
        if message_id is None:
            logger.debug(
                "ignored unsupported unbound OpenCode question event: session_id=%s type=%s",
                session_id,
                raw.get("type"),
            )
            return True
        if not isinstance(message_id, str):
            raise TypeError("messageID must be a string")
        queue = self._queue_for_message(session_id, message_id)
        if queue is None:
            logger.debug(
                "ignored unsupported OpenCode question event without active run: session_id=%s type=%s",
                session_id,
                raw.get("type"),
            )
            return True
        logger.warning(
            "OpenCode question support is unavailable: session_id=%s type=%s",
            session_id,
            raw.get("type"),
        )
        await queue.put(RunFailed("OpenCode question support is unavailable"))
        return True

    def _log_unknown_event(
        self,
        raw: dict[str, Any],
        level: int,
        handling_result: str,
        active_turn_match: str,
    ) -> None:
        details = _unknown_event_details(raw, active_turn_match)
        logger.log(
            level,
            "opencode unknown event %s: type=%s session_id=%s message_id=%s part_id=%s part_type=%s active_turn_match=%s",
            handling_result,
            details["event_type"],
            details["session_id"],
            details["message_id"],
            details["part_id"],
            details["part_type"],
            details["active_turn_match"],
            extra=details | {"handling_result": handling_result},
        )

    def _active_turn_match(self, raw: dict[str, Any]) -> str:
        properties = raw.get("properties")
        if not isinstance(properties, dict):
            return "unrelated"
        session_id = _event_session_id(properties)
        if session_id is None:
            return "unrelated"
        active_message_id = self._session_messages.get(session_id)
        if active_message_id is None:
            return "unrelated"
        message_id = _event_message_id(properties)
        if message_id == active_message_id:
            return "active_turn"
        return "active_session"

    def _remember_message_context(self, raw: dict[str, Any]) -> None:
        properties = raw.get("properties")
        if not isinstance(properties, dict):
            return
        info = properties.get("info")
        if isinstance(info, dict):
            session_id = info.get("sessionID")
            message_id = info.get("id")
            role = info.get("role")
            if isinstance(session_id, str) and isinstance(message_id, str) and isinstance(role, str):
                self._message_roles[(session_id, message_id)] = role
                parent_id = info.get("parentID")
                if role == "assistant" and isinstance(parent_id, str):
                    self._message_parents[(session_id, message_id)] = parent_id
        part = properties.get("part")
        if isinstance(part, dict):
            session_id = properties.get("sessionID")
            message_id = part.get("messageID")
            part_id = part.get("id")
            part_type = part.get("type")
            if (
                isinstance(session_id, str)
                and isinstance(message_id, str)
                and isinstance(part_id, str)
                and isinstance(part_type, str)
            ):
                self._part_types[(session_id, message_id, part_id)] = part_type

    def _with_known_part_type(self, raw: dict[str, Any]) -> dict[str, Any]:
        if raw.get("type") != "message.part.delta":
            return raw
        properties = raw.get("properties")
        if not isinstance(properties, dict) or "part" in properties:
            return raw
        session_id = properties.get("sessionID")
        message_id = properties.get("messageID")
        part_id = properties.get("partID")
        if not isinstance(session_id, str) or not isinstance(message_id, str) or not isinstance(part_id, str):
            return raw
        part_type = self._part_types.get((session_id, message_id, part_id))
        if part_type is None:
            return raw
        enriched_properties = dict(properties)
        enriched_properties["_partType"] = part_type
        enriched = dict(raw)
        enriched["properties"] = enriched_properties
        return enriched

    def _with_part_update_delta(self, raw: dict[str, Any]) -> dict[str, Any]:
        if raw.get("type") != "message.part.updated":
            return raw
        properties = raw.get("properties")
        if not isinstance(properties, dict):
            return raw
        part = properties.get("part")
        if not isinstance(part, dict):
            return raw
        text = part.get("text")
        if not isinstance(text, str):
            return raw
        session_id = properties.get("sessionID")
        message_id = part.get("messageID")
        part_id = part.get("id")
        if not isinstance(session_id, str) or not isinstance(message_id, str) or not isinstance(part_id, str):
            return raw
        key = (session_id, message_id, part_id)
        previous = self._part_texts.get(key)
        self._part_texts[key] = text
        if previous is None:
            delta = text
        elif key in self._part_conflicts:
            delta = ""
        elif text.startswith(previous):
            delta = text[len(previous):]
        else:
            logger.warning(
                "OpenCode part update was not append-only: session_id=%s message_id=%s part_id=%s",
                session_id,
                message_id,
                part_id,
            )
            self._part_conflicts.add(key)
            delta = ""
        enriched_properties = dict(properties)
        enriched_properties["delta"] = delta
        enriched = dict(raw)
        enriched["properties"] = enriched_properties
        return enriched

    def _remember_part_delta(self, raw: dict[str, Any]) -> None:
        if raw.get("type") != "message.part.delta":
            return
        properties = raw.get("properties")
        if not isinstance(properties, dict):
            return
        text = properties.get("delta")
        if not isinstance(text, str) or text == "":
            return
        session_id = properties.get("sessionID")
        message_id = properties.get("messageID")
        part_id = properties.get("partID")
        part = properties.get("part")
        if isinstance(part, dict):
            if message_id is None:
                message_id = part.get("messageID")
            if part_id is None:
                part_id = part.get("id")
        if not isinstance(session_id, str) or not isinstance(message_id, str) or not isinstance(part_id, str):
            return
        key = (session_id, message_id, part_id)
        if key in self._part_conflicts:
            return
        self._part_texts[key] = self._part_texts.get(key, "") + text

    def _is_duplicate_tool_part_status(self, raw: dict[str, Any]) -> bool:
        if raw.get("type") != "message.part.updated":
            return False
        properties = raw.get("properties")
        if not isinstance(properties, dict):
            return False
        part = properties.get("part")
        if not isinstance(part, dict) or part.get("type") != "tool":
            return False
        session_id = properties.get("sessionID")
        message_id = part.get("messageID")
        part_id = part.get("id")
        state = part.get("state")
        if (
            not isinstance(session_id, str)
            or not isinstance(message_id, str)
            or not isinstance(part_id, str)
            or not isinstance(state, dict)
        ):
            return False
        status = state.get("status")
        if not isinstance(status, str):
            return False
        key = (session_id, message_id, part_id)
        if self._tool_part_statuses.get(key) == status:
            return True
        self._tool_part_statuses[key] = status
        return False

    def _is_user_text_event(self, translated) -> bool:
        if translated.message_id is None or not _is_text_stream_event(translated.event):
            return False
        role = self._message_roles.get((translated.session_id, translated.message_id))
        return role == "user"

    def _replay_bound_assistant_events(self, raw: dict[str, Any]) -> None:
        properties = raw.get("properties")
        if not isinstance(properties, dict):
            return
        info = properties.get("info")
        if not isinstance(info, dict):
            return
        session_id = info.get("sessionID")
        message_id = info.get("id")
        role = info.get("role")
        parent_id = info.get("parentID")
        if not isinstance(session_id, str) or not isinstance(message_id, str) or role != "assistant":
            return
        if not isinstance(parent_id, str):
            return
        active_message_id = self._session_messages.get(session_id)
        if parent_id != active_message_id:
            return
        queue = self._queue_for_active_turn(session_id)
        if queue is None:
            return
        self._session_assistants[session_id] = message_id
        for event in self._early.pop((session_id, message_id), []):
            queue.put_nowait(event)

    def _queue_for_active_turn(self, session_id: str) -> asyncio.Queue[AgentEvent] | None:
        active_message_id = self._session_messages.get(session_id)
        if active_message_id is None:
            return None
        return self._queues.get((session_id, active_message_id))

    def _queue_for_message(self, session_id: str, message_id: str) -> asyncio.Queue[AgentEvent] | None:
        queue = self._queue_for_active_turn(session_id)
        if queue is None:
            return None
        active_message_id = self._session_messages.get(session_id)
        if message_id == active_message_id:
            return queue
        assistant_message_id = self._session_assistants.get(session_id)
        if assistant_message_id == message_id:
            return queue
        if self._message_parents.get((session_id, message_id)) == active_message_id:
            self._session_assistants[session_id] = message_id
            for event in self._early.pop((session_id, message_id), []):
                queue.put_nowait(event)
            return queue
        return None


class OpenCodeTurnStream:
    def __init__(
        self,
        *,
        client: OpencodeClient,
        router: OpenCodeEventRouter,
        agent_session_id: str,
        workspace: str,
        agent_turn: AgentTurn,
        queue: asyncio.Queue[AgentEvent],
    ) -> None:
        self.client = client
        self.router = router
        self._agent_session_id = agent_session_id
        self._workspace = workspace
        self._agent_turn = agent_turn
        self.queue = queue
        self._text = ""
        self._thinking = ""
        self._saw_activity = False
        self._pending_question_id: str | None = None

    @property
    def agent_turn(self) -> AgentTurn:
        return self._agent_turn

    @property
    def events(self) -> AsyncIterator[AgentEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[AgentEvent]:
        while True:
            event = await self.queue.get()
            if isinstance(event, RunCompleted):
                snapshot_events, assistant_seen = await self._assistant_snapshot_events()
                for snapshot_event in snapshot_events:
                    self._remember_emitted(snapshot_event)
                    yield snapshot_event
                if not self._saw_activity and not assistant_seen:
                    logger.debug(
                        "ignored OpenCode session completion without assistant activity: session_id=%s turn_id=%s",
                        self._agent_session_id,
                        self.agent_turn.agent_turn_id,
                    )
                    continue
                self.router.unregister(self._agent_session_id, self.agent_turn.agent_turn_id)
                yield event
                return
            if isinstance(event, (RunFailed, RunInterrupted, RunTimedOut)):
                self.router.unregister(self._agent_session_id, self.agent_turn.agent_turn_id)
                yield event
                return
            self._remember_emitted(event)
            yield event

    async def stop(self) -> None:
        await self.client.abort_session(session_id=self._agent_session_id, workspace=self._workspace)

    async def answer_user_input(self, text: str) -> None:
        if not _question_capability_enabled(self.router.question_capability):
            raise ValueError("OpenCode question support is unavailable")
        if self._pending_question_id is None:
            raise ValueError("OpenCode question request is not active")
        await self.client.answer_question(
            question_id=self._pending_question_id,
            answers=[[text]],
            workspace=self._workspace,
        )

    async def answer_approval(self, pending_request_id: str, decision: str) -> None:
        await self.client.answer_permission(
            session_id=self._agent_session_id,
            permission_id=pending_request_id,
            decision=_permission_decision(decision),
            workspace=self._workspace,
        )

    async def _assistant_snapshot_events(self) -> tuple[list[AgentEvent], bool]:
        messages = await self.client.session_messages(session_id=self._agent_session_id, workspace=self._workspace)
        assistant = _assistant_message_for_turn(messages, self.agent_turn.agent_turn_id)
        if assistant is None:
            return [], False
        parts = assistant.get("parts")
        if not isinstance(parts, list):
            raise TypeError("parts must be a list")
        events: list[AgentEvent] = []
        thinking = _joined_part_text(parts, "reasoning")
        if thinking is not None:
            delta = _remaining_suffix(current=self._thinking, snapshot=thinking)
            if delta:
                events.append(ThinkingDelta(delta))
        text = _joined_part_text(parts, "text")
        if text is not None:
            delta = _remaining_suffix(current=self._text, snapshot=text)
            if delta:
                events.append(TextDelta(delta))
        return events, True

    def _remember_emitted(self, event: AgentEvent) -> None:
        self._saw_activity = True
        if isinstance(event, UserInputRequested):
            self._pending_question_id = event.pending_request_id
        if isinstance(event, TextDelta):
            self._text += event.text
        elif isinstance(event, ThinkingDelta):
            self._thinking += event.text


def _permission_decision(decision: str) -> str:
    if decision in {"accept", "approve", "allow"}:
        return "once"
    if decision in {"reject", "deny", "abort"}:
        return "reject"
    raise ValueError(f"unsupported OpenCode permission decision: {decision}")


def _question_capability_enabled(capability: OpenCodeQuestionCapability | None) -> bool:
    return (
        capability is not None
        and capability.request_event == "question.asked"
        and capability.reply_endpoint == "/question/:requestID/reply"
    )


def _provider_model_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    providers = payload.get("providers")
    if not isinstance(providers, list):
        raise TypeError("providers must be a list")
    model_ids: list[str] = []
    for provider in providers:
        if not isinstance(provider, dict):
            raise TypeError("provider must be a dict")
        provider_id = _required_str(provider, "id")
        models = provider.get("models")
        if not isinstance(models, dict):
            raise TypeError("models must be a dict")
        for model_id in models:
            if not isinstance(model_id, str):
                raise TypeError("model id must be a string")
            model_ids.append(f"{provider_id}/{model_id}")
    return tuple(model_ids)


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


def _question_request_event(properties: dict[str, Any]) -> AgentEvent:
    request_id = _required_str(properties, "id")
    questions = properties.get("questions")
    if not isinstance(questions, list):
        raise TypeError("questions must be a list")
    if len(questions) != 1:
        return RunFailed("Unsupported OpenCode question request")
    question = questions[0]
    if not isinstance(question, dict):
        raise TypeError("question must be a dict")
    if question.get("multiple") is True:
        return RunFailed("Unsupported OpenCode question request")
    options = question.get("options")
    if options is not None and options != []:
        return RunFailed("Unsupported OpenCode question request")
    custom = question.get("custom")
    if custom is not None and custom is not False:
        return RunFailed("Unsupported OpenCode question request")
    return UserInputRequested(
        request_id,
        _required_str(question, "question"),
        properties,
    )


def _new_session_title(now: datetime) -> str:
    return f"session_{now:%Y%m%d_%H%M%S_%f}"


def _new_message_id(now: datetime) -> str:
    global _last_message_id_millis, _message_id_counter
    millis = int(now.timestamp() * 1000)
    if millis != _last_message_id_millis:
        _last_message_id_millis = millis
        _message_id_counter = 0
    _message_id_counter += 1
    encoded = (millis * 0x1000 + _message_id_counter) & ((1 << 48) - 1)
    return f"msg_{encoded:012x}{_random_base62(14)}"


def _random_base62(length: int) -> str:
    alphabet = string.digits + string.ascii_uppercase + string.ascii_lowercase
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _is_text_stream_event(event: AgentEvent) -> bool:
    return isinstance(event, (TextDelta, ThinkingDelta))


def _assistant_message_for_turn(messages: list[dict[str, Any]], user_message_id: str) -> dict[str, Any] | None:
    for message in messages:
        if not isinstance(message, dict):
            raise TypeError("message must be a dict")
        info = message.get("info")
        if not isinstance(info, dict):
            raise TypeError("info must be a dict")
        if info.get("role") == "assistant" and info.get("parentID") == user_message_id:
            return message
    return None


def _joined_part_text(parts: list[Any], part_type: str) -> str | None:
    values: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            raise TypeError("part must be a dict")
        if part.get("type") != part_type:
            continue
        text = part.get("text")
        if not isinstance(text, str):
            raise TypeError("part text must be a string")
        values.append(text)
    if not values:
        return None
    return "".join(values)


def _remaining_suffix(*, current: str, snapshot: str) -> str:
    if snapshot.startswith(current):
        return snapshot[len(current):]
    logger.warning("OpenCode assistant snapshot did not extend streamed text")
    return ""


def _raw_event_summary(raw: dict[str, Any]) -> dict[str, Any]:
    properties = raw.get("properties")
    if not isinstance(properties, dict):
        return {"type": raw.get("type")}
    part = properties.get("part")
    part_type = part.get("type") if isinstance(part, dict) else None
    delta = properties.get("delta")
    return {
        "type": raw.get("type"),
        "session_id": properties.get("sessionID") or (part.get("sessionID") if isinstance(part, dict) else None),
        "message_id": properties.get("messageID") or (part.get("messageID") if isinstance(part, dict) else None),
        "part_type": part_type,
        "field": properties.get("field"),
        "delta_len": len(delta) if isinstance(delta, str) else None,
    }


def _unknown_event_details(raw: dict[str, Any], active_turn_match: str) -> dict[str, Any]:
    properties = raw.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    part = properties.get("part")
    return {
        "event_type": raw.get("type"),
        "session_id": _event_session_id(properties),
        "message_id": _event_message_id(properties),
        "part_id": _event_part_id(properties),
        "part_type": part.get("type") if isinstance(part, dict) else properties.get("partType"),
        "active_turn_match": active_turn_match,
    }


def _event_session_id(properties: dict[str, Any]) -> Any:
    part = properties.get("part")
    if isinstance(part, dict) and part.get("sessionID") is not None:
        return part.get("sessionID")
    return properties.get("sessionID")


def _event_message_id(properties: dict[str, Any]) -> Any:
    part = properties.get("part")
    if isinstance(part, dict) and part.get("messageID") is not None:
        return part.get("messageID")
    tool = properties.get("tool")
    if isinstance(tool, dict) and tool.get("messageID") is not None:
        return tool.get("messageID")
    return properties.get("messageID")


def _event_part_id(properties: dict[str, Any]) -> Any:
    part = properties.get("part")
    if isinstance(part, dict) and part.get("id") is not None:
        return part.get("id")
    return properties.get("partID")


def _is_interactive_unknown_event(raw: dict[str, Any]) -> bool:
    event_type = raw.get("type")
    if not isinstance(event_type, str):
        return False
    parts = event_type.lower().replace("-", ".").replace("_", ".").split(".")
    return any(part in {"question", "permission", "input", "request", "requested", "asked"} for part in parts)


def _is_known_ignored_event(raw: dict[str, Any]) -> bool:
    return raw.get("type") in {
        "message.part.delta",
        "message.part.updated",
        "session.status",
    }


def _required_active_session_id(raw: dict[str, Any]) -> str:
    properties = raw.get("properties")
    if not isinstance(properties, dict):
        raise TypeError("properties must be a dict")
    session_id = _event_session_id(properties)
    if not isinstance(session_id, str):
        raise TypeError("sessionID must be a string")
    return session_id


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value

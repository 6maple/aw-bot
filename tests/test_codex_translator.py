import asyncio
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from c_auto_bridge.agent.codex_app_server import CodexAppServerAdapter, CodexEventRouter
from c_auto_bridge.agent.codex_jsonrpc import JsonRpcError
from c_auto_bridge.agent.codex_translator import translate_codex_event
from c_auto_bridge.config_codex import CodexConfig, load_codex_config
from c_auto_bridge.core.agent_events import (
    ApprovalRequested,
    RunCompleted,
    RunFailed,
    RunInterrupted,
    RunTimedOut,
    TextDelta,
    ThinkingDelta,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
    UserInputRequested,
)
from c_auto_bridge.core.agent_session import Workspace
from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.core.run_view import PendingRequestView, RunView
from c_auto_bridge.core.use_cases import CoreUseCases, PrivateChatTextMessage, RunViewAction, SkillInfo
from c_auto_bridge.core.workspace import WorkspaceValidator
from c_auto_bridge.ports.agent import AgentThreadNotFound
from c_auto_bridge.store.file_store import FileStore


class CodexTranslatorTest(unittest.TestCase):
    def test_translates_generated_protocol_shapes(self) -> None:
        fixtures = [
            (_notification("item/agentMessage/delta", delta="hi", itemId="i"), TextDelta("hi")),
            (_notification("item/reasoning/summaryTextDelta", delta="hmm", itemId="i", summaryIndex=0), ThinkingDelta("hmm")),
            (_notification("item/started", item={"id": "t", "type": "commandExecution", "command": "git status"}), ToolStarted("t", "command", {"command": "git status"})),
            (_notification("item/completed", item={"id": "t", "type": "commandExecution", "status": "completed", "aggregatedOutput": "ok"}), ToolFinished("t", "ok", False)),
            (_request(7, "item/tool/requestUserInput", itemId="i", questions=[{"id": "q", "header": "Path", "question": "Which path?"}]), UserInputRequested("7", "Which path?", _request(7, "item/tool/requestUserInput", itemId="i", questions=[{"id": "q", "header": "Path", "question": "Which path?"}])["params"])),
            (_request(8, "item/commandExecution/requestApproval", itemId="i", startedAtMs=1, command="git status"), ApprovalRequested("8", "git status", _request(8, "item/commandExecution/requestApproval", itemId="i", startedAtMs=1, command="git status")["params"])),
            (_request(9, "item/permissions/requestApproval", itemId="i", startedAtMs=1, reason="Need network"), ApprovalRequested("9", "Need network", _request(9, "item/permissions/requestApproval", itemId="i", startedAtMs=1, reason="Need network")["params"])),
            (_notification("thread/tokenUsage/updated", tokenUsage={"last": {"inputTokens": 3, "outputTokens": 2}, "total": {}}), UsageUpdated(3, 2)),
            (_notification("turn/completed", turn={"id": "turn", "items": [], "status": "completed"}), RunCompleted()),
            (_notification("turn/completed", turn={"id": "turn", "items": [], "status": "interrupted"}), RunInterrupted()),
            (_notification("turn/completed", turn={"id": "turn", "items": [], "status": "timed_out"}), RunTimedOut()),
            (_notification("turn/completed", turn={"id": "turn", "items": [], "status": "failed", "error": {"message": "boom"}}), RunFailed("boom")),
        ]
        for raw, expected in fixtures:
            with self.subTest(method=raw["method"]):
                self.assertEqual(translate_codex_event(raw).event, expected)

    def test_turn_completed_can_use_nested_turn_id_without_top_level_turn_id(self) -> None:
        raw = {
            "method": "turn/completed",
            "params": {
                "threadId": "thread",
                "turn": {"id": "turn", "items": [], "status": "completed"},
            },
        }

        translated = translate_codex_event(raw)

        self.assertEqual(translated.turn_id, "turn")
        self.assertEqual(translated.thread_id, "thread")
        self.assertEqual(translated.event, RunCompleted())

    def test_token_usage_without_routing_ids_does_not_crash_translator(self) -> None:
        raw = {
            "method": "thread/tokenUsage/updated",
            "params": {
                "tokenUsage": {
                    "last": {"inputTokens": 3, "outputTokens": 2},
                    "total": {},
                },
            },
        }

        translated = translate_codex_event(raw)

        self.assertIsNone(translated.turn_id)
        self.assertIsNone(translated.thread_id)
        self.assertEqual(translated.event, UsageUpdated(3, 2))

    def test_router_routes_and_responds_to_server_requests(self) -> None:
        async def run() -> None:
            router = CodexEventRouter()
            await router.handle_event(_notification("item/agentMessage/delta", delta="early", itemId="i"))
            with TemporaryDirectory() as tmpdir:
                rpc = FakeRpc()
                adapter = CodexAppServerAdapter(config=_config(), store=FileStore(tmpdir), rpc=rpc, event_router=router)
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix it", model="test-model-next")
                self.assertEqual(await anext(agent_run.events), TextDelta("early"))

                await router.handle_event(_request(7, "item/tool/requestUserInput", itemId="i", questions=[{"id": "q", "header": "Path", "question": "Which path?"}]))
                self.assertIsInstance(await anext(agent_run.events), UserInputRequested)
                await agent_run.answer_user_input("src")

                await router.handle_event(_request(8, "item/fileChange/requestApproval", itemId="i", startedAtMs=1, reason="Write file"))
                self.assertIsInstance(await anext(agent_run.events), ApprovalRequested)
                await agent_run.answer_approval("8", "deny")

            self.assertEqual([call[0] for call in rpc.calls], ["turn/start", "respond", "respond"])
            self.assertEqual(
                rpc.calls[0][1]["input"],
                [{"type": "text", "text": "fix it"}],
            )
            self.assertEqual(rpc.calls[0][1]["model"], "test-model-next")
            self.assertEqual(rpc.calls[1], ("respond", 7, {"answers": {"q": {"answers": ["src"]}}}))
            self.assertEqual(rpc.calls[2], ("respond", 8, {"decision": "decline"}))

        asyncio.run(run())

    def test_permissions_approval_acceptance_responds_and_continues_current_turn(self) -> None:
        async def run() -> None:
            router = CodexEventRouter()
            with TemporaryDirectory() as tmpdir:
                rpc = ContinuingApprovalRpc(router=router)
                adapter = CodexAppServerAdapter(config=_default_config(), store=FileStore(tmpdir), rpc=rpc, event_router=router)
                persistence = FakeRunPersistence()
                run_view_sink = FakeRunViewSink()
                use_cases = CoreUseCases(
                    agent=adapter,
                    persistence=persistence,
                    run_view_sink=run_view_sink,
                    workspace=Workspace(path="D:/repo"),
                    workspace_validator=WorkspaceValidator(
                        home_directory="D:/Users/Maple",
                        temp_directory="D:/Temp",
                        system_directories=(),
                    ),
                    access_mode="workspace",
                    agent_name="codex",
                    clock=lambda: __import__("datetime").datetime(2026, 6, 6),
                    run_id_factory=lambda now: "run_1",
                )

                pending_task = asyncio.create_task(
                    use_cases.handle_private_chat_text(
                        PrivateChatTextMessage(
                            private_chat_scope_id="chat_1",
                            user_id="user_1",
                            text="install dependency",
                        )
                    )
                )
                await rpc.wait_for_turn_start()
                await router.handle_event(
                    _request(9, "item/permissions/requestApproval", itemId="i", startedAtMs=1, reason="Need network")
                )

                first_run = await asyncio.wait_for(pending_task, timeout=1)
                self.assertEqual(first_run.status, "pending_approval")
                self.assertEqual(run_view_sink.views[-1].status, "pending_approval")
                self.assertEqual(run_view_sink.views[-1].pending.pending_request_id, "9")
                self.assertEqual(run_view_sink.views[-1].pending.prompt, "Need network")

                resumed_run = await use_cases.handle_run_view_action(
                    RunViewAction(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        action="allow",
                        pending_request_id="9",
                    )
                )

            self.assertEqual(resumed_run.status, "completed")
            self.assertEqual(persistence.closed_pending_requests, [("9", "resolved")])
            self.assertEqual(run_view_sink.views[-1].pending, None)
            self.assertEqual(run_view_sink.views[-1].text, "approved")
            self.assertEqual(rpc.calls[-1], ("respond", 9, {"decision": "accept"}))

        asyncio.run(run())

    def test_new_declines_pending_codex_approval_without_turn_interrupt(self) -> None:
        async def run() -> None:
            router = CodexEventRouter()
            with TemporaryDirectory() as tmpdir:
                rpc = ContinuingApprovalRpc(router=router)
                adapter = CodexAppServerAdapter(config=_default_config(), store=FileStore(tmpdir), rpc=rpc, event_router=router)
                persistence = FakeRunPersistence()
                use_cases = CoreUseCases(
                    agent=adapter,
                    persistence=persistence,
                    run_view_sink=FakeRunViewSink(),
                    workspace=Workspace(path="D:/repo"),
                    workspace_validator=WorkspaceValidator(
                        home_directory="D:/Users/Maple",
                        temp_directory="D:/Temp",
                        system_directories=(),
                    ),
                    access_mode="workspace",
                    agent_name="codex",
                    clock=lambda: datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc),
                    run_id_factory=RunIdFactory(),
                )

                pending_task = asyncio.create_task(
                    use_cases.handle_private_chat_text(
                        PrivateChatTextMessage(
                            private_chat_scope_id="chat_1",
                            user_id="user_1",
                            text="install dependency",
                        )
                    )
                )
                await rpc.wait_for_turn_start()
                await router.handle_event(
                    _request(9, "item/permissions/requestApproval", itemId="i", startedAtMs=1, reason="Need network")
                )
                first_run = await asyncio.wait_for(pending_task, timeout=1)

                reset_run = await use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="/new",
                    )
                )

            self.assertEqual(first_run.status, "pending_approval")
            self.assertEqual(reset_run.status, "completed")
            self.assertIn(("respond", 9, {"decision": "decline"}), rpc.calls)
            self.assertNotIn("turn/interrupt", [call[0] for call in rpc.calls])
            self.assertEqual(persistence.closed_pending_requests, [("9", "resolved")])

        asyncio.run(run())

    def test_approval_decisions_map_accept_and_reject_synonyms_and_reject_unknown(self) -> None:
        async def run() -> None:
            for decision in ("approve", "accept", "allow"):
                with self.subTest(decision=decision):
                    router = CodexEventRouter()
                    with TemporaryDirectory() as tmpdir:
                        rpc = FakeRpc()
                        adapter = CodexAppServerAdapter(config=_default_config(), store=FileStore(tmpdir), rpc=rpc, event_router=router)
                        agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")
                        await router.handle_event(_request(9, "item/permissions/requestApproval", itemId="i", startedAtMs=1, reason="Need network"))
                        await anext(agent_run.events)
                        await agent_run.answer_approval("9", decision)
                        self.assertEqual(rpc.calls[-1], ("respond", 9, {"decision": "accept"}))

            for decision in ("reject", "deny", "abort", "decline", "cancel"):
                with self.subTest(decision=decision):
                    router = CodexEventRouter()
                    with TemporaryDirectory() as tmpdir:
                        rpc = FakeRpc()
                        adapter = CodexAppServerAdapter(config=_default_config(), store=FileStore(tmpdir), rpc=rpc, event_router=router)
                        agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")
                        await router.handle_event(_request(9, "item/permissions/requestApproval", itemId="i", startedAtMs=1, reason="Need network"))
                        await anext(agent_run.events)
                        await agent_run.answer_approval("9", decision)
                        self.assertEqual(rpc.calls[-1], ("respond", 9, {"decision": "decline"}))

            router = CodexEventRouter()
            with TemporaryDirectory() as tmpdir:
                rpc = FakeRpc()
                adapter = CodexAppServerAdapter(config=_default_config(), store=FileStore(tmpdir), rpc=rpc, event_router=router)
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix")
                await router.handle_event(_request(9, "item/permissions/requestApproval", itemId="i", startedAtMs=1, reason="Need network"))
                await anext(agent_run.events)
                with self.assertRaisesRegex(ValueError, "unsupported Codex approval decision: remember"):
                    await agent_run.answer_approval("9", "remember")
                self.assertEqual([call for call in rpc.calls if call[0] == "respond"], [])
                await agent_run.answer_approval("9", "accept")
                self.assertEqual(rpc.calls[-1], ("respond", 9, {"decision": "accept"}))

        asyncio.run(run())

    def test_create_and_reuse_session_on_new_agent_port(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                rpc = FakeRpc(thread_id="thread_1")
                store = FileStore(tmpdir)
                adapter = CodexAppServerAdapter(config=_config(), store=store, rpc=rpc)

                created = await adapter.create_session(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    agent_name="codex",
                    workspace=Workspace(path="D:/repo"),
                    access_mode="workspace",
                )
                reused = await adapter.get_or_create_session(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    agent_name="codex",
                    workspace=Workspace(path="D:/repo"),
                    access_mode="workspace",
                )

                self.assertEqual(created, reused)
                self.assertEqual(created.agent_session_id, "thread_1")
                self.assertEqual(store.get_current_session("user_1").bot_session_id, "thread_1")
                self.assertEqual([call[0] for call in rpc.calls], ["thread/start"])

        asyncio.run(run())

    def test_codex_model_options_use_codex_models_or_configured_model(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "CODEX_HOME": "C:/Users/Maple/.codex",
                "CODEX_WORKSPACE": "D:/repo",
                "CODEX_MODEL": "test-model",
                "CODEX_MODELS": "test-model,test-model-next",
                "CODEX_SANDBOX": "workspace-write",
                "CODEX_APPROVAL_POLICY": "on-request",
            },
            clear=True,
        ):
            explicit = load_codex_config()

        with patch.dict(
            "os.environ",
            {
                "CODEX_HOME": "C:/Users/Maple/.codex",
                "CODEX_WORKSPACE": "D:/repo",
                "CODEX_MODEL": "test-model",
                "CODEX_SANDBOX": "workspace-write",
                "CODEX_APPROVAL_POLICY": "on-request",
            },
            clear=True,
        ):
            fallback = load_codex_config()

        with TemporaryDirectory() as tmpdir:
            explicit_adapter = CodexAppServerAdapter(config=explicit, store=FileStore(tmpdir), rpc=FakeRpc())
            fallback_adapter = CodexAppServerAdapter(config=fallback, store=FileStore(tmpdir), rpc=FakeRpc())

            async def run() -> None:
                self.assertEqual(
                    await explicit_adapter.list_models(workspace=Workspace(path="D:/repo")),
                    ("test-model", "test-model-next"),
                )
                self.assertEqual(
                    await fallback_adapter.list_models(workspace=Workspace(path="D:/repo")),
                    ("test-model",),
                )

            asyncio.run(run())

    def test_codex_skills_come_from_app_server_skills_api(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                rpc = FakeRpc()
                rpc.skills = {
                    "skills": [
                        {"name": "c-tdd", "description": "Test-driven development"},
                        {"name": "c-review"},
                    ]
                }
                adapter = CodexAppServerAdapter(config=_config(), store=FileStore(tmpdir), rpc=rpc)

                self.assertEqual(
                    await adapter.list_skills(workspace=Workspace(path="D:/repo")),
                    (
                        SkillInfo(name="c-tdd", description="Test-driven development"),
                        SkillInfo(name="c-review", description=None),
                    ),
                )
                self.assertEqual(rpc.calls, [("skill/list", {"cwd": "D:/repo"})])

        asyncio.run(run())

    def test_omits_optional_model_and_approval_overrides_when_unset(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                rpc = FakeRpc(thread_id="thread_1")
                adapter = CodexAppServerAdapter(config=_default_config(), store=FileStore(tmpdir), rpc=rpc)

                session = await adapter.create_session(
                    private_chat_scope_id="chat_1",
                    user_id="user_1",
                    agent_name="codex",
                    workspace=Workspace(path="D:/repo"),
                    access_mode="workspace",
                )
                await adapter.start_turn(agent_session=session, prompt="fix it")

            thread_payload = rpc.calls[0][1]
            turn_payload = rpc.calls[1][1]
            self.assertNotIn("model", thread_payload)
            self.assertNotIn("approvalPolicy", thread_payload)
            self.assertNotIn("model", turn_payload)
            self.assertNotIn("approvalPolicy", turn_payload)
            self.assertEqual(thread_payload["cwd"], "D:/repo")
            self.assertEqual(turn_payload["threadId"], "thread_1")
            self.assertEqual(turn_payload["cwd"], "D:/repo")
            self.assertEqual(turn_payload["input"], [{"type": "text", "text": "fix it"}])
            self.assertEqual(thread_payload["sandbox"], "workspace-write")
            self.assertEqual(
                turn_payload["sandboxPolicy"],
                {
                    "type": "workspaceWrite",
                    "writableRoots": ["D:/repo"],
                    "networkAccess": False,
                },
            )

        asyncio.run(run())

    def test_start_turn_maps_provider_neutral_attachments_to_codex_input_items(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                rpc = FakeRpc(thread_id="thread_1")
                adapter = CodexAppServerAdapter(config=_default_config(), store=FileStore(tmpdir), rpc=rpc)

                await adapter.start_turn(
                    agent_session=_session(),
                    prompt="review",
                    attachments=(
                        Attachment(kind="image", path="D:/cache/diagram.png", name="diagram.png"),
                        Attachment(kind="file", path="D:/cache/notes.txt", name="notes.txt"),
                    ),
                )
                await adapter.start_turn(
                    agent_session=_session(),
                    prompt="",
                    attachments=(Attachment(kind="image", path="D:/cache/only.png", name="only.png"),),
                )

            self.assertEqual(
                rpc.calls[0][1]["input"],
                [
                    {"type": "text", "text": "review"},
                    {"type": "localImage", "path": "D:/cache/diagram.png"},
                    {"type": "mention", "path": "D:/cache/notes.txt"},
                ],
            )
            self.assertEqual(
                rpc.calls[1][1]["input"],
                [{"type": "localImage", "path": "D:/cache/only.png"}],
            )

        asyncio.run(run())

    def test_thread_not_found_rpc_error_maps_to_agent_session_recovery_signal(self) -> None:
        async def run() -> None:
            with TemporaryDirectory() as tmpdir:
                rpc = FakeThreadNotFoundRpc()
                adapter = CodexAppServerAdapter(config=_default_config(), store=FileStore(tmpdir), rpc=rpc)

                with self.assertRaises(AgentThreadNotFound):
                    await adapter.start_turn(agent_session=_session(), prompt="fix it")

            self.assertEqual(
                rpc.calls,
                [
                    (
                        "turn/start",
                        {
                            "threadId": "thread",
                            "cwd": "D:/repo",
                            "input": [{"type": "text", "text": "fix it"}],
                            "sandboxPolicy": {
                                "type": "workspaceWrite",
                                "writableRoots": ["D:/repo"],
                                "networkAccess": False,
                            },
                        },
                    )
                ],
            )

        asyncio.run(run())

    def test_queued_attachments_flow_into_next_codex_turn_payload(self) -> None:
        async def run() -> None:
            router = CodexEventRouter()
            with TemporaryDirectory() as tmpdir:
                rpc = QueuedTurnRpc()
                adapter = CodexAppServerAdapter(config=_default_config(), store=FileStore(tmpdir), rpc=rpc, event_router=router)
                persistence = FakeRunPersistence()
                run_view_sink = FakeRunViewSink()
                use_cases = CoreUseCases(
                    agent=adapter,
                    persistence=persistence,
                    run_view_sink=run_view_sink,
                    workspace=Workspace(path="D:/repo"),
                    workspace_validator=WorkspaceValidator(
                        home_directory="D:/Users/Maple",
                        temp_directory="D:/Temp",
                        system_directories=(),
                    ),
                    access_mode="workspace",
                    agent_name="codex",
                    clock=lambda: datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc),
                    run_id_factory=RunIdFactory(),
                )

                run_task = asyncio.create_task(
                    use_cases.handle_private_chat_text(
                        PrivateChatTextMessage(
                            private_chat_scope_id="chat_1",
                            user_id="user_1",
                            text="first",
                        )
                    )
                )
                await rpc.wait_for_turn_count(1)

                await use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="queued text",
                        attachments=(Attachment(kind="image", path="D:/cache/queued.png", name="queued.png"),),
                    )
                )
                await use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id="chat_1",
                        user_id="user_1",
                        text="",
                        attachments=(Attachment(kind="file", path="D:/cache/queued.txt", name="queued.txt"),),
                    )
                )

                await router.handle_event(_turn_completed("turn_1"))
                await rpc.wait_for_turn_count(2)
                await router.handle_event(_turn_completed("turn_2"))
                final_run = await asyncio.wait_for(run_task, timeout=1)

            self.assertEqual(final_run.status, "completed")
            self.assertEqual(
                [call[1]["input"] for call in rpc.calls if call[0] == "turn/start"],
                [
                    [{"type": "text", "text": "first"}],
                    [
                        {"type": "text", "text": "queued text"},
                        {"type": "localImage", "path": "D:/cache/queued.png"},
                        {"type": "mention", "path": "D:/cache/queued.txt"},
                    ],
                ],
            )

        asyncio.run(run())


class FakeRpc:
    def __init__(self, thread_id: str = "thread"):
        self.calls = []
        self.thread_id = thread_id
        self.skills = {"skills": []}

    async def request(self, method, params):
        self.calls.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": self.thread_id}}
        if method == "skill/list":
            return self.skills
        return {"turn": {"id": "turn"}}

    async def respond(self, request_id, result):
        self.calls.append(("respond", request_id, result))


class FakeThreadNotFoundRpc:
    def __init__(self) -> None:
        self.calls = []

    async def request(self, method, params):
        self.calls.append((method, params))
        raise JsonRpcError({"message": "thread not found: thread"})

    async def respond(self, request_id, result):
        raise AssertionError("thread-not-found flow should not respond")


class ContinuingApprovalRpc(FakeRpc):
    def __init__(self, *, router: CodexEventRouter) -> None:
        super().__init__(thread_id="thread")
        self.router = router
        self._turn_started = asyncio.Event()

    async def request(self, method, params):
        result = await super().request(method, params)
        if method == "turn/start":
            self._turn_started.set()
        return result

    async def respond(self, request_id, result):
        await super().respond(request_id, result)
        await self.router.handle_event(_notification("item/agentMessage/delta", delta="approved", itemId="i"))
        await self.router.handle_event(_notification("turn/completed", turn={"id": "turn", "items": [], "status": "completed"}))

    async def wait_for_turn_start(self) -> None:
        await asyncio.wait_for(self._turn_started.wait(), timeout=1)


class QueuedTurnRpc(FakeRpc):
    def __init__(self) -> None:
        super().__init__(thread_id="thread")
        self._turn_started = asyncio.Condition()
        self._turn_count = 0

    async def request(self, method, params):
        if method == "turn/start":
            self.calls.append((method, params))
            async with self._turn_started:
                self._turn_count += 1
                self._turn_started.notify_all()
                return {"turn": {"id": f"turn_{self._turn_count}"}}
        return await super().request(method, params)

    async def wait_for_turn_count(self, count: int) -> None:
        async with self._turn_started:
            await asyncio.wait_for(self._turn_started.wait_for(lambda: self._turn_count >= count), timeout=1)


class RunIdFactory:
    def __init__(self) -> None:
        self._value = 0

    def __call__(self, now: datetime) -> str:
        self._value += 1
        return f"run_{self._value}"


class FakeRunPersistence:
    def __init__(self) -> None:
        self.closed_pending_requests: list[tuple[str, str]] = []

    async def record_run_created(self, run) -> None:
        pass

    async def record_run_event(self, *, run_id: str, event) -> None:
        pass

    async def record_run_terminal_status(self, *, run_id: str, status: str, updated_at: str) -> None:
        pass

    async def open_pending_request(self, *, run_id: str, pending_request: PendingRequestView) -> None:
        pass

    async def close_pending_request(self, *, pending_request_id: str, status: str) -> None:
        self.closed_pending_requests.append((pending_request_id, status))

    async def clear_current_session(self, *, private_chat_scope_id: str) -> None:
        pass

    async def save_agent_session(self, *, agent_session) -> None:
        pass

    async def list_agent_sessions(self, *, private_chat_scope_id: str, user_id: str) -> list:
        return []

    async def list_named_workspaces(self) -> list:
        return []


class FakeRunViewSink:
    def __init__(self) -> None:
        self.views: list[RunView] = []

    async def publish(self, *, private_chat_scope_id: str, run_view: RunView) -> None:
        self.views.append(run_view)


def _notification(method, **params):
    return {"method": method, "params": {"threadId": "thread", "turnId": "turn", **params}}


def _request(request_id, method, **params):
    return {"id": request_id, **_notification(method, **params)}


def _turn_completed(turn_id: str):
    return {
        "method": "turn/completed",
        "params": {
            "threadId": "thread",
            "turnId": turn_id,
            "turn": {"id": turn_id, "items": [], "status": "completed"},
        },
    }


def _config() -> CodexConfig:
    return CodexConfig(
        None,
        None,
        "C:/Users/Maple/.codex",
        "D:/repo",
        "D:/repo/.claude/skills/c-auto/SKILL.md",
        "test-model",
        ("test-model",),
        "workspace-write",
        "on-request",
    )


def _default_config() -> CodexConfig:
    return CodexConfig(
        app_server_url=None,
        cli_path=None,
        home=None,
        workspace="D:/repo",
        c_auto_skill_path=None,
        model=None,
        models=(),
        sandbox="workspace-write",
        approval_policy=None,
    )


def _session():
    from c_auto_bridge.core.agent_session import AgentSession

    return AgentSession("thread", "chat", "u", "codex", Workspace(path="D:/repo"), "workspace")


if __name__ == "__main__":
    unittest.main()

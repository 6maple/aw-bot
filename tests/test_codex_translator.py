import asyncio
from tempfile import TemporaryDirectory
import unittest

from c_auto_bridge.agent.codex_app_server import CodexAppServerAdapter, CodexEventRouter
from c_auto_bridge.agent.codex_translator import translate_codex_event
from c_auto_bridge.config_codex import CodexConfig
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
            (_notification("thread/tokenUsage/updated", tokenUsage={"last": {"inputTokens": 3, "outputTokens": 2}, "total": {}}), UsageUpdated(3, 2)),
            (_notification("turn/completed", turn={"id": "turn", "items": [], "status": "completed"}), RunCompleted()),
            (_notification("turn/completed", turn={"id": "turn", "items": [], "status": "interrupted"}), RunInterrupted()),
            (_notification("turn/completed", turn={"id": "turn", "items": [], "status": "timed_out"}), RunTimedOut()),
            (_notification("turn/completed", turn={"id": "turn", "items": [], "status": "failed", "error": {"message": "boom"}}), RunFailed("boom")),
        ]
        for raw, expected in fixtures:
            with self.subTest(method=raw["method"]):
                self.assertEqual(translate_codex_event(raw).event, expected)

    def test_router_routes_and_responds_to_server_requests(self) -> None:
        async def run() -> None:
            router = CodexEventRouter()
            await router.handle_event(_notification("item/agentMessage/delta", delta="early", itemId="i"))
            with TemporaryDirectory() as tmpdir:
                rpc = FakeRpc()
                adapter = CodexAppServerAdapter(config=_config(), store=FileStore(tmpdir), rpc=rpc, event_router=router)
                agent_run = await adapter.start_turn(agent_session=_session(), prompt="fix it")
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
            self.assertEqual(rpc.calls[1], ("respond", 7, {"answers": {"q": {"answers": ["src"]}}}))
            self.assertEqual(rpc.calls[2], ("respond", 8, {"decision": "decline"}))

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


class FakeRpc:
    def __init__(self, thread_id: str = "thread"):
        self.calls = []
        self.thread_id = thread_id

    async def request(self, method, params):
        self.calls.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": self.thread_id}}
        return {"turn": {"id": "turn"}}

    async def respond(self, request_id, result):
        self.calls.append(("respond", request_id, result))


def _notification(method, **params):
    return {"method": method, "params": {"threadId": "thread", "turnId": "turn", **params}}


def _request(request_id, method, **params):
    return {"id": request_id, **_notification(method, **params)}


def _config() -> CodexConfig:
    return CodexConfig(None, None, "C:/Users/Maple/.codex", "D:/repo", "D:/repo/.claude/skills/c-auto/SKILL.md", "test-model", "workspace-write", "on-request")


def _session():
    from c_auto_bridge.core.agent_session import AgentSession

    return AgentSession("thread", "chat", "u", "codex", Workspace(path="D:/repo"), "workspace")


if __name__ == "__main__":
    unittest.main()

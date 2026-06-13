import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from c_auto_bridge.app.runtime import _listen, build_runtime
from c_auto_bridge.agent.codex_stdio import CodexStdioClient
from c_auto_bridge.agent.codex_websocket import CodexWebSocketClient
from c_auto_bridge.config import Config
from c_auto_bridge.config_codex import CodexConfig
from c_auto_bridge.config_opencode import OpenCodeConfig
from c_auto_bridge.feishu.attachment_intake import DownloadedAttachment
from c_auto_bridge.feishu.message import IncomingAttachment, IncomingMessage
from c_auto_bridge.core.agent_session import Workspace
from c_auto_bridge.feishu.gateway import IncomingCardAction
from c_auto_bridge.feishu.message import IncomingMenuEvent
from c_auto_bridge.feishu.private_chat_adapter import FeishuPrivateChatAdapter
from c_auto_bridge.store.file_run_persistence import FileRunPersistence
from c_auto_bridge.store.file_store import FileStore


class AppRuntimeTest(unittest.TestCase):
    def test_build_runtime_wires_codex_core_runtime(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            codex_home = Path(tmpdir) / "codex-home"
            workspace.mkdir()
            codex_home.mkdir()

            components = build_runtime(
                Config(data_dir=str(Path(tmpdir) / "data"), default_agent="codex"),
                app_id="app_id",
                app_secret="app_secret",
                rpc_factory=lambda **kwargs: FakeCodexRpc(kwargs=kwargs),
                codex_config_factory=lambda: CodexConfig(
                    app_server_url=None,
                    cli_path="codex",
                    home=str(codex_home),
                    workspace=str(workspace),
                    c_auto_skill_path=None,
                    model="test-model",
                    models=("test-model",),
                    sandbox="workspace-write",
                    approval_policy="on-request",
                ),
                gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
            )

            self.assertIsInstance(components.persistence, FileRunPersistence)
            self.assertIsInstance(components.chat_adapter, FeishuPrivateChatAdapter)
            self.assertEqual(components.use_cases._run_controller.workspace.path, str(workspace.resolve()))
            self.assertEqual(components.rpc.kwargs, {"executable": "codex", "codex_home": str(codex_home)})

    def test_build_runtime_wires_gateway_as_attachment_downloader(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            gateway = FakeGatewayWithDownloads(
                downloads={
                    "img_1": DownloadedAttachment(file_name="diagram.png", content=b"png"),
                }
            )

            components = build_runtime(
                Config(data_dir=str(Path(tmpdir) / "data"), default_agent="codex"),
                app_id="app_id",
                app_secret="app_secret",
                rpc_factory=lambda **kwargs: FakeCodexRpc(kwargs=kwargs),
                codex_config_factory=lambda: CodexConfig(
                    app_server_url=None,
                    cli_path=None,
                    home=None,
                    workspace=str(workspace),
                    c_auto_skill_path=None,
                    model=None,
                    models=(),
                    sandbox="workspace-write",
                    approval_policy=None,
                ),
                gateway_factory=lambda *args, **kwargs: gateway,
            )

            asyncio.run(
                components.chat_adapter._attachment_intake.cache_attachments(
                    IncomingMessage(
                        message_id="om_1",
                        chat_id="chat_1",
                        chat_type="p2p",
                        user_id="user_1",
                        text="",
                        attachments=(
                            IncomingAttachment(kind="image", resource_key="img_1", file_name="diagram.png"),
                        ),
                    )
                )
            )

        self.assertEqual(gateway.download_calls, [("om_1", "image", "img_1")])

    def test_build_runtime_passes_recent_private_chat_scope_ids_to_gateway(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            data_dir = Path(tmpdir) / "data"
            workspace.mkdir()
            store = FileStore(data_dir)
            store.save_run(
                _run_ref(
                    run_id="run_1",
                    scope_id="chat_1",
                    updated_at="2026-06-05T10:00:00+08:00",
                )
            )

            components = build_runtime(
                Config(data_dir=str(data_dir), default_agent="codex"),
                app_id="app_id",
                app_secret="app_secret",
                rpc_factory=lambda **kwargs: FakeCodexRpc(kwargs=kwargs),
                codex_config_factory=lambda: CodexConfig(
                    app_server_url=None,
                    cli_path=None,
                    home=None,
                    workspace=str(workspace),
                    c_auto_skill_path=None,
                    model=None,
                    models=(),
                    sandbox="workspace-write",
                    approval_policy=None,
                ),
                gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
            )

        self.assertEqual(components.gateway.known_private_chat_ids, {"chat_1"})

    def test_build_runtime_uses_config_workspace_without_requiring_codex_overrides(self) -> None:
        with TemporaryDirectory() as tmpdir:
            components = build_runtime(
                Config(data_dir=str(Path(tmpdir) / "data"), default_agent="codex"),
                app_id="app_id",
                app_secret="app_secret",
                rpc_factory=lambda **kwargs: FakeCodexRpc(kwargs=kwargs),
                codex_config_factory=lambda: CodexConfig(
                    app_server_url=None,
                    cli_path=None,
                    home=None,
                    workspace=tmpdir,
                    c_auto_skill_path=None,
                    model=None,
                    models=(),
                    sandbox="workspace-write",
                    approval_policy=None,
                ),
                gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
            )

            self.assertEqual(components.use_cases._run_controller.workspace.path, str(Path(tmpdir).resolve()))
            self.assertEqual(components.rpc.kwargs, {"executable": None, "codex_home": None})

    def test_build_runtime_defaults_to_codex_stdio_client_when_websocket_url_is_unset(self) -> None:
        with TemporaryDirectory() as tmpdir:
            components = build_runtime(
                Config(data_dir=str(Path(tmpdir) / "data"), default_agent="codex"),
                app_id="app_id",
                app_secret="app_secret",
                codex_config_factory=lambda: CodexConfig(
                    app_server_url=None,
                    cli_path=None,
                    home=None,
                    workspace=tmpdir,
                    c_auto_skill_path=None,
                    model=None,
                    models=(),
                    sandbox="workspace-write",
                    approval_policy=None,
                ),
                gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
            )

            self.assertIsInstance(components.rpc, CodexStdioClient)
            self.assertIsNone(components.rpc.executable)
            self.assertIsNone(components.rpc.codex_home)

    def test_build_runtime_wires_menu_callback_to_chat_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            codex_home = Path(tmpdir) / "codex-home"
            workspace.mkdir()
            codex_home.mkdir()

            components = build_runtime(
                Config(data_dir=str(Path(tmpdir) / "data"), default_agent="codex"),
                app_id="app_id",
                app_secret="app_secret",
                rpc_factory=lambda **kwargs: FakeCodexRpc(),
                codex_config_factory=lambda: CodexConfig(
                    app_server_url=None,
                    cli_path="codex",
                    home=str(codex_home),
                    workspace=str(workspace),
                    c_auto_skill_path=None,
                    model="test-model",
                    models=("test-model",),
                    sandbox="workspace-write",
                    approval_policy="on-request",
                ),
                gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
                menu_card_transport_factory=lambda client: client,
            )

            components.async_runner.run(
                components.gateway.on_menu(
                    IncomingMenuEvent(
                        user_id="ou_1",
                        event_key="aw_bot_menu()",
                    )
                )
            )

            self.assertEqual(components.gateway.user_cards_sent, [("ou_1", "card_1")])
            self.assertEqual(components.gateway.cards_sent, [])
            self.assertNotIn("menu:agent:plan", _card_commands(components.gateway.cards_created[0]))
            self.assertNotIn("menu:agent:build", _card_commands(components.gateway.cards_created[0]))

    def test_build_runtime_shows_plan_build_menu_only_for_opencode(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            components = build_runtime(
                Config(data_dir=str(Path(tmpdir) / "data"), default_agent="opencode"),
                app_id="app_id",
                app_secret="app_secret",
                opencode_client_factory=lambda url: FakeOpenCodeClient(),
                opencode_config_factory=lambda: OpenCodeConfig(
                    server_url="http://127.0.0.1:4096",
                    workspace=str(workspace),
                    model=None,
                    agent=None,
                ),
                gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
                menu_card_transport_factory=lambda client: client,
            )

            components.async_runner.run(
                components.gateway.on_menu(
                    IncomingMenuEvent(
                        user_id="ou_1",
                        event_key="aw_bot_menu()",
                    )
                )
            )

            commands = _card_commands(components.gateway.cards_created[0])
            self.assertIn("menu:agent:plan", commands)
            self.assertIn("menu:agent:build", commands)

    def test_build_runtime_sends_card_actions_to_chat_not_user(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            codex_home = Path(tmpdir) / "codex-home"
            workspace.mkdir()
            codex_home.mkdir()

            components = build_runtime(
                Config(data_dir=str(Path(tmpdir) / "data"), default_agent="codex"),
                app_id="app_id",
                app_secret="app_secret",
                rpc_factory=lambda **kwargs: FakeCodexRpc(),
                codex_config_factory=lambda: CodexConfig(
                    app_server_url=None,
                    cli_path="codex",
                    home=str(codex_home),
                    workspace=str(workspace),
                    c_auto_skill_path=None,
                    model="test-model",
                    models=("test-model",),
                    sandbox="workspace-write",
                    approval_policy="on-request",
                ),
                gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
                menu_card_transport_factory=lambda client: client,
            )

            components.async_runner.run(
                components.gateway.on_card_action(
                    IncomingCardAction(
                        chat_id="oc_1",
                        user_id="ou_1",
                        value={"cmd": "menu:help"},
                    )
                )
            )

            self.assertEqual(components.gateway.cards_sent, [("oc_1", "card_1")])
            self.assertEqual(components.gateway.user_cards_sent, [])

    def test_build_runtime_uses_codex_websocket_when_url_is_configured(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            codex_home = Path(tmpdir) / "codex-home"
            workspace.mkdir()
            codex_home.mkdir()

            def fail_stdio_factory(**kwargs):
                raise AssertionError("stdio app-server should not be started")

            components = build_runtime(
                Config(data_dir=str(Path(tmpdir) / "data"), default_agent="codex"),
                app_id="app_id",
                app_secret="app_secret",
                rpc_factory=fail_stdio_factory,
                codex_config_factory=lambda: CodexConfig(
                    app_server_url="ws://127.0.0.1:4500",
                    cli_path="codex",
                    home=None,
                    workspace=str(workspace),
                    c_auto_skill_path=None,
                    model=None,
                    models=(),
                    sandbox="workspace-write",
                    approval_policy=None,
                ),
                gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
            )

            self.assertIsInstance(components.rpc, CodexWebSocketClient)
            self.assertEqual(components.rpc.url, "ws://127.0.0.1:4500")
            self.assertIsNone(components.rpc.codex_home)

    def test_build_runtime_wires_opencode_core_runtime(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            components = build_runtime(
                Config(data_dir=str(Path(tmpdir) / "data"), default_agent="opencode"),
                app_id="app_id",
                app_secret="app_secret",
                opencode_client_factory=lambda url: FakeOpenCodeClient(),
                opencode_config_factory=lambda: OpenCodeConfig(
                    server_url="http://127.0.0.1:4096",
                    workspace=str(workspace),
                    model=None,
                    agent=None,
                ),
                gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
            )

            self.assertIsInstance(components.persistence, FileRunPersistence)
            self.assertIsInstance(components.chat_adapter, FeishuPrivateChatAdapter)
            self.assertEqual(components.use_cases._run_controller.workspace.path, str(workspace.resolve()))

    def test_build_runtime_fails_when_opencode_startup_capability_is_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            with self.assertRaisesRegex(RuntimeError, "OpenCode required capability is missing: prompt async"):
                build_runtime(
                    Config(data_dir=str(Path(tmpdir) / "data"), default_agent="opencode"),
                    app_id="app_id",
                    app_secret="app_secret",
                    opencode_client_factory=lambda url: MissingPromptOpenCodeClient(),
                    opencode_config_factory=lambda: OpenCodeConfig(
                        server_url="http://127.0.0.1:4096",
                        workspace=str(workspace),
                        model=None,
                        agent=None,
                    ),
                    gateway_factory=lambda *args, **kwargs: FakeGateway(*args, **kwargs),
                )

    def test_opencode_listener_reports_ended_event_stream(self) -> None:
        async def run() -> None:
            client = FakeOpenCodeClient()
            router = FakeOpenCodeEventRouter()

            await _listen("opencode", None, client, router, workspace=Workspace(path="D:/repo"))

            self.assertEqual(router.interruptions, ["OpenCode event stream ended"])
            self.assertEqual(client.events_workspace, "D:/repo")

        asyncio.run(run())

    def test_opencode_listener_reports_raised_event_stream_and_reraises(self) -> None:
        async def run() -> None:
            client = FakeOpenCodeClient(event_error=RuntimeError("socket closed"))
            router = FakeOpenCodeEventRouter()

            with self.assertRaisesRegex(RuntimeError, "socket closed"):
                await _listen("opencode", None, client, router, workspace=Workspace(path="D:/repo"))

            self.assertEqual(router.interruptions, ["socket closed"])
            self.assertEqual(client.events_workspace, "D:/repo")

        asyncio.run(run())


class FakeGateway:
    def __init__(
        self,
        app_id,
        app_secret,
        *,
        on_message,
        on_menu,
        on_card_action,
        submit,
        known_private_chat_ids=None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.on_message = on_message
        self.on_menu = on_menu
        self.on_card_action = on_card_action
        self.submit = submit
        self.client = self
        self.cards_created = []
        self.cards_sent = []
        self.user_cards_sent = []
        self.known_private_chat_ids = set(known_private_chat_ids or ())

    def start(self) -> None:
        return None

    async def send_text(self, chat_id: str, text: str) -> None:
        return None

    async def create_card(self, card):
        self.cards_created.append(card)
        return "card_1"

    async def send_card(self, chat_id: str, card_id: str):
        self.cards_sent.append((chat_id, card_id))
        return "message_1"

    async def send_card_to_user(self, open_id: str, card_id: str):
        self.user_cards_sent.append((open_id, card_id))
        return "message_1"

    async def update_card(self, card_id, card, sequence):
        return None

    async def close_card(self, card_id, sequence):
        return None


class FakeGatewayWithDownloads(FakeGateway):
    def __init__(self, *, downloads):
        self.downloads = downloads
        self.download_calls = []
        self.client = object()
        self.known_private_chat_ids = set()

    async def download(self, *, message_id: str, attachment: IncomingAttachment) -> DownloadedAttachment:
        self.download_calls.append((message_id, attachment.kind, attachment.resource_key))
        return self.downloads[attachment.resource_key]


class FakeCodexRpc:
    def __init__(self, kwargs=None) -> None:
        self.kwargs = kwargs or {}

    async def connect(self) -> None:
        return None

    async def initialize(self):
        return {}

    async def request(self, method: str, params: dict):
        return {}

    async def respond(self, request_id, result: dict) -> None:
        return None

    async def listen(self):
        if False:
            yield None

    async def close(self) -> None:
        return None


class FakeOpenCodeClient:
    def __init__(self, event_error: Exception | None = None) -> None:
        self.event_error = event_error
        self.events_workspace: str | None = None

    async def create_session(self, *, title: str, workspace: str):
        return {"id": "session_1"}

    async def health(self):
        return {"healthy": True}

    async def session_messages(self, *, session_id: str, workspace: str):
        return []

    async def prompt_async(self, **kwargs):
        return True

    async def answer_question(self, **kwargs):
        return True

    async def answer_permission(self, **kwargs):
        return True

    async def abort_session(self, **kwargs):
        return True

    async def events(self, *, workspace: str):
        self.events_workspace = workspace
        if self.event_error is not None:
            raise self.event_error
        if False:
            yield None


class MissingPromptOpenCodeClient(FakeOpenCodeClient):
    prompt_async = None


class FakeOpenCodeEventRouter:
    def __init__(self) -> None:
        self.events = []
        self.interruptions = []

    async def handle_event(self, event) -> None:
        self.events.append(event)

    async def handle_stream_interruption(self, reason: str) -> None:
        self.interruptions.append(reason)


def _card_commands(card: dict) -> list[str]:
    commands = []
    for element in card["body"]["elements"]:
        if element["tag"] == "action":
            commands.extend(action["value"]["cmd"] for action in element["actions"])
            continue
        if element["tag"] == "column_set":
            for column in element["columns"]:
                commands.extend(
                    child["value"]["cmd"]
                    for child in column["elements"]
                    if child["tag"] == "button"
                )
            continue
        if element["tag"] != "button":
            continue
        commands.append(element["value"]["cmd"])
    return commands


def _run_ref(*, run_id: str, scope_id: str, updated_at: str):
    from c_auto_bridge.store.models import RunRef

    return RunRef(
        run_id=run_id,
        scope_id=scope_id,
        bot_session_id="session_1",
        agent="codex",
        thread_id="thread_1",
        turn_id="turn_1",
        status="completed",
        created_at=updated_at,
        updated_at=updated_at,
    )


if __name__ == "__main__":
    unittest.main()

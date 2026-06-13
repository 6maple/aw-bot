import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any

from c_auto_bridge.agent.codex_app_server import CodexAppServerAdapter, CodexEventRouter, CodexRpc
from c_auto_bridge.agent.codex_stdio import CodexStdioClient
from c_auto_bridge.agent.codex_websocket import CodexWebSocketClient
from c_auto_bridge.agent.opencode_http import OpencodeHttpClient
from c_auto_bridge.agent.opencode_server import OpenCodeEventRouter, OpenCodeServerAdapter, OpencodeClient
from c_auto_bridge.cli_opencode import check_opencode_startup_capabilities
from c_auto_bridge.config import Config
from c_auto_bridge.config_codex import CodexConfig, load_codex_config
from c_auto_bridge.config_opencode import OpenCodeConfig, load_opencode_config
from c_auto_bridge.core.agent_session import Workspace
from c_auto_bridge.core.use_cases import CoreUseCases
from c_auto_bridge.core.workspace import WorkspaceValidator
from c_auto_bridge.feishu.gateway import FeishuGateway, IncomingCardAction
from c_auto_bridge.feishu.attachment_intake import AttachmentIntakeTracer
from c_auto_bridge.feishu.message import IncomingMessage
from c_auto_bridge.feishu.private_chat_adapter import FeishuPrivateChatAdapter
from c_auto_bridge.feishu.run_view_sink import FeishuRunViewSink
from c_auto_bridge.feishu.stream_card import LarkCardTransport, StreamCard
from c_auto_bridge.react.card_renderer import render_card
from c_auto_bridge.react.text_renderer import render_text
from c_auto_bridge.store.file_run_persistence import FileRunPersistence
from c_auto_bridge.store.file_store import FileStore


logger = logging.getLogger(__name__)


@dataclass
class RuntimeComponents:
    store: FileStore
    persistence: FileRunPersistence
    use_cases: CoreUseCases
    chat_adapter: FeishuPrivateChatAdapter
    gateway: FeishuGateway
    async_runner: "AsyncRuntimeLoop"
    listen: Callable[[], Awaitable[None]]
    listener_future: Future | None
    rpc: CodexRpc | None
    opencode: OpencodeClient | None


def build_runtime(
    config: Config,
    *,
    app_id: str,
    app_secret: str,
    store_factory: Callable[[str], FileStore] = FileStore,
    persistence_factory: Callable[[FileStore], FileRunPersistence] = FileRunPersistence,
    rpc_factory: Callable[..., CodexRpc] = CodexStdioClient,
    opencode_client_factory: Callable[[str], OpencodeClient] = OpencodeHttpClient,
    codex_config_factory: Callable[[], CodexConfig] = load_codex_config,
    opencode_config_factory: Callable[[], OpenCodeConfig] = load_opencode_config,
    gateway_factory: Callable[..., FeishuGateway] = FeishuGateway,
) -> RuntimeComponents:
    store = store_factory(config.data_dir)
    persistence = persistence_factory(store)
    store.initialize()
    asyncio.run(persistence.recover_incomplete(updated_at=datetime.now().astimezone().isoformat()))
    async_runner = AsyncRuntimeLoop()

    rpc: CodexRpc | None = None
    opencode: OpencodeClient | None = None
    event_handler: Any
    workspace: Workspace
    access_mode: str
    if config.default_agent == "codex":
        agent_config = codex_config_factory()
        workspace = Workspace(path=str(Path(agent_config.workspace).resolve()))
        access_mode = _codex_access_mode(agent_config)
        if agent_config.app_server_url is not None:
            rpc = CodexWebSocketClient(
                url=agent_config.app_server_url,
                executable=agent_config.cli_path,
                codex_home=agent_config.home,
            )
        else:
            rpc = rpc_factory(executable=agent_config.cli_path, codex_home=agent_config.home)
        event_handler = CodexEventRouter()
        agent = CodexAppServerAdapter(
            config=agent_config,
            store=store,
            rpc=rpc,
            event_router=event_handler,
        )
    elif config.default_agent == "opencode":
        agent_config = opencode_config_factory()
        workspace = Workspace(path=str(Path(agent_config.workspace).resolve()))
        access_mode = "workspace"
        opencode = opencode_client_factory(agent_config.server_url)
        capability_passed, capability_message = check_opencode_startup_capabilities(
            agent_config,
            client_factory=lambda url: opencode,
        )
        if not capability_passed:
            raise RuntimeError(capability_message)
        event_handler = OpenCodeEventRouter()
        agent = OpenCodeServerAdapter(
            config=agent_config,
            store=store,
            client=opencode,
            event_router=event_handler,
        )
    else:
        raise ValueError(f"unsupported default agent: {config.default_agent}")

    chat_adapter: FeishuPrivateChatAdapter | None = None

    async def handle_message(incoming: IncomingMessage) -> None:
        if chat_adapter is None:
            raise RuntimeError("runtime chat adapter is not attached")
        await chat_adapter.handle_message(incoming)

    async def handle_card_action(incoming: IncomingCardAction) -> None:
        if chat_adapter is None:
            raise RuntimeError("runtime chat adapter is not attached")
        await chat_adapter.handle_card_action(incoming)

    gateway = gateway_factory(
        app_id,
        app_secret,
        on_message=handle_message,
        on_card_action=handle_card_action,
        submit=async_runner.submit,
        known_private_chat_ids=set(store.list_private_chat_scope_ids(limit=20)),
    )
    run_view_sink = FeishuRunViewSink(
        stream_card=StreamCard(
            LarkCardTransport(gateway.client),
            render_card=render_card,
            render_text=render_text,
            send_text=gateway.send_text,
        ),
        send_text=gateway.send_text,
        clock=lambda: datetime.now().astimezone().isoformat(),
    )
    use_cases = CoreUseCases(
        agent=agent,
        persistence=persistence,
        run_view_sink=run_view_sink,
        workspace=workspace,
        workspace_validator=_workspace_validator(),
        access_mode=access_mode,
        agent_name=config.default_agent,
        clock=lambda: datetime.now().astimezone(),
        run_id_factory=lambda now: f"run_{now:%Y%m%d_%H%M%S_%f}",
    )
    chat_adapter = FeishuPrivateChatAdapter(
        use_cases=use_cases,
        attachment_intake=AttachmentIntakeTracer(
            cache_dir=Path(config.data_dir) / "attachment_cache",
            downloader=gateway,
        ),
        send_text=gateway.send_text,
    )
    listen = lambda: _listen(config.default_agent, rpc, opencode, event_handler, workspace=workspace)
    return RuntimeComponents(
        store=store,
        persistence=persistence,
        use_cases=use_cases,
        chat_adapter=chat_adapter,
        gateway=gateway,
        async_runner=async_runner,
        listen=listen,
        listener_future=None,
        rpc=rpc,
        opencode=opencode,
    )


def start_runtime(components: RuntimeComponents) -> None:
    components.listener_future = components.async_runner.submit(components.listen())
    components.listener_future.add_done_callback(_on_listener_done)
    components.gateway.start()


def stop_runtime(components: RuntimeComponents) -> None:
    if components.listener_future is not None:
        components.listener_future.cancel()
    components.async_runner.run(_close_runtime(components))
    components.async_runner.stop()


async def _listen(
    agent: str,
    rpc: CodexRpc | None,
    opencode: OpencodeClient | None,
    event_handler: Any,
    workspace: Workspace,
) -> None:
    if agent == "codex":
        if rpc is None:
            raise RuntimeError("Codex RPC is not configured")
        await rpc.connect()
        await rpc.initialize()
        async for event in rpc.listen():
            await event_handler.handle_event(event)
        return
    if agent == "opencode":
        if opencode is None:
            raise RuntimeError("OpenCode client is not configured")
        try:
            async for event in opencode.events(workspace=workspace.path):
                await event_handler.handle_event(event)
        except Exception as exc:
            await event_handler.handle_stream_interruption(str(exc))
            raise
        await event_handler.handle_stream_interruption("OpenCode event stream ended")
        return
    raise ValueError(f"unsupported default agent: {agent}")


async def _close_runtime(components: RuntimeComponents) -> None:
    if components.rpc is not None:
        await components.rpc.close()


def _on_listener_done(future: Future) -> None:
    if future.cancelled():
        return
    exc = future.exception()
    if exc is not None:
        logger.error("agent event listener failed", exc_info=(type(exc), exc, exc.__traceback__))


def _workspace_validator() -> WorkspaceValidator:
    system_directories = tuple(
        Path(value)
        for value in (
            tempfile.gettempdir(),
            Path.home().anchor,
        )
        if value
    )
    return WorkspaceValidator(
        home_directory=Path.home(),
        temp_directory=Path(tempfile.gettempdir()),
        system_directories=system_directories,
    )


def _codex_access_mode(config: CodexConfig) -> str:
    if config.sandbox != "workspace-write":
        raise ValueError(f"unsupported Codex sandbox: {config.sandbox}")
    return "workspace"


class AsyncRuntimeLoop:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: Thread | None = None
        self._started = Event()

    def run(self, coro: Awaitable[Any]) -> Any:
        return self.submit(coro).result()

    def submit(self, coro: Awaitable[Any]) -> Future:
        self.start()
        if self.loop is None:
            raise RuntimeError("async runtime loop was not started")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def start(self) -> None:
        if self.thread is not None:
            return
        if self.loop is None or self.loop.is_closed():
            self.loop = asyncio.new_event_loop()
        self.thread = Thread(target=self._run_loop, name="runtime-async-loop", daemon=True)
        self.thread.start()
        self._started.wait()

    def stop(self) -> None:
        if self.thread is None:
            return
        if self.loop is None:
            raise RuntimeError("async runtime loop was not started")
        future = asyncio.run_coroutine_threadsafe(self._cancel_tasks(), self.loop)
        future.result()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()
        self.loop.close()
        self.thread = None
        self._started.clear()

    def _run_loop(self) -> None:
        if self.loop is None:
            raise RuntimeError("async runtime loop was not initialized")
        asyncio.set_event_loop(self.loop)
        self._started.set()
        self.loop.run_forever()

    async def _cancel_tasks(self) -> None:
        tasks = [
            task
            for task in asyncio.all_tasks(self.loop)
            if task is not asyncio.current_task(self.loop)
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

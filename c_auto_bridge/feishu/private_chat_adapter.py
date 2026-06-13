import logging
from hashlib import sha1
from collections.abc import Awaitable, Callable
from typing import Any

from c_auto_bridge.core.use_cases import (
    ApprovalDecisionRequired,
    CoreUseCases,
    FileFinderResult,
    ModelListResult,
    OpenCodeAgentSelected,
    PrivateChatTextMessage,
    ResumeSessionList,
    RunViewAction,
    SkillListResult,
    WorkspaceListResult,
)
from c_auto_bridge.feishu.attachment_intake import AttachmentIntakeTracer
from c_auto_bridge.feishu.gateway import IncomingCardAction
from c_auto_bridge.feishu.message import IncomingMenuEvent, IncomingMessage


logger = logging.getLogger(__name__)


class FeishuPrivateChatAdapter:
    def __init__(
        self,
        *,
        use_cases: CoreUseCases,
        send_card: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        send_user_card: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        attachment_intake: AttachmentIntakeTracer | None = None,
        send_text: Callable[[str, str], Awaitable[None]] | None = None,
        show_opencode_agent_controls: bool = False,
    ) -> None:
        self._use_cases = use_cases
        self._send_card = send_card
        self._send_user_card = send_user_card
        self._attachment_intake = attachment_intake
        self._send_text = send_text
        self._show_opencode_agent_controls = show_opencode_agent_controls

    async def handle_message(self, incoming: IncomingMessage) -> None:
        if incoming.chat_type != "p2p":
            logger.info(
                "private chat adapter ignored non-p2p message: message_id=%s chat_type=%s",
                incoming.message_id,
                incoming.chat_type,
            )
            return
        logger.info(
            "private chat adapter forwarding message: message_id=%s chat_id=%s user_id=%s text_len=%s attachment_count=%s",
            incoming.message_id,
            incoming.chat_id,
            incoming.user_id,
            len(incoming.text),
            len(incoming.attachments),
        )
        attachments = ()
        if self._attachment_intake is not None:
            attachments = await self._attachment_intake.cache_attachments(incoming)
        result = await self._use_cases.handle_private_chat_text(
            PrivateChatTextMessage(
                private_chat_scope_id=incoming.chat_id,
                user_id=incoming.user_id,
                text=incoming.text,
                attachments=attachments,
            )
        )
        if isinstance(result, FileFinderResult):
            await self._send_file_finder_result(incoming.chat_id, result)
        if isinstance(result, ModelListResult):
            await self._send_model_list_result(incoming.chat_id, result)
        if isinstance(result, SkillListResult):
            await self._send_skill_list_result(incoming.chat_id, result)
        if isinstance(result, OpenCodeAgentSelected):
            await self._send_opencode_agent_selected(incoming.chat_id, result)
        if isinstance(result, ApprovalDecisionRequired):
            logger.info(
                "private chat adapter sending approval decision guidance: message_id=%s pending_id=%s",
                incoming.message_id,
                result.pending_request_id,
            )
            if self._send_text is not None:
                await self._send_text(incoming.chat_id, result.message)

    async def handle_menu(self, incoming: IncomingMenuEvent) -> None:
        logger.info(
            "private chat adapter handling menu: event_key=%s user_id=%s matched=%s",
            incoming.event_key,
            incoming.user_id,
            incoming.event_key == "aw_bot_menu()",
        )
        if incoming.event_key != "aw_bot_menu()":
            return
        if self._send_user_card is None:
            raise RuntimeError("menu user card sender is not configured")
        await self._send_user_card(
            incoming.user_id,
            _first_level_command_panel(
                show_opencode_agent_controls=self._show_opencode_agent_controls
            ),
        )

    async def handle_card_action(self, incoming: IncomingCardAction) -> None:
        action = incoming.value.get("cmd") or incoming.value.get("action")
        if not isinstance(action, str):
            raise TypeError("card action must include cmd or action")
        logger.info(
            "private chat adapter handling card action: chat_id=%s user_id=%s action=%s",
            incoming.chat_id,
            incoming.user_id,
            action,
        )
        if action == "menu:workspace":
            if self._send_card is None:
                raise RuntimeError("menu card sender is not configured")
            result = await self._use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id=incoming.chat_id,
                    user_id=incoming.user_id,
                    text="/ws list",
                )
            )
            if not isinstance(result, WorkspaceListResult):
                raise TypeError("workspace menu requires a workspace list result")
            await self._send_card(incoming.chat_id, _workspace_panel(result))
            return
        if action == "menu:sessions":
            if self._send_card is None:
                raise RuntimeError("menu card sender is not configured")
            result = await self._use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id=incoming.chat_id,
                    user_id=incoming.user_id,
                    text="/resume",
                )
            )
            if not isinstance(result, ResumeSessionList):
                raise TypeError("sessions menu requires a resume session list result")
            await self._send_card(incoming.chat_id, _sessions_panel(result))
            return
        if action == "menu:timeout":
            if self._send_card is None:
                raise RuntimeError("menu card sender is not configured")
            await self._send_card(incoming.chat_id, _idle_timeout_panel())
            return
        if action == "menu:help":
            if self._send_card is None:
                raise RuntimeError("menu card sender is not configured")
            await self._send_card(incoming.chat_id, _help_panel())
            return
        if action == "menu:model":
            if self._send_card is None:
                raise RuntimeError("menu card sender is not configured")
            result = await self._use_cases.handle_private_chat_text(
                PrivateChatTextMessage(
                    private_chat_scope_id=incoming.chat_id,
                    user_id=incoming.user_id,
                    text="/model",
                )
            )
            if not isinstance(result, ModelListResult):
                raise TypeError("model menu requires a model list result")
            await self._send_card(incoming.chat_id, _model_panel(result))
            return
        if action == "menu:files":
            if self._send_card is None:
                raise RuntimeError("menu card sender is not configured")
            await self._send_card(incoming.chat_id, _file_search_panel())
            return
        text_command = _direct_text_command(action)
        if text_command is not None:
            try:
                await self._use_cases.handle_private_chat_text(
                    PrivateChatTextMessage(
                        private_chat_scope_id=incoming.chat_id,
                        user_id=incoming.user_id,
                        text=text_command,
                    )
                )
            except RuntimeError as exc:
                if action == "menu:stop" and "scope does not have an active run for user" in str(exc):
                    await self._send_feedback(incoming.chat_id, "当前没有正在运行的任务。")
                    return
                raise
            feedback = _direct_command_feedback(action)
            if feedback is not None:
                await self._send_feedback(incoming.chat_id, feedback)
            return
        pending_id = incoming.value.get("pending_id")
        if not isinstance(pending_id, str):
            raise TypeError("pending_id must be a string")
        await self._use_cases.handle_run_view_action(
            RunViewAction(
                private_chat_scope_id=incoming.chat_id,
                user_id=incoming.user_id,
                action=_approval_action(action),
                pending_request_id=pending_id,
            )
        )

    async def _send_feedback(self, chat_id: str, text: str) -> None:
        if self._send_text is None:
            return
        await self._send_text(chat_id, text)

    async def _send_file_finder_result(self, chat_id: str, result: FileFinderResult) -> None:
        if self._send_text is None:
            return
        text = "\n".join(result.paths)
        if text == "":
            text = "No matching files found."
        await self._send_text(chat_id, text)

    async def _send_model_list_result(self, chat_id: str, result: ModelListResult) -> None:
        if self._send_text is None:
            return
        current = result.selected_model
        if current is None:
            current = "(none)"
        models = "\n".join(f"- {model}" for model in result.models)
        await self._send_text(chat_id, f"Agent: {result.agent_name}\nCurrent: {current}\nModels:\n{models}")

    async def _send_skill_list_result(self, chat_id: str, result: SkillListResult) -> None:
        if self._send_text is None:
            return
        skills = "\n".join(_skill_line(skill.name, skill.description) for skill in result.skills)
        await self._send_text(chat_id, f"Agent: {result.agent_name}\nSkills:\n{skills}")

    async def _send_opencode_agent_selected(self, chat_id: str, result: OpenCodeAgentSelected) -> None:
        if self._send_text is None:
            return
        await self._send_text(chat_id, f"OpenCode agent selected: {result.agent}")


def _approval_action(action: str) -> str:
    if action == "approve":
        return "accept"
    if action == "reject":
        return "deny"
    raise ValueError(f"unsupported card action: {action}")


def _skill_line(name: str, description: str | None) -> str:
    if description is None:
        return f"- {name}"
    return f"- {name}: {description}"


def _direct_text_command(action: str) -> str | None:
    if action == "stop":
        return "/stop"
    if action == "menu:stop":
        return "/stop"
    if action == "menu:new":
        return "/new"
    if action == "menu:reset":
        return "/reset"
    if action.startswith("menu:workspace:use:"):
        return f"/ws use {action.removeprefix('menu:workspace:use:')}"
    if action.startswith("menu:sessions:resume:"):
        return f"/resume {action.removeprefix('menu:sessions:resume:')}"
    if action.startswith("menu:timeout:"):
        return f"/timeout {action.removeprefix('menu:timeout:')}"
    if action == "menu:skills":
        return "/skills"
    if action.startswith("menu:model:use:"):
        return f"/model use {action.removeprefix('menu:model:use:')}"
    if action == "menu:agent:plan":
        return "/agent plan"
    if action == "menu:agent:build":
        return "/agent build"
    return None


def _direct_command_feedback(action: str) -> str | None:
    if action == "menu:new":
        return "已开启新的任务上下文。请直接发送你的需求。"
    if action == "menu:reset":
        return "已重置当前会话。请直接发送新的需求。"
    if action == "menu:stop":
        return "已停止当前任务。"
    return None


def _first_level_command_panel(*, show_opencode_agent_controls: bool) -> dict[str, Any]:
    rows = [
        [
            _button("新任务", "menu:new"),
            _button("停止", "menu:stop"),
            _button("重置", "menu:reset"),
        ],
        [
            _button("工作区", "menu:workspace"),
            _button("历史", "menu:sessions"),
            _button("Skills", "menu:skills"),
        ],
        [
            _button("模型", "menu:model"),
            _button("文件", "menu:files"),
        ],
    ]
    if show_opencode_agent_controls:
        rows.append(
            [
                _button("Plan", "menu:agent:plan"),
                _button("Build", "menu:agent:build"),
            ]
        )
    rows.append(
        [
            _button("超时", "menu:timeout"),
            _button("帮助", "menu:help"),
        ]
    )
    return _card("AW Bot 命令", [_button_row(row) for row in rows])


def _button_row(buttons: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tag": "column_set",
        "flex_mode": "flow",
        "horizontal_spacing": "8px",
        "columns": [_button_column(button) for button in buttons],
    }


def _button_column(button: dict[str, Any]) -> dict[str, Any]:
    return {
        "tag": "column",
        "width": "auto",
        "vertical_align": "top",
        "elements": [button],
    }


def _workspace_panel(result: WorkspaceListResult) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    if len(result.workspaces) == 0:
        elements.append(_section("还没有保存的工作区。", "workspace_empty"))
    for workspace in result.workspaces:
        elements.append(
            _section(
                f"{workspace.name}\n{workspace.workspace.path}\n更新时间：{workspace.updated_at}",
                f"workspace_{workspace.name}",
            )
        )
        elements.append(_button("使用", f"menu:workspace:use:{workspace.name}"))
    return _card("已保存的工作区", elements)


def _sessions_panel(result: ResumeSessionList) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    if len(result.sessions) == 0:
        elements.append(_section("没有可恢复的历史会话。", "sessions_empty"))
    for session in result.sessions:
        elements.append(
            _section(
                (
                    f"{session.agent_session_id}\n"
                    f"工作区：{session.workspace.path}\n"
                    f"Agent：{session.agent_name}\n"
                    f"更新时间：{session.updated_at}"
                ),
                _element_id("ses", session.agent_session_id),
            )
        )
        elements.append(_button("恢复", f"menu:sessions:resume:{session.agent_session_id}"))
    return _card("历史 Agent 会话", elements)


def _idle_timeout_panel() -> dict[str, Any]:
    return _card(
        "空闲超时",
        [
            _button("5 分钟", "menu:timeout:5"),
            _button("10 分钟", "menu:timeout:10"),
            _button("30 分钟", "menu:timeout:30"),
            _button("关闭", "menu:timeout:off"),
            _button("默认", "menu:timeout:default"),
        ],
    )


def _model_panel(result: ModelListResult) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    current = result.selected_model
    if current is None:
        current = "(none)"
    elements.append(_section(f"Agent: {result.agent_name}\nCurrent: {current}", "model_status"))
    if len(result.models) == 0:
        elements.append(_section("No models are configured.", "model_empty"))
    for model in result.models:
        elements.append(_section(model, _element_id("model", model)))
        elements.append(_button("Use", f"menu:model:use:{model}"))
    return _card("Models", elements)


def _file_search_panel() -> dict[str, Any]:
    return _card(
        "File Search",
        [
            _section("Send /files <query> to search workspace files.", "file_search_template"),
        ],
    )


def _help_panel() -> dict[str, Any]:
    return _card(
        "AW Bot 菜单帮助",
        [
            _section(
                (
                    "直接命令：/new、/stop、/reset、/ws use <名称>、"
                    "/resume <会话 ID>、/timeout 5|10|30|off|default"
                ),
                "help_direct",
            ),
            _section(
                (
                    "二级面板：工作区、历史 Agent 会话、空闲超时。"
                ),
                "help_panels",
            ),
            _section(
                "直接发送普通任务文本会开始一次 Agent Turn；只打开菜单不会启动任务。",
                "help_turns",
            ),
        ],
    )


def _button(label: str, command: str) -> dict[str, Any]:
    value = {"cmd": command}
    return {
        "tag": "button",
        "element_id": _element_id("btn", command),
        "text": {"tag": "plain_text", "content": label},
        "action_type": "request",
        "value": value,
        "behaviors": [{"type": "callback", "value": value}],
    }


def _section(content: str, element_id: str) -> dict[str, Any]:
    return {"tag": "markdown", "element_id": element_id, "content": content}


def _element_id(prefix: str, value: str) -> str:
    return f"{prefix}_{sha1(value.encode('utf-8')).hexdigest()[:10]}"


def _card(title: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": title}},
        "body": {"elements": elements},
    }

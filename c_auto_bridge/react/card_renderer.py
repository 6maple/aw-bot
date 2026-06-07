import json

from c_auto_bridge.react.state import RunState, ToolState


MAX_BLOCK_TEXT_LENGTH = 3000
THINKING_MAX_LENGTH = 1500
TOOL_TEXT_MAX_LENGTH = 1800


def render_card(state: RunState) -> dict:
    elements: list[dict] = []

    if state.thinking:
        elements.append(_thinking_panel(state.thinking, _thinking_active(state)))
    for index, part in enumerate(_split(state.text), start=1):
        if part.strip():
            elements.append({"tag": "markdown", "element_id": f"text_{index}", "content": part})

    if len(state.tools) > 1:
        elements.append(_historical_tools_panel(state.tools[:-1]))
    if state.tools:
        latest_tool = state.tools[-1]
        elements.append(_tool_panel(latest_tool, expanded=latest_tool.status == "running"))
    if _has_usage(state):
        elements.append(_usage_note(state))
    if state.pending is not None:
        elements.append(_pending_panel(state))
        if state.pending.kind == "approval":
            elements.extend(_approval_actions(state.run_id, state.pending.pending_id))
    elif state.status == "running":
        elements.append(_footer_status(state))
        elements.append(_stop_action(state.run_id))
    elif state.status == "completed" and not elements:
        elements.append(_note("_（未返回内容）_"))
    elif state.status == "failed" and state.error:
        elements.append(_note(f"⚠️ agent 失败：{state.error}"))
    elif state.status == "interrupted":
        elements.append(_note("_⏹ 已被中断_"))
    elif state.status == "timed_out":
        elements.append(_note("_⏱ 已超时_"))

    title = _title(state.status)
    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": state.status == "running",
            "update_multi": True,
            "summary": {"content": _summary(state)},
            "streaming_config": {
                "print_frequency_ms": {"default": 70, "android": 70, "ios": 70, "pc": 70},
                "print_step": {"default": 1, "android": 1, "ios": 1, "pc": 1},
                "print_strategy": "fast",
            },
        },
        "header": {"title": {"tag": "plain_text", "content": title}},
        "body": {"elements": elements},
    }


def _split(text: str) -> list[str]:
    if not text:
        return []
    return [text[index:index + MAX_BLOCK_TEXT_LENGTH] for index in range(0, len(text), MAX_BLOCK_TEXT_LENGTH)]


def _thinking_active(state: RunState) -> bool:
    return state.status == "running" and not state.text and state.pending is None


def _thinking_panel(content: str, active: bool) -> dict:
    title = "🧠 **思考中**" if active else "🧠 **思考完成，点击查看**"
    return _collapsible_panel(
        title=title,
        body=_truncate(content, THINKING_MAX_LENGTH),
        expanded=active,
        border="grey",
        element_id="thinking",
    )


def _tool_panel(tool: ToolState, *, expanded: bool) -> dict:
    status = {
        "running": "运行中",
        "completed": "已完成",
        "failed": "失败",
    }[tool.status]
    body = _tool_body(tool)
    return _collapsible_panel(
        title=f"🛠 **{tool.name}** - {status}",
        body=body,
        expanded=expanded,
        border="red" if tool.status == "failed" else "grey",
        element_id="tool_latest",
    )


def _historical_tools_panel(tools: tuple[ToolState, ...]) -> dict:
    body = "\n\n".join(_historical_tool_summary(tool) for tool in tools)
    return _collapsible_panel(
        title=f"🧰 **历史工具调用（{len(tools)}）**",
        body=body,
        expanded=False,
        border="grey",
        element_id="tool_history",
    )


def _historical_tool_summary(tool: ToolState) -> str:
    status = {
        "running": "运行中",
        "completed": "已完成",
        "failed": "失败",
    }[tool.status]
    return f"**{tool.name}** - {status}\n{_tool_body(tool)}"


def _tool_body(tool: ToolState) -> str:
    body = f"**输入**\n```json\n{_format_json(tool.input)}\n```"
    if tool.output:
        body = f"{body}\n\n**输出**\n```\n{_truncate(tool.output, TOOL_TEXT_MAX_LENGTH)}\n```"
    return body


def _format_json(value: dict) -> str:
    return _truncate(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        TOOL_TEXT_MAX_LENGTH,
    )


def _collapsible_panel(*, title: str, body: str, expanded: bool, border: str, element_id: str) -> dict:
    return {
        "tag": "collapsible_panel",
        "element_id": element_id,
        "expanded": expanded,
        "header": {
            "title": {"tag": "markdown", "content": title},
            "vertical_align": "center",
            "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "size": "16px 16px"},
            "icon_position": "follow_text",
            "icon_expanded_angle": -180,
        },
        "border": {"color": border, "corner_radius": "5px"},
        "vertical_spacing": "8px",
        "padding": "8px 8px 8px 8px",
        "elements": [{"tag": "markdown", "content": body, "text_size": "notation"}],
    }


def _note(content: str) -> dict:
    return {"tag": "markdown", "content": content, "text_size": "notation"}


def _pending_panel(state: RunState) -> dict:
    if state.pending is None:
        raise ValueError("pending state is required")
    if state.pending.kind == "user_input":
        content = f"**请补充信息**\n\n{state.pending.prompt}\n\n直接回复这条消息即可继续。"
    else:
        content = f"**等待审批**\n\n{state.pending.prompt}"
    return {"tag": "markdown", "element_id": "pending", "content": content}


def _has_usage(state: RunState) -> bool:
    return state.usage.input_tokens > 0 or state.usage.output_tokens > 0


def _usage_note(state: RunState) -> dict:
    return _note(
        f"Token 用量：输入 {state.usage.input_tokens} / 输出 {state.usage.output_tokens}"
    )


def _footer_status(state: RunState) -> dict:
    if state.tools and state.tools[-1].status == "running":
        return _note("🛠 正在调用工具")
    if state.text:
        return _note("✍️ 正在输出")
    return _note("🧠 正在思考")


def _stop_action(run_id: str) -> dict:
    value = {"cmd": "stop", "run_id": run_id}
    return {
        "tag": "button",
        "element_id": "stop_btn",
        "text": {"tag": "plain_text", "content": "⏹ 终止"},
        "type": "danger",
        "action_type": "request",
        "value": value,
        "behaviors": [
            {"type": "callback", "value": value}
        ],
    }


def _approval_actions(run_id: str, pending_id: str) -> list[dict]:
    return [
        {
            "tag": "button",
            "element_id": element_id,
            "text": {"tag": "plain_text", "content": label},
            "action_type": "request",
            "value": {"cmd": action, "run_id": run_id, "pending_id": pending_id},
            "behaviors": [
                {"type": "callback", "value": {"cmd": action, "run_id": run_id, "pending_id": pending_id}}
            ],
        }
        for element_id, label, action in (("approve_btn", "批准", "approve"), ("reject_btn", "拒绝", "reject"))
    ]


def _title(status: str) -> str:
    return {
        "running": "处理中",
        "pending_user_input": "等待补充信息",
        "pending_approval": "等待审批",
        "completed": "已完成",
        "failed": "失败",
        "interrupted": "已停止",
        "timed_out": "已超时",
    }[status]


def _summary(state: RunState) -> str:
    if state.status == "running":
        if state.tools and state.tools[-1].status == "running":
            return "正在调用工具"
        if state.text:
            return "正在输出"
        return "思考中"
    return _title(state.status)


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[:max_length]}..."

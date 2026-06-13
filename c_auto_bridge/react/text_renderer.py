from c_auto_bridge.react.state import RunState


MAX_TEXT_LENGTH = 4000


def render_text(state: RunState) -> str:
    if state.pending is not None:
        text = _pending_text(state)
    elif state.text:
        text = state.text
    elif state.error:
        text = f"任务失败：{state.error}"
    else:
        text = _status_text(state.status)
    if len(text) <= MAX_TEXT_LENGTH:
        return text
    return text[: MAX_TEXT_LENGTH - 1] + "…"


def _pending_text(state: RunState) -> str:
    if state.pending is None:
        raise ValueError("pending text requires pending state")
    if state.pending.kind == "approval":
        prompt = state.pending.prompt or "需要审批"
        return f"等待审批：\n{prompt}\n\n回复“同意”继续，或回复“拒绝”取消。"
    prompt = state.pending.prompt or "请补充信息"
    return f"等待补充信息：\n{prompt}"


def _status_text(status: str) -> str:
    return {
        "running": "处理中…",
        "pending_user_input": "等待补充信息",
        "pending_approval": "等待审批",
        "completed": "任务已完成",
        "failed": "任务失败",
        "interrupted": "任务已停止",
        "timed_out": "任务已超时",
    }[status]

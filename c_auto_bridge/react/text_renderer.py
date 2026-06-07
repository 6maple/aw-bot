from c_auto_bridge.react.state import RunState


MAX_TEXT_LENGTH = 4000


def render_text(state: RunState) -> str:
    if state.text:
        text = state.text
    elif state.error:
        text = f"任务失败：{state.error}"
    else:
        text = _status_text(state.status)
    if len(text) <= MAX_TEXT_LENGTH:
        return text
    return text[: MAX_TEXT_LENGTH - 1] + "…"


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

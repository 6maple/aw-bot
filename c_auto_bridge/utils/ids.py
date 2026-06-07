from datetime import datetime


def new_bot_session_id(now: datetime | None = None) -> str:
    timestamp = now or datetime.now().astimezone()
    return f"s_{timestamp:%Y%m%d_%H%M%S_%f}"


def new_pending_id(now: datetime | None = None) -> str:
    timestamp = now or datetime.now().astimezone()
    return f"p_{timestamp:%Y%m%d_%H%M%S_%f}"


def new_run_id(now: datetime | None = None) -> str:
    timestamp = now or datetime.now().astimezone()
    return f"r_{timestamp:%Y%m%d_%H%M%S_%f}"

APPROVAL_DECISIONS = {
    "同意": "accept",
    "yes": "accept",
    "y": "accept",
    "allow": "accept",
    "本会话同意": "acceptForSession",
    "always": "acceptForSession",
    "拒绝": "decline",
    "no": "decline",
    "n": "decline",
    "deny": "decline",
    "取消": "cancel",
    "cancel": "cancel",
}


def map_approval_decision(text: str) -> str | None:
    return APPROVAL_DECISIONS.get(text.strip().lower())

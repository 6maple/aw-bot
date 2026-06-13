from typing import Any

from lark_oapi.ws import client as lark_ws_client


LARK_WS_KEEPALIVE_DISABLED_MARKER = "_c_auto_bridge_keepalive_disabled"


def disable_websockets_builtin_keepalive(ws_client_module: Any = lark_ws_client) -> None:
    """Disable websockets' protocol ping while preserving Lark's business ping."""
    current = ws_client_module._ws_connect_kwargs
    if getattr(current, LARK_WS_KEEPALIVE_DISABLED_MARKER, False):
        return

    def patched() -> dict[str, Any]:
        kwargs = dict(current())
        kwargs["ping_interval"] = None
        return kwargs

    setattr(patched, LARK_WS_KEEPALIVE_DISABLED_MARKER, True)
    ws_client_module._ws_connect_kwargs = patched

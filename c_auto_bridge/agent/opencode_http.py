import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class OpencodeHttpError(RuntimeError):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"OpenCode HTTP {status}: {body}")


class OpencodeHttpClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/global/health")

    async def list_providers(self, *, workspace: str) -> dict[str, Any]:
        return await self._request("GET", _with_directory("/provider", workspace))

    async def providers(self, *, workspace: str) -> dict[str, Any]:
        return await self.list_providers(workspace=workspace)

    async def list_agents(self, *, workspace: str) -> list[dict[str, Any]]:
        return await self._request("GET", _with_directory("/agent", workspace))

    async def list_skills(self, *, workspace: str) -> list[dict[str, Any]]:
        return await self._request("GET", _with_directory("/skill", workspace))

    async def create_session(self, *, title: str, workspace: str) -> dict[str, Any]:
        return await self._request("POST", _with_directory("/session", workspace), {"title": title})

    async def session_messages(
        self,
        *,
        session_id: str,
        workspace: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        path = f"/session/{quote(session_id, safe='')}/message"
        if limit is not None:
            path = f"{path}?{urlencode({'limit': limit})}"
        path = _with_directory(path, workspace)
        return await self._request("GET", path)

    async def session_message(self, *, session_id: str, message_id: str, workspace: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            _with_directory(
                f"/session/{quote(session_id, safe='')}/message/{quote(message_id, safe='')}",
                workspace,
            ),
        )

    async def prompt_async(
        self,
        *,
        session_id: str,
        message_id: str,
        text: str,
        model: dict[str, str] | None,
        agent: str | None,
        workspace: str,
    ) -> bool:
        return await self._send_prompt(
            path=_with_directory(f"/session/{quote(session_id, safe='')}/prompt_async", workspace),
            message_id=message_id,
            text=text,
            model=model,
            agent=agent,
        )

    async def events(self, *, workspace: str) -> AsyncIterator[dict[str, Any]]:
        events = self._sync_events(workspace=workspace)
        while True:
            event = await asyncio.to_thread(next, events)
            yield event

    async def _send_prompt(
        self,
        *,
        path: str,
        message_id: str | None,
        text: str,
        model: dict[str, str] | None,
        agent: str | None,
    ) -> Any:
        body: dict[str, Any] = {
            "parts": [
                {
                    "type": "text",
                    "text": text,
                }
            ]
        }
        if message_id is not None:
            body["messageID"] = message_id
        if model is not None:
            body["model"] = model
        if agent is not None:
            body["agent"] = agent
        return await self._request("POST", path, body)

    async def answer_permission(
        self,
        *,
        session_id: str,
        permission_id: str,
        decision: str,
        workspace: str,
    ) -> bool:
        return await self._request(
            "POST",
            _with_directory(f"/permission/{quote(permission_id, safe='')}/reply", workspace),
            {"reply": decision},
        )

    async def answer_question(
        self,
        *,
        question_id: str,
        answers: list[list[str]],
        workspace: str,
    ) -> bool:
        return await self._request(
            "POST",
            _with_directory(f"/question/{quote(question_id, safe='')}/reply", workspace),
            {"answers": answers},
        )

    async def abort_session(self, *, session_id: str, workspace: str) -> bool:
        return await self._request(
            "POST",
            _with_directory(f"/session/{quote(session_id, safe='')}/abort", workspace),
        )

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        return await asyncio.to_thread(self._sync_request, method, path, body)

    def _sync_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
    ) -> Any:
        data = None
        headers = {"Accept": "application/json"}
        auth_header = _basic_auth_header()
        if auth_header is not None:
            headers["Authorization"] = auth_header
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                content = response.read()
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise OpencodeHttpError(exc.code, error_body) from exc
        if not content:
            return True
        return json.loads(content.decode("utf-8"))

    def _sync_events(self, *, workspace: str):
        request = Request(
            f"{self.base_url}{_with_directory('/event', workspace)}",
            headers={
                "Accept": "text/event-stream",
                **_auth_headers(),
            },
            method="GET",
        )
        with urlopen(request, timeout=None) as response:
            data_lines: list[str] = []
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    if data_lines:
                        yield json.loads("\n".join(data_lines))
                        data_lines = []
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())


def _basic_auth_header() -> str | None:
    password = os.environ.get("OPENCODE_SERVER_PASSWORD")
    if password is None:
        return None
    username = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _auth_headers() -> dict[str, str]:
    auth_header = _basic_auth_header()
    if auth_header is None:
        return {}
    return {"Authorization": auth_header}


def _with_directory(path: str, workspace: str) -> str:
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}{urlencode({'directory': workspace})}"

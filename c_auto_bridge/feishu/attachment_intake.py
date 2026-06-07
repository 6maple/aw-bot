from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from c_auto_bridge.core.agent_session import AgentSession
from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.feishu.message import IncomingAttachment, IncomingMessage


SUPPORTED_ATTACHMENT_KINDS = {"image", "file"}


@dataclass(frozen=True)
class DownloadedAttachment:
    file_name: str
    content: bytes


class AttachmentDownloader(Protocol):
    async def download(
        self,
        *,
        message_id: str,
        attachment: IncomingAttachment,
    ) -> DownloadedAttachment:
        ...


class AttachmentAgentPort(Protocol):
    async def start_turn(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
        attachments: tuple[Attachment, ...],
    ) -> object:
        ...


class AttachmentIntakeTracer:
    def __init__(self, *, cache_dir: Path, downloader: AttachmentDownloader) -> None:
        self._cache_dir = cache_dir
        self._downloader = downloader

    async def start_turn(
        self,
        *,
        agent: AttachmentAgentPort,
        agent_session: AgentSession,
        message: IncomingMessage,
    ) -> object:
        attachments = await self._cache_attachments(message)
        return await agent.start_turn(
            agent_session=agent_session,
            prompt=message.text,
            attachments=attachments,
        )

    async def _cache_attachments(self, message: IncomingMessage) -> tuple[Attachment, ...]:
        cached_attachments: list[Attachment] = []
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        for attachment in message.attachments:
            if attachment.kind not in SUPPORTED_ATTACHMENT_KINDS:
                continue
            downloaded = await self._downloader.download(
                message_id=message.message_id,
                attachment=attachment,
            )
            path = self._cache_dir / f"{attachment.resource_key}__{downloaded.file_name}"
            path.write_bytes(downloaded.content)
            cached_attachments.append(
                Attachment(
                    kind=attachment.kind,
                    path=str(path),
                    name=downloaded.file_name,
                )
            )
        return tuple(cached_attachments)

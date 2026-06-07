from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from c_auto_bridge.core.agent_session import AgentSession, Workspace
from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.feishu.attachment_intake import (
    AttachmentIntakeTracer,
    DownloadedAttachment,
)
from c_auto_bridge.feishu.message import IncomingAttachment, IncomingMessage


class AttachmentIntakeTracerTest(unittest.IsolatedAsyncioTestCase):
    async def test_downloads_supported_attachments_to_cache_and_passes_core_attachments(self) -> None:
        with TemporaryDirectory() as tmpdir:
            downloader = FakeDownloader(
                downloads={
                    "img_1": DownloadedAttachment(file_name="diagram.png", content=b"png"),
                    "file_1": DownloadedAttachment(file_name="notes.txt", content=b"text"),
                }
            )
            agent = FakeAttachmentAgentPort()
            tracer = AttachmentIntakeTracer(cache_dir=Path(tmpdir), downloader=downloader)

            await tracer.start_turn(
                agent=agent,
                agent_session=_session(),
                message=IncomingMessage(
                    message_id="om_1",
                    chat_id="chat_1",
                    chat_type="p2p",
                    user_id="user_1",
                    text="review these",
                    attachments=(
                        IncomingAttachment(kind="image", resource_key="img_1", file_name="diagram.png"),
                        IncomingAttachment(kind="file", resource_key="file_1", file_name="notes.txt"),
                    ),
                ),
            )

            self.assertEqual(
                downloader.calls,
                [("om_1", "image", "img_1"), ("om_1", "file", "file_1")],
            )
            self.assertEqual(
                agent.calls,
                [
                    (
                        "session_1",
                        "review these",
                        (
                            Attachment(kind="image", path=str(Path(tmpdir) / "img_1__diagram.png"), name="diagram.png"),
                            Attachment(kind="file", path=str(Path(tmpdir) / "file_1__notes.txt"), name="notes.txt"),
                        ),
                    )
                ],
            )
            self.assertEqual((Path(tmpdir) / "img_1__diagram.png").read_bytes(), b"png")
            self.assertEqual((Path(tmpdir) / "file_1__notes.txt").read_bytes(), b"text")

    async def test_skips_unsupported_media_kinds(self) -> None:
        with TemporaryDirectory() as tmpdir:
            downloader = FakeDownloader(downloads={})
            agent = FakeAttachmentAgentPort()
            tracer = AttachmentIntakeTracer(cache_dir=Path(tmpdir), downloader=downloader)

            await tracer.start_turn(
                agent=agent,
                agent_session=_session(),
                message=IncomingMessage(
                    message_id="om_1",
                    chat_id="chat_1",
                    chat_type="p2p",
                    user_id="user_1",
                    text="skip unsupported",
                    attachments=(
                        IncomingAttachment(kind="audio", resource_key="audio_1", file_name="voice.m4a"),
                        IncomingAttachment(kind="sticker", resource_key="sticker_1", file_name="smile.webp"),
                    ),
                ),
            )

            self.assertEqual(downloader.calls, [])
            self.assertEqual(agent.calls, [("session_1", "skip unsupported", ())])


def _session() -> AgentSession:
    return AgentSession(
        agent_session_id="session_1",
        private_chat_scope_id="chat_1",
        user_id="user_1",
        agent_name="codex",
        workspace=Workspace(path="D:/repo"),
        access_mode="workspace",
    )


@dataclass(frozen=True)
class FakeDownloader:
    downloads: dict[str, DownloadedAttachment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "calls", [])

    async def download(self, *, message_id: str, attachment: IncomingAttachment) -> DownloadedAttachment:
        self.calls.append((message_id, attachment.kind, attachment.resource_key))
        return self.downloads[attachment.resource_key]


@dataclass(frozen=True)
class FakeAttachmentAgentPort:
    def __post_init__(self) -> None:
        object.__setattr__(self, "calls", [])

    async def start_turn(
        self,
        *,
        agent_session: AgentSession,
        prompt: str,
        attachments: tuple[Attachment, ...],
    ) -> None:
        self.calls.append((agent_session.agent_session_id, prompt, attachments))


if __name__ == "__main__":
    unittest.main()

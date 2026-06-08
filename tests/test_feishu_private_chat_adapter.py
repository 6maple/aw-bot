import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.core.use_cases import PrivateChatTextMessage, RunViewAction
from c_auto_bridge.feishu.attachment_intake import AttachmentIntakeTracer, DownloadedAttachment
from c_auto_bridge.feishu.gateway import IncomingCardAction
from c_auto_bridge.feishu.message import IncomingAttachment, IncomingMessage
from c_auto_bridge.feishu.private_chat_adapter import FeishuPrivateChatAdapter


class FeishuPrivateChatAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_private_chat_message_is_forwarded_to_core_use_cases(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="p2p",
                user_id="user_1",
                text="ship it",
            )
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "ship it")],
        )

    async def test_private_chat_message_downloads_supported_attachments_before_forwarding(self) -> None:
        use_cases = FakeUseCases()
        downloader = FakeDownloader(
            {
                "img_1": DownloadedAttachment(file_name="diagram.png", content=b"png"),
                "file_1": DownloadedAttachment(file_name="notes.txt", content=b"text"),
            }
        )
        with TemporaryDirectory() as tmpdir:
            intake = AttachmentIntakeTracer(cache_dir=Path(tmpdir), downloader=downloader)
            adapter = FeishuPrivateChatAdapter(use_cases=use_cases, attachment_intake=intake)

            await adapter.handle_message(
                IncomingMessage(
                    message_id="om_1",
                    chat_id="chat_1",
                    chat_type="p2p",
                    user_id="user_1",
                    text="review",
                    attachments=(
                        IncomingAttachment(kind="image", resource_key="img_1", file_name="diagram.png"),
                        IncomingAttachment(kind="file", resource_key="file_1", file_name="notes.txt"),
                        IncomingAttachment(kind="audio", resource_key="audio_1", file_name="voice.m4a"),
                    ),
                )
            )

            self.assertEqual(downloader.calls, [("om_1", "image", "img_1"), ("om_1", "file", "file_1")])
            self.assertEqual((Path(tmpdir) / "img_1__diagram.png").read_bytes(), b"png")
            self.assertEqual((Path(tmpdir) / "file_1__notes.txt").read_bytes(), b"text")
            self.assertEqual(
                use_cases.text_messages,
                [
                    PrivateChatTextMessage(
                        "chat_1",
                        "user_1",
                        "review",
                        (
                            Attachment(kind="image", path=str(Path(tmpdir) / "img_1__diagram.png"), name="diagram.png"),
                            Attachment(kind="file", path=str(Path(tmpdir) / "file_1__notes.txt"), name="notes.txt"),
                        ),
                    )
                ],
            )

    async def test_non_private_chat_message_is_ignored(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_message(
            IncomingMessage(
                message_id="om_1",
                chat_id="chat_1",
                chat_type="group",
                user_id="user_1",
                text="ship it",
            )
        )

        self.assertEqual(use_cases.text_messages, [])

    async def test_stop_card_action_becomes_stop_command(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "stop", "run_id": "run_1"})
        )

        self.assertEqual(
            use_cases.text_messages,
            [PrivateChatTextMessage("chat_1", "user_1", "/stop")],
        )

    async def test_approval_card_action_is_mapped_to_core_run_view_action(self) -> None:
        use_cases = FakeUseCases()
        adapter = FeishuPrivateChatAdapter(use_cases=use_cases)

        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"cmd": "approve", "pending_id": "pending_1"})
        )
        await adapter.handle_card_action(
            IncomingCardAction("chat_1", "user_1", {"action": "reject", "pending_id": "pending_2"})
        )

        self.assertEqual(
            use_cases.run_view_actions,
            [
                RunViewAction("chat_1", "user_1", "accept", "pending_1"),
                RunViewAction("chat_1", "user_1", "deny", "pending_2"),
            ],
        )


class FakeUseCases:
    def __init__(self) -> None:
        self.text_messages: list[PrivateChatTextMessage] = []
        self.run_view_actions: list[RunViewAction] = []

    async def handle_private_chat_text(self, message: PrivateChatTextMessage) -> None:
        self.text_messages.append(message)

    async def handle_run_view_action(self, action: RunViewAction) -> None:
        self.run_view_actions.append(action)


class FakeDownloader:
    def __init__(self, downloads: dict[str, DownloadedAttachment]) -> None:
        self.downloads = downloads
        self.calls: list[tuple[str, str, str]] = []

    async def download(self, *, message_id: str, attachment: IncomingAttachment) -> DownloadedAttachment:
        self.calls.append((message_id, attachment.kind, attachment.resource_key))
        return self.downloads[attachment.resource_key]



if __name__ == "__main__":
    unittest.main()

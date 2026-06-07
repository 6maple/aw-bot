import unittest

from c_auto_bridge.feishu.message import IncomingAttachment, parse_message_content, parse_text_content


class ParseTextContentTest(unittest.TestCase):
    def test_parse_text_content(self) -> None:
        self.assertEqual(parse_text_content('{"text": "hello"}'), "hello")

    def test_reject_missing_text(self) -> None:
        with self.assertRaises(KeyError):
            parse_text_content("{}")

    def test_reject_non_string_text(self) -> None:
        with self.assertRaises(TypeError):
            parse_text_content('{"text": 123}')

    def test_parse_image_attachment_content(self) -> None:
        text, attachments = parse_message_content("image", '{"image_key": "img_1"}')

        self.assertEqual(text, "")
        self.assertEqual(
            attachments,
            (IncomingAttachment(kind="image", resource_key="img_1", file_name=None),),
        )

    def test_parse_file_attachment_content(self) -> None:
        text, attachments = parse_message_content(
            "file",
            '{"file_key": "file_1", "file_name": "notes.txt"}',
        )

        self.assertEqual(text, "")
        self.assertEqual(
            attachments,
            (IncomingAttachment(kind="file", resource_key="file_1", file_name="notes.txt"),),
        )

    def test_parse_unsupported_media_content(self) -> None:
        text, attachments = parse_message_content(
            "audio",
            '{"file_key": "audio_1"}',
        )

        self.assertEqual(text, "")
        self.assertEqual(
            attachments,
            (IncomingAttachment(kind="audio", resource_key="audio_1", file_name=None),),
        )


if __name__ == "__main__":
    unittest.main()

from datetime import datetime, timedelta, timezone
import unittest

from c_auto_bridge.core.attachments import Attachment
from c_auto_bridge.core.queue import QueuedMessage, pop_next_merged_prompt


class CoreQueueTest(unittest.TestCase):
    def test_merges_messages_within_merge_window(self) -> None:
        start = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        items = [
            QueuedMessage(user_id="user_1", text="one", queued_at=start),
            QueuedMessage(user_id="user_1", text="two", queued_at=start + timedelta(seconds=1)),
            QueuedMessage(user_id="user_1", text="three", queued_at=start + timedelta(seconds=4)),
        ]

        prompt, attachments, user_id, remaining = pop_next_merged_prompt(items, merge_window_seconds=1.5)

        self.assertEqual(user_id, "user_1")
        self.assertEqual(prompt, "one\ntwo")
        self.assertEqual(attachments, ())
        self.assertEqual([item.text for item in remaining], ["three"])

    def test_empty_queue_has_no_prompt(self) -> None:
        self.assertIsNone(pop_next_merged_prompt([], merge_window_seconds=1.5))

    def test_merges_attachments_in_message_order_without_empty_text_newlines(self) -> None:
        start = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        image = Attachment(kind="image", path="D:/cache/a.png", name="a.png")
        file = Attachment(kind="file", path="D:/cache/b.txt", name="b.txt")
        second_image = Attachment(kind="image", path="D:/cache/c.png", name="c.png")
        items = [
            QueuedMessage(user_id="user_1", text="", attachments=(image,), queued_at=start),
            QueuedMessage(user_id="user_1", text="describe these", queued_at=start + timedelta(seconds=1)),
            QueuedMessage(user_id="user_1", text="", attachments=(file, second_image), queued_at=start + timedelta(seconds=1.4)),
        ]

        prompt, attachments, user_id, remaining = pop_next_merged_prompt(items, merge_window_seconds=1.5)

        self.assertEqual(user_id, "user_1")
        self.assertEqual(prompt, "describe these")
        self.assertEqual(attachments, (image, file, second_image))
        self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main()

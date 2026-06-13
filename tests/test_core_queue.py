from datetime import datetime, timedelta, timezone
import unittest

from c_auto_bridge.core.queue import QueuedMessage, pop_next_merged_prompt


class CoreQueueTest(unittest.TestCase):
    def test_merges_messages_within_merge_window(self) -> None:
        start = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        items = [
            QueuedMessage(user_id="user_1", text="one", queued_at=start, model=None, opencode_agent=None),
            QueuedMessage(
                user_id="user_1",
                text="two",
                queued_at=start + timedelta(seconds=1),
                model="test-model",
                opencode_agent="plan",
            ),
            QueuedMessage(
                user_id="user_1",
                text="three",
                queued_at=start + timedelta(seconds=4),
                model=None,
                opencode_agent=None,
            ),
        ]

        prompt, user_id, model, opencode_agent, remaining = pop_next_merged_prompt(items, merge_window_seconds=1.5)

        self.assertEqual(user_id, "user_1")
        self.assertEqual(model, "test-model")
        self.assertEqual(opencode_agent, "plan")
        self.assertEqual(prompt, "one\ntwo")
        self.assertEqual([item.text for item in remaining], ["three"])

    def test_empty_queue_has_no_prompt(self) -> None:
        self.assertIsNone(pop_next_merged_prompt([], merge_window_seconds=1.5))


if __name__ == "__main__":
    unittest.main()

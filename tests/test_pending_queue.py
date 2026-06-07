import asyncio
import unittest

from c_auto_bridge.bot.pending_queue import PendingQueue


class PendingQueueTest(unittest.TestCase):
    def test_merges_messages_and_waits_for_active_scope(self) -> None:
        async def run() -> None:
            active = {"chat": True}
            sent = []

            async def dispatch(scope, user, text):
                sent.append((scope, user, text))

            queue = PendingQueue(dispatch, is_active=lambda scope: active[scope], debounce_seconds=0.01)
            queue.submit("chat", "user", "one")
            queue.submit("chat", "user", "two")
            await asyncio.sleep(0.03)
            self.assertEqual(sent, [])
            active["chat"] = False
            for _ in range(20):
                if sent:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(sent, [("chat", "user", "one\ntwo")])
            await queue.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

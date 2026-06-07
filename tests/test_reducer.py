import unittest

from c_auto_bridge.react.events import (
    ApprovalRequested,
    RunCompleted,
    RunFailed,
    RunInterrupted,
    RunTimedOut,
    TextDelta,
    ThinkingDelta,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
    UserInputRequested,
)
from c_auto_bridge.react.reducer import reduce_run_state
from c_auto_bridge.react.state import initial_run_state


class RunStateReducerTest(unittest.TestCase):
    def test_reduces_progress_and_pending_events(self) -> None:
        state = initial_run_state("run_1")
        events = [
            ThinkingDelta("considering"),
            TextDelta("Done"),
            ToolStarted("tool_1", "shell", {"command": "pytest"}),
            ToolFinished("tool_1", "passed", False),
            UsageUpdated(10, 4),
            UserInputRequested("pending_1", "Which file?", {"field": "path"}),
            ApprovalRequested("pending_2", "Run tests?", {"command": "pytest"}),
        ]

        for event in events:
            state = reduce_run_state(state, event)

        self.assertEqual(state.thinking, "considering")
        self.assertEqual(state.text, "Done")
        self.assertEqual(state.tools[0].status, "completed")
        self.assertEqual(state.tools[0].output, "passed")
        self.assertEqual(state.usage.input_tokens, 10)
        self.assertEqual(state.usage.output_tokens, 4)
        self.assertEqual(state.pending.pending_id, "pending_2")
        self.assertEqual(state.pending.kind, "approval")

    def test_reduces_all_terminal_events(self) -> None:
        cases = [
            (RunCompleted(), "completed", None),
            (RunFailed("boom"), "failed", "boom"),
            (RunInterrupted(), "interrupted", None),
            (RunTimedOut(), "timed_out", None),
        ]

        for event, status, error in cases:
            with self.subTest(status=status):
                state = reduce_run_state(initial_run_state("run_1"), event)
                self.assertEqual(state.status, status)
                self.assertEqual(state.error, error)
                self.assertIsNone(state.pending)


if __name__ == "__main__":
    unittest.main()

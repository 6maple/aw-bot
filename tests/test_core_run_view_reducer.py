import ast
from pathlib import Path
import unittest

from c_auto_bridge.core.agent_events import (
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
from c_auto_bridge.core.run_view import initial_run_view
from c_auto_bridge.core.run_view_reducer import reduce_run_view


class CoreRunViewReducerTest(unittest.TestCase):
    def test_reduces_progress_and_pending_events(self) -> None:
        state = initial_run_view("run_1")
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
            state = reduce_run_view(state, event)

        self.assertEqual(state.thinking, "considering")
        self.assertEqual(state.text, "Done")
        self.assertEqual(state.tools[0].status, "completed")
        self.assertEqual(state.tools[0].output, "passed")
        self.assertEqual(state.usage.input_tokens, 10)
        self.assertEqual(state.usage.output_tokens, 4)
        self.assertEqual(state.pending.pending_request_id, "pending_2")
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
                state = reduce_run_view(
                    reduce_run_view(
                        initial_run_view("run_1"),
                        UserInputRequested("pending_1", "Which file?", {"field": "path"}),
                    ),
                    event,
                )
                self.assertEqual(state.status, status)
                self.assertEqual(state.error, error)
                self.assertIsNone(state.pending)

    def test_reducer_module_depends_only_on_core_types(self) -> None:
        path = Path("c_auto_bridge/core/run_view_reducer.py")
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = []
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)

        forbidden_prefixes = (
            "c_auto_bridge.agent",
            "c_auto_bridge.feishu",
            "c_auto_bridge.react",
            "c_auto_bridge.runtime",
            "c_auto_bridge.store",
        )
        for name in imported:
            self.assertFalse(
                name.startswith(forbidden_prefixes),
                msg=f"{path} imports forbidden module {name}",
            )


if __name__ == "__main__":
    unittest.main()

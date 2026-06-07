from dataclasses import replace
import unittest

from c_auto_bridge.react.card_renderer import render_card
from c_auto_bridge.react.state import PendingState, ToolState, UsageState, initial_run_state
from c_auto_bridge.react.text_renderer import render_text


class RendererTest(unittest.TestCase):
    def test_running_card_contains_streaming_and_stop(self) -> None:
        card = render_card(replace(initial_run_state("run_1"), text="hello"))
        self.assertTrue(card["config"]["streaming_mode"])
        self.assertTrue(card["config"]["update_multi"])
        self.assertEqual(card["config"]["summary"]["content"], "正在输出")
        self.assertEqual(card["config"]["streaming_config"]["print_strategy"], "fast")
        button = card["body"]["elements"][-1]
        self.assertEqual(button["tag"], "button")
        self.assertEqual(button["action_type"], "request")
        self.assertEqual(button["value"]["cmd"], "stop")
        self.assertEqual(button["value"]["run_id"], "run_1")
        self.assertEqual(button["behaviors"][0]["value"]["cmd"], "stop")
        self.assertEqual(button["behaviors"][0]["value"]["run_id"], "run_1")

    def test_running_footer_statuses(self) -> None:
        thinking_card = render_card(initial_run_state("run_1"))
        output_card = render_card(replace(initial_run_state("run_1"), text="hello"))
        tool_card = render_card(
            replace(
                initial_run_state("run_1"),
                tools=(ToolState("tool_1", "shell", {"command": "pytest"}, None, "running"),),
            )
        )

        self.assertEqual(thinking_card["config"]["summary"]["content"], "思考中")
        self.assertIn("正在思考", thinking_card["body"]["elements"][-2]["content"])
        self.assertEqual(output_card["config"]["summary"]["content"], "正在输出")
        self.assertIn("正在输出", output_card["body"]["elements"][-2]["content"])
        self.assertEqual(tool_card["config"]["summary"]["content"], "正在调用工具")
        self.assertIn("正在调用工具", tool_card["body"]["elements"][-2]["content"])

    def test_tool_history_and_latest_tool_rendering(self) -> None:
        state = replace(
            initial_run_state("run_1"),
            tools=(
                ToolState("tool_1", "shell", {"command": "pytest"}, "passed", "completed"),
                ToolState("tool_2", "edit", {"file": "a.py"}, None, "running"),
            ),
        )

        card = render_card(state)
        history = card["body"]["elements"][0]
        latest = card["body"]["elements"][1]

        self.assertEqual(history["element_id"], "tool_history")
        self.assertFalse(history["expanded"])
        self.assertIn("历史工具调用（1）", history["header"]["title"]["content"])
        self.assertIn('"command": "pytest"', history["elements"][0]["content"])
        self.assertIn("passed", history["elements"][0]["content"])
        self.assertEqual(latest["element_id"], "tool_latest")
        self.assertTrue(latest["expanded"])
        self.assertIn('"file": "a.py"', latest["elements"][0]["content"])

    def test_tool_element_id_satisfies_feishu_card_constraint(self) -> None:
        state = replace(
            initial_run_state("run_1"),
            tools=(
                ToolState(
                    "prt_ea153a8c4001CbBLm9Q6P3oc38",
                    "glob",
                    {"pattern": "*"},
                    "files",
                    "completed",
                ),
            ),
        )

        card = render_card(state)

        for element_id in _element_ids(card):
            self.assertRegex(element_id, r"^[A-Za-z][A-Za-z0-9_]{0,19}$")

    def test_usage_is_displayed_when_available(self) -> None:
        state = replace(
            initial_run_state("run_1"),
            status="completed",
            text="done",
            usage=UsageState(input_tokens=12, output_tokens=5),
        )

        card = render_card(state)

        self.assertIn("Token 用量：输入 12 / 输出 5", card["body"]["elements"][-1]["content"])

    def test_card_separates_thinking_from_final_output(self) -> None:
        state = replace(
            initial_run_state("run_1"),
            status="completed",
            thinking="checking options",
            text="final answer",
        )
        card = render_card(state)
        thinking = card["body"]["elements"][0]
        answer = card["body"]["elements"][1]

        self.assertEqual(thinking["tag"], "collapsible_panel")
        self.assertFalse(thinking["expanded"])
        self.assertIn("思考完成", thinking["header"]["title"]["content"])
        self.assertEqual(thinking["elements"][0]["content"], "checking options")
        self.assertEqual(answer, {"tag": "markdown", "element_id": "text_1", "content": "final answer"})

    def test_running_thinking_panel_is_expanded(self) -> None:
        card = render_card(replace(initial_run_state("run_1"), thinking="checking"))
        thinking = card["body"]["elements"][0]

        self.assertEqual(thinking["tag"], "collapsible_panel")
        self.assertTrue(thinking["expanded"])
        self.assertIn("思考中", thinking["header"]["title"]["content"])

    def test_approval_card_contains_buttons(self) -> None:
        state = replace(
            initial_run_state("run_1"),
            status="pending_approval",
            pending=PendingState("p_1", "approval", "Approve?", {}),
        )
        card = render_card(state)
        self.assertEqual(
            [item["behaviors"][0]["value"]["cmd"] for item in card["body"]["elements"][-2:]],
            ["approve", "reject"],
        )
        self.assertEqual(
            [item["action_type"] for item in card["body"]["elements"][-2:]],
            ["request", "request"],
        )

    def test_pending_user_input_card_prompts_for_reply(self) -> None:
        state = replace(
            initial_run_state("run_1"),
            status="pending_user_input",
            pending=PendingState("p_1", "user_input", "Which file?", {}),
        )
        card = render_card(state)
        pending = card["body"]["elements"][-1]

        self.assertEqual(pending["element_id"], "pending")
        self.assertIn("请补充信息", pending["content"])
        self.assertIn("Which file?", pending["content"])
        self.assertIn("直接回复这条消息即可继续", pending["content"])

    def test_text_fallback_uses_error(self) -> None:
        state = replace(initial_run_state("run_1"), status="failed", error="boom")
        self.assertEqual(render_text(state), "任务失败：boom")


if __name__ == "__main__":
    unittest.main()


def _element_ids(value):
    if isinstance(value, dict):
        element_id = value.get("element_id")
        if element_id is not None:
            yield element_id
        for child in value.values():
            yield from _element_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _element_ids(child)

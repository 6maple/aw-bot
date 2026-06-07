from pathlib import Path
import unittest


FORBIDDEN_TEST_TEXT = (
    "import openai",
    "from openai",
    "import anthropic",
    "from anthropic",
    "import dashscope",
    "from dashscope",
    "generativeai",
    "gpt-",
    "claude-",
    "deepseek",
    "gemini",
    "qwen",
    "alibaba-cn",
)


class NoLiveLlmCallsTest(unittest.TestCase):
    def test_tests_do_not_reference_live_llm_sdks_or_models(self) -> None:
        offenders: list[str] = []
        tests_dir = Path(__file__).resolve().parent
        for path in tests_dir.glob("test_*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for pattern in FORBIDDEN_TEST_TEXT:
                if pattern in text and path.name != Path(__file__).name:
                    offenders.append(f"{path.name}: {pattern}")

        self.assertEqual(
            offenders,
            [],
            "Tests must use fakes/mocks and inert test model names, not live LLM SDKs or model IDs.",
        )


if __name__ == "__main__":
    unittest.main()

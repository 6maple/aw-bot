import unittest

from c_auto_bridge.cli_opencode import check_opencode_startup_capabilities
from c_auto_bridge.config_opencode import OpenCodeConfig


class OpencodeStartupCapabilityTest(unittest.TestCase):
    def test_required_capabilities_fail_when_missing(self) -> None:
        result = check_opencode_startup_capabilities(
            OpenCodeConfig(
                server_url="http://127.0.0.1:4096",
                workspace="D:/repo",
                model=None,
                agent=None,
            ),
            client_factory=lambda url: MissingPromptClient(),
        )

        self.assertEqual(
            result,
            (
                False,
                "OpenCode required capability is missing: prompt async",
            ),
        )

    def test_required_capabilities_fail_when_probe_fails(self) -> None:
        result = check_opencode_startup_capabilities(
            OpenCodeConfig(
                server_url="http://127.0.0.1:4096",
                workspace="D:/repo",
                model=None,
                agent=None,
            ),
            client_factory=lambda url: FailingHealthClient(),
        )

        self.assertEqual(
            result,
            (
                False,
                "OpenCode required capability failed: health (offline)",
            ),
        )

    def test_question_capability_is_not_enabled_without_request_schema_evidence(self) -> None:
        result = check_opencode_startup_capabilities(
            OpenCodeConfig(
                server_url="http://127.0.0.1:4096",
                workspace="D:/repo",
                model=None,
                agent=None,
            ),
            client_factory=lambda url: CompleteClient(),
        )

        self.assertEqual(
            result,
            (
                True,
                "OpenCode required capabilities are present; question capability: disabled",
            ),
        )

    def test_startup_probe_does_not_create_session_or_send_prompt(self) -> None:
        client = RecordingPromptClient()

        result = check_opencode_startup_capabilities(
            OpenCodeConfig(
                server_url="http://127.0.0.1:4096",
                workspace="D:/repo",
                model=None,
                agent=None,
            ),
            client_factory=lambda url: client,
        )

        self.assertEqual(
            result,
            (
                True,
                "OpenCode required capabilities are present; question capability: disabled",
            ),
        )
        self.assertEqual(client.create_session_calls, 0)
        self.assertEqual(client.prompt_calls, 0)
        self.assertEqual(client.message_read_calls, 0)
        self.assertEqual(client.abort_calls, 0)

    def test_configured_agent_fails_when_agent_listing_is_available_and_missing(self) -> None:
        client = MissingAgentClient()
        result = check_opencode_startup_capabilities(
            OpenCodeConfig(
                server_url="http://127.0.0.1:4096",
                workspace="D:/repo",
                model=None,
                agent="build",
            ),
            client_factory=lambda url: client,
        )

        self.assertEqual(
            result,
            (
                False,
                "OpenCode configured agent is not available: build",
            ),
        )
        self.assertEqual(client.agent_workspace, "D:/repo")

    def test_configured_model_fails_when_runtime_provider_api_reports_missing_model(self) -> None:
        result = check_opencode_startup_capabilities(
            OpenCodeConfig(
                server_url="http://127.0.0.1:4096",
                workspace="D:/repo",
                model="test-provider/test-model",
                agent=None,
            ),
            client_factory=lambda url: MissingModelClient(),
        )

        self.assertEqual(
            result,
            (
                False,
                "OpenCode model is not loaded by provider test-provider: test-model (available: other-model)",
            ),
        )


class MissingPromptClient:
    async def health(self):
        return {"healthy": True}

    async def create_session(self, *, title: str, workspace: str):
        return {"id": "session_1"}

    async def session_messages(self, *, session_id: str, workspace: str):
        return []

    async def answer_permission(self, **kwargs):
        return True

    async def abort_session(self, **kwargs):
        return True

    async def events(self, *, workspace: str):
        if workspace != "D:/repo":
            raise AssertionError("event stream probe must use configured workspace")
        if False:
            yield {}


class FailingHealthClient(MissingPromptClient):
    async def health(self):
        raise RuntimeError("offline")

    async def prompt_async(self, **kwargs):
        return True


class CompleteClient(FailingHealthClient):
    async def health(self):
        return {"healthy": True}

    async def create_session(self, *, title: str, workspace: str):
        return {"id": "session_1"}

    async def session_messages(self, *, session_id: str, workspace: str):
        return []

    async def answer_permission(self, **kwargs):
        return True

    async def answer_question(self, **kwargs):
        return True

    async def abort_session(self, **kwargs):
        return True


class MissingAgentClient(CompleteClient):
    def __init__(self) -> None:
        self.agent_workspace: str | None = None

    async def list_agents(self, *, workspace: str):
        self.agent_workspace = workspace
        return [{"name": "plan"}]


class MissingModelClient(CompleteClient):
    async def list_providers(self, *, workspace: str):
        if workspace != "D:/repo":
            raise AssertionError("model probe must use configured workspace")
        return {
            "all": [
                {
                    "id": "test-provider",
                    "models": {"other-model": {"id": "other-model"}},
                }
            ],
        }


class RecordingPromptClient(CompleteClient):
    def __init__(self) -> None:
        self.create_session_calls = 0
        self.prompt_calls = 0
        self.message_read_calls = 0
        self.abort_calls = 0

    async def create_session(self, *, title: str, workspace: str):
        self.create_session_calls += 1
        return {"id": "session_1"}

    async def prompt_async(self, **kwargs):
        self.prompt_calls += 1
        return True

    async def session_messages(self, *, session_id: str, workspace: str):
        self.message_read_calls += 1
        return []

    async def abort_session(self, **kwargs):
        self.abort_calls += 1
        return True


if __name__ == "__main__":
    unittest.main()

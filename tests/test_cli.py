import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from c_auto_bridge import cli
from c_auto_bridge.cli_opencode import check_opencode_model_available


class CliTest(unittest.TestCase):
    def test_validate_start_environment_reports_missing_codex_values(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("c_auto_bridge.cli_codex.shutil.which", return_value=None),
        ):
            checks = cli.validate_start_environment()

        messages = [message for passed, message in checks if not passed]
        self.assertIn("missing required Feishu env vars: LARK_APP_ID, LARK_APP_SECRET", messages)
        self.assertIn(
            "missing required Codex env vars: CODEX_HOME, CODEX_WORKSPACE, CODEX_MODEL, CODEX_SANDBOX, CODEX_APPROVAL_POLICY",
            messages,
        )
        self.assertIn("Codex CLI executable was not found on PATH", messages)

    def test_doctor_validates_codex_cli_and_paths_without_starting_server(self) -> None:
        with TemporaryDirectory() as tmpdir:
            env = _codex_env(tmpdir)
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli_codex.shutil.which", return_value="C:/Codex/codex.exe"),
                patch("builtins.print"),
            ):
                result = cli.doctor()
        self.assertEqual(result, 0)

    def test_start_builds_runtime_without_managing_codex_server(self) -> None:
        with TemporaryDirectory() as tmpdir:
            env = _codex_env(tmpdir)
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli_codex.shutil.which", return_value="C:/Codex/codex.exe"),
                patch("c_auto_bridge.cli.build_runtime") as build_runtime,
                patch("c_auto_bridge.cli.start_runtime") as start_runtime,
                patch("c_auto_bridge.cli.stop_runtime") as stop_runtime,
            ):
                components = object()
                build_runtime.return_value = components
                result = cli.start()
        self.assertEqual(result, 0)
        start_runtime.assert_called_once_with(components)
        stop_runtime.assert_called_once_with(components)

    def test_start_manages_opencode_server(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "workspace")
            os.makedirs(workspace)
            env = {
                "LARK_APP_ID": "app_id",
                "LARK_APP_SECRET": "app_secret",
                "C_AUTO_DEFAULT_AGENT": "opencode",
                "OPENCODE_SERVER_URL": "http://127.0.0.1:4096",
                "OPENCODE_WORKSPACE": workspace,
                "C_AUTO_DATA_DIR": os.path.join(tmpdir, "data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli_opencode.check_opencode_server_connection", side_effect=[(False, "no"), (True, "ok")]),
                patch("c_auto_bridge.cli_opencode.shutil.which", return_value="C:/OpenCode/opencode.exe"),
                patch("c_auto_bridge.cli_opencode.subprocess.Popen") as popen,
                patch("c_auto_bridge.cli.check_opencode_startup_capabilities", return_value=(True, "ok")),
                patch("c_auto_bridge.cli.build_runtime") as build_runtime,
                patch("c_auto_bridge.cli.start_runtime"),
                patch("c_auto_bridge.cli.stop_runtime"),
            ):
                process = FakeProcess()
                popen.return_value = process
                build_runtime.return_value = object()
                result = cli.start()
        self.assertEqual(result, 0)
        self.assertTrue(process.terminated)

    def test_start_reuses_running_opencode_server(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "workspace")
            os.makedirs(workspace)
            env = {
                "LARK_APP_ID": "app_id",
                "LARK_APP_SECRET": "app_secret",
                "C_AUTO_DEFAULT_AGENT": "opencode",
                "OPENCODE_SERVER_URL": "http://127.0.0.1:4096",
                "OPENCODE_WORKSPACE": workspace,
                "C_AUTO_DATA_DIR": os.path.join(tmpdir, "data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli_opencode.check_opencode_server_connection", return_value=(True, "ok")),
                patch("c_auto_bridge.cli_opencode.subprocess.Popen") as popen,
                patch("c_auto_bridge.cli.check_opencode_startup_capabilities", return_value=(True, "ok")),
                patch("c_auto_bridge.cli.build_runtime") as build_runtime,
                patch("c_auto_bridge.cli.start_runtime"),
                patch("c_auto_bridge.cli.stop_runtime"),
            ):
                build_runtime.return_value = object()
                result = cli.start()
        self.assertEqual(result, 0)
        popen.assert_not_called()

    def test_start_stops_when_opencode_model_is_not_loaded(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "workspace")
            os.makedirs(workspace)
            env = {
                "LARK_APP_ID": "app_id",
                "LARK_APP_SECRET": "app_secret",
                "C_AUTO_DEFAULT_AGENT": "opencode",
                "OPENCODE_SERVER_URL": "http://127.0.0.1:4096",
                "OPENCODE_WORKSPACE": workspace,
                "OPENCODE_MODEL": "test-provider/test-model",
                "C_AUTO_DATA_DIR": os.path.join(tmpdir, "data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli.ensure_opencode_server", return_value=None),
                patch(
                    "c_auto_bridge.cli.check_opencode_startup_capabilities",
                    return_value=(False, "OpenCode provider is not loaded: test-provider"),
                ),
                patch("c_auto_bridge.cli.build_runtime") as build_runtime,
                patch("builtins.print") as print_,
            ):
                result = cli.start()
        self.assertEqual(result, 1)
        build_runtime.assert_not_called()
        print_.assert_called_once_with("[FAIL] OpenCode provider is not loaded: test-provider")

    def test_start_stops_when_opencode_startup_capability_is_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            workspace = os.path.join(tmpdir, "workspace")
            os.makedirs(workspace)
            env = {
                "LARK_APP_ID": "app_id",
                "LARK_APP_SECRET": "app_secret",
                "C_AUTO_DEFAULT_AGENT": "opencode",
                "OPENCODE_SERVER_URL": "http://127.0.0.1:4096",
                "OPENCODE_WORKSPACE": workspace,
                "C_AUTO_DATA_DIR": os.path.join(tmpdir, "data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli.ensure_opencode_server", return_value=None),
                patch(
                    "c_auto_bridge.cli.check_opencode_startup_capabilities",
                    return_value=(False, "OpenCode required capability is missing: prompt async"),
                ),
                patch("c_auto_bridge.cli.build_runtime") as build_runtime,
                patch("builtins.print") as print_,
            ):
                result = cli.start()
        self.assertEqual(result, 1)
        build_runtime.assert_not_called()
        print_.assert_called_once_with("[FAIL] OpenCode required capability is missing: prompt async")

    def test_start_returns_one_when_environment_is_invalid(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("c_auto_bridge.cli_codex.shutil.which", return_value=None),
        ):
            self.assertEqual(cli.start(), 1)

    def test_opencode_model_check_accepts_loaded_model(self) -> None:
        result = check_opencode_model_available(
            "http://127.0.0.1:4096",
            "test-provider/test-model",
            workspace="D:/repo",
            client_factory=lambda url: FakeOpencodeConfigClient(
                {
                    "all": [
                        {
                            "id": "test-provider",
                            "models": {"test-model": {"id": "test-model"}},
                        }
                    ]
                }
            ),
        )

        self.assertEqual(result, (True, "OpenCode model is available: test-provider/test-model"))

    def test_opencode_model_check_reports_unloaded_provider(self) -> None:
        result = check_opencode_model_available(
            "http://127.0.0.1:4096",
            "test-provider/test-model",
            workspace="D:/repo",
            client_factory=lambda url: FakeOpencodeConfigClient(
                {
                    "all": [
                        {
                            "id": "opencode",
                            "models": {"other-model": {}},
                        }
                    ]
                }
            ),
        )

        self.assertEqual(
            result,
            (
                False,
                "OpenCode provider is not loaded: test-provider (available providers: opencode)",
            ),
        )

    def test_opencode_model_check_accepts_legacy_provider_payload_as_fallback(self) -> None:
        result = check_opencode_model_available(
            "http://127.0.0.1:4096",
            "test-provider/test-model",
            workspace="D:/repo",
            client_factory=lambda url: FakeOpencodeConfigClient(
                {
                    "providers": [
                        {
                            "id": "test-provider",
                            "models": {"test-model": {"id": "test-model"}},
                        }
                    ]
                }
            ),
        )

        self.assertEqual(result, (True, "OpenCode model is available: test-provider/test-model"))


class FakeProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


class FakeOpencodeConfigClient:
    def __init__(self, payload):
        self.payload = payload

    async def list_providers(self, *, workspace: str):
        if workspace != "D:/repo":
            raise AssertionError("model check must use the requested workspace")
        return self.payload


def _codex_env(tmpdir: str) -> dict[str, str]:
    home = os.path.join(tmpdir, "codex-home")
    workspace = os.path.join(tmpdir, "workspace")
    os.makedirs(home)
    os.makedirs(workspace)
    return {
        "LARK_APP_ID": "app_id",
        "LARK_APP_SECRET": "app_secret",
        "CODEX_HOME": home,
        "CODEX_WORKSPACE": workspace,
        "CODEX_MODEL": "test-model",
        "CODEX_SANDBOX": "workspace-write",
        "CODEX_APPROVAL_POLICY": "on-request",
        "C_AUTO_DATA_DIR": os.path.join(tmpdir, "data"),
    }


if __name__ == "__main__":
    unittest.main()

import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from c_auto_bridge import cli
from c_auto_bridge.cli_opencode import check_opencode_model_available


class CliTest(unittest.TestCase):
    def test_validate_start_environment_requires_only_lark_and_codex_cli_by_default(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("c_auto_bridge.cli_codex.shutil.which", return_value=None),
        ):
            checks = cli.validate_start_environment()

        messages = [message for passed, message in checks if not passed]
        self.assertIn("missing required Feishu env vars: LARK_APP_ID, LARK_APP_SECRET", messages)
        self.assertIn("Codex CLI executable was not found on PATH", messages)
        self.assertFalse(any("missing required Codex env vars" in message for message in messages))

    def test_validate_start_environment_accepts_default_codex_stdio_config(self) -> None:
        with TemporaryDirectory() as tmpdir:
            env = {
                "LARK_APP_ID": "app_id",
                "LARK_APP_SECRET": "app_secret",
                "C_AUTO_DATA_DIR": os.path.join(tmpdir, "data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli_codex.shutil.which", return_value="C:/Codex/codex.exe"),
            ):
                checks = cli.validate_start_environment()

        self.assertTrue(all(passed for passed, _ in checks), checks)
        self.assertIn(
            (True, "Codex App Server connection path: default stdio (codex app-server --listen stdio://)"),
            checks,
        )
        self.assertIn(
            (True, "Codex approval policy is on-request (interactive bridge default)"),
            checks,
        )

    def test_validate_start_environment_reports_explicit_codex_websocket_override(self) -> None:
        with TemporaryDirectory() as tmpdir:
            env = {
                "LARK_APP_ID": "app_id",
                "LARK_APP_SECRET": "app_secret",
                "CODEX_APP_SERVER_URL": "ws://127.0.0.1:4500",
                "C_AUTO_DATA_DIR": os.path.join(tmpdir, "data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli_codex.shutil.which", return_value="C:/Codex/codex.exe"),
            ):
                checks = cli.validate_start_environment()

        self.assertTrue(all(passed for passed, _ in checks), checks)
        self.assertIn(
            (True, "Codex App Server connection path: explicit WebSocket override (ws://127.0.0.1:4500)"),
            checks,
        )
        messages = [message for _, message in checks]
        self.assertIn("Codex home path is not configured; Codex default will be used", messages)
        self.assertIn("workspace path is not configured; bridge process cwd will be used", messages)
        self.assertIn("Codex approval policy is on-request (interactive bridge default)", messages)
        self.assertFalse(any("missing required Codex env vars" in message for message in messages))

    def test_validate_start_environment_rejects_unsupported_codex_sandbox(self) -> None:
        with TemporaryDirectory() as tmpdir:
            env = {
                "LARK_APP_ID": "app_id",
                "LARK_APP_SECRET": "app_secret",
                "CODEX_SANDBOX": "danger-full-access",
                "C_AUTO_DATA_DIR": os.path.join(tmpdir, "data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli_codex.shutil.which", return_value="C:/Codex/codex.exe"),
            ):
                checks = cli.validate_start_environment()

        messages = [message for passed, message in checks if not passed]
        self.assertIn(
            "unsupported Codex sandbox: danger-full-access (only workspace-write is supported)",
            messages,
        )

    def test_validate_start_environment_rejects_unsupported_codex_approval_policy(self) -> None:
        with TemporaryDirectory() as tmpdir:
            env = {
                "LARK_APP_ID": "app_id",
                "LARK_APP_SECRET": "app_secret",
                "CODEX_APPROVAL_POLICY": "sometimes",
                "C_AUTO_DATA_DIR": os.path.join(tmpdir, "data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("c_auto_bridge.cli_codex.shutil.which", return_value="C:/Codex/codex.exe"),
            ):
                checks = cli.validate_start_environment()

        messages = [message for passed, message in checks if not passed]
        self.assertIn(
            "unsupported Codex approval policy: sometimes (supported: never, on-request, untrusted)",
            messages,
        )

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

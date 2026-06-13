import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from c_auto_bridge.config_codex import load_codex_config


class CodexConfigTest(unittest.TestCase):
    def test_load_codex_config_uses_defaults_without_optional_overrides(self) -> None:
        with TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {}, clear=True), patch("os.getcwd", return_value=tmpdir):
                config = load_codex_config()

        self.assertIsNone(config.app_server_url)
        self.assertIsNone(config.home)
        self.assertEqual(config.workspace, tmpdir)
        self.assertIsNone(config.model)
        self.assertEqual(config.sandbox, "workspace-write")
        self.assertEqual(config.approval_policy, "on-request")

    def test_load_codex_config_applies_explicit_overrides(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home = os.path.join(tmpdir, "codex-home")
            workspace = os.path.join(tmpdir, "workspace")
            env = {
                "CODEX_APP_SERVER_URL": "ws://127.0.0.1:4500",
                "CODEX_CLI_PATH": "/usr/local/bin/codex",
                "CODEX_HOME": home,
                "CODEX_WORKSPACE": workspace,
                "CODEX_MODEL": "test-model",
                "CODEX_SANDBOX": "workspace-write",
                "CODEX_APPROVAL_POLICY": "on-request",
            }
            with patch.dict(os.environ, env, clear=True):
                config = load_codex_config()

        self.assertEqual(config.app_server_url, "ws://127.0.0.1:4500")
        self.assertEqual(config.cli_path, "/usr/local/bin/codex")
        self.assertEqual(config.home, home)
        self.assertEqual(config.workspace, workspace)
        self.assertEqual(config.model, "test-model")
        self.assertEqual(config.sandbox, "workspace-write")
        self.assertEqual(config.approval_policy, "on-request")

    def test_load_codex_config_websocket_override_does_not_require_optional_overrides(self) -> None:
        with TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"CODEX_APP_SERVER_URL": "ws://127.0.0.1:4500"}, clear=True),
                patch("os.getcwd", return_value=tmpdir),
            ):
                config = load_codex_config()

        self.assertEqual(config.app_server_url, "ws://127.0.0.1:4500")
        self.assertIsNone(config.home)
        self.assertEqual(config.workspace, tmpdir)
        self.assertIsNone(config.model)
        self.assertEqual(config.sandbox, "workspace-write")
        self.assertEqual(config.approval_policy, "on-request")

    def test_load_codex_config_treats_empty_optional_overrides_as_unset(self) -> None:
        with TemporaryDirectory() as tmpdir:
            env = {
                "CODEX_APP_SERVER_URL": "",
                "CODEX_CLI_PATH": "",
                "CODEX_HOME": "",
                "CODEX_MODEL": "",
                "CODEX_APPROVAL_POLICY": "",
            }
            with patch.dict(os.environ, env, clear=True), patch("os.getcwd", return_value=tmpdir):
                config = load_codex_config()

        self.assertIsNone(config.app_server_url)
        self.assertIsNone(config.cli_path)
        self.assertIsNone(config.home)
        self.assertIsNone(config.model)
        self.assertEqual(config.approval_policy, "on-request")

    def test_load_codex_config_rejects_unsupported_sandbox(self) -> None:
        with patch.dict(os.environ, {"CODEX_SANDBOX": "read-only"}, clear=True):
            with self.assertRaisesRegex(ValueError, "unsupported Codex sandbox: read-only"):
                load_codex_config()

    def test_load_codex_config_rejects_unsupported_approval_policy(self) -> None:
        with patch.dict(os.environ, {"CODEX_APPROVAL_POLICY": "sometimes"}, clear=True):
            with self.assertRaisesRegex(ValueError, "unsupported Codex approval policy: sometimes"):
                load_codex_config()


if __name__ == "__main__":
    unittest.main()

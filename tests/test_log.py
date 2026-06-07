import logging
import os
import unittest
from unittest.mock import patch

from c_auto_bridge.utils.log import configure_logging


class LogTest(unittest.TestCase):
    def tearDown(self) -> None:
        logging.basicConfig(level=logging.WARNING, force=True)

    def test_configure_logging_defaults_to_info(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            configure_logging()

        self.assertEqual(logging.getLogger().level, logging.INFO)

    def test_configure_logging_uses_env_level(self) -> None:
        with patch.dict(os.environ, {"C_AUTO_LOG_LEVEL": "debug"}, clear=True):
            configure_logging()

        self.assertEqual(logging.getLogger().level, logging.DEBUG)

    def test_configure_logging_rejects_empty_level(self) -> None:
        with patch.dict(os.environ, {"C_AUTO_LOG_LEVEL": ""}, clear=True):
            with self.assertRaisesRegex(ValueError, "must not be empty"):
                configure_logging()

    def test_configure_logging_rejects_unknown_level(self) -> None:
        with patch.dict(os.environ, {"C_AUTO_LOG_LEVEL": "verbose"}, clear=True):
            with self.assertRaisesRegex(ValueError, "must be one of"):
                configure_logging()


if __name__ == "__main__":
    unittest.main()

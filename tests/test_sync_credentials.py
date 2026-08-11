"""A credential failure must be visible somewhere -- the mirror runs
unattended under pythonw.exe, which has no console, so sync.log is the only
channel that exists. `SystemExit` inherits from BaseException, not
Exception, so it slips past `main()`'s `except Exception` and leaves no
trace at all. These tests pin token() to a catchable exception type and pin
main() to actually logging it.
"""
import importlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import sync  # noqa: E402


class ReloadedSyncTest(unittest.TestCase):
    """Base: points sync.DATA at a private temp dir via TICKTICK_SYNC_DATA,
    so nothing here ever touches the real %LOCALAPPDATA%\\ticktick-sync\\.env.
    """

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self._old_env = os.environ.get("TICKTICK_SYNC_DATA")
        os.environ["TICKTICK_SYNC_DATA"] = self.data_dir
        importlib.reload(sync)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("TICKTICK_SYNC_DATA", None)
        else:
            os.environ["TICKTICK_SYNC_DATA"] = self._old_env
        importlib.reload(sync)


class TokenTest(ReloadedSyncTest):
    def test_a_missing_env_file_raises_config_error_not_system_exit(self):
        with self.assertRaises(sync.ConfigError):
            sync.token()

    def test_an_env_file_without_a_recognised_variable_raises_config_error(self):
        env_path = os.path.join(self.data_dir, ".env")
        with open(env_path, "w", encoding="utf-8") as handle:
            handle.write("SOMETHING_ELSE=value\n")

        with self.assertRaises(sync.ConfigError):
            sync.token()

    def test_config_error_is_an_exception_subclass(self):
        """The entire point of the fix: `except Exception` in main() must
        actually see this, which bare SystemExit (a BaseException) does not."""
        self.assertTrue(issubclass(sync.ConfigError, Exception))
        self.assertFalse(issubclass(sync.ConfigError, SystemExit))


class MainLogsCredentialFailureTest(ReloadedSyncTest):
    def test_a_missing_credential_is_logged_not_silently_dropped(self):
        # The GitHub read is not under test here and must not touch the
        # network or call the real `gh`; it is stubbed to succeed so the run
        # reaches token(), which is the code path under test.
        with mock.patch.object(sync.github, "read_desired", return_value={}):
            exit_code = sync.main(["--quiet"])

        self.assertEqual(1, exit_code)
        log_path = os.path.join(self.data_dir, "sync.log")
        self.assertTrue(os.path.exists(log_path), "sync.log was never written")
        with open(log_path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("ConfigError", content)


if __name__ == "__main__":
    unittest.main()

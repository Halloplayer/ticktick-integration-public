"""FINDING I4: everything that can fail must fail INSIDE the logged path.

The mirror runs unattended under pythonw.exe, which has no console and no
stderr anyone will ever see. `sync.log` is the only channel that exists. Work
done before `main()`'s try/except -- reading config.toml, creating the data
directory -- therefore fails into total silence: the run dies, nothing is
written anywhere, and the list quietly goes stale while looking healthy. That
is the same failure mode the ConfigError fix closed one line further down.

Worse still is the module-level `os.environ["LOCALAPPDATA"]` lookup: a KeyError
there kills the process during import, before `main()` exists at all.
"""
import importlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import sync  # noqa: E402


class ReloadedSyncTest(unittest.TestCase):
    """Points sync.DATA at a private temp dir via TICKTICK_SYNC_DATA, so
    nothing here touches the real, LIVE %LOCALAPPDATA%\\ticktick-sync.
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

    def log_text(self):
        path = os.path.join(self.data_dir, "sync.log")
        self.assertTrue(os.path.exists(path), "sync.log was never written")
        with open(path, encoding="utf-8") as handle:
            return handle.read()


class ConfigFailureIsLoggedTest(ReloadedSyncTest):
    def test_a_config_that_does_not_exist_is_logged_not_silently_fatal(self):
        missing = os.path.join(self.data_dir, "there-is-no-such-file.toml")

        exit_code = sync.main(["--quiet", "--config", missing])

        self.assertEqual(1, exit_code)
        self.assertIn("FileNotFoundError", self.log_text())

    def test_a_corrupt_config_is_logged(self):
        """The exact case in the finding: a broken config.toml under pythonw."""
        bad = os.path.join(self.data_dir, "config.toml")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("this is not = = valid toml\n")

        exit_code = sync.main(["--quiet", "--config", bad])

        self.assertEqual(1, exit_code)
        self.assertIn("ERROR", self.log_text())

    def test_the_log_is_written_even_when_the_data_directory_did_not_exist(self):
        """Directory creation moved inside the handler, so it must not be the
        thing that stops the log from being written."""
        fresh = os.path.join(self.data_dir, "not-created-yet")
        os.environ["TICKTICK_SYNC_DATA"] = fresh
        importlib.reload(sync)

        exit_code = sync.main(["--quiet", "--config",
                               os.path.join(fresh, "missing.toml")])

        self.assertEqual(1, exit_code)
        self.assertTrue(os.path.exists(os.path.join(fresh, "sync.log")))


class ImportMustNotRaiseTest(unittest.TestCase):
    """A module-level KeyError is unrecoverable: there is no handler yet, no
    log file, and under pythonw.exe no console either."""

    def setUp(self):
        self._saved = {name: os.environ.get(name)
                       for name in ("TICKTICK_SYNC_DATA", "LOCALAPPDATA")}

    def tearDown(self):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        importlib.reload(sync)

    def test_importing_without_localappdata_does_not_raise(self):
        os.environ.pop("TICKTICK_SYNC_DATA", None)
        os.environ.pop("LOCALAPPDATA", None)

        importlib.reload(sync)  # must not raise

        self.assertTrue(str(sync.DATA), "DATA must still resolve to something")

    def test_the_explicit_override_still_wins(self):
        target = tempfile.mkdtemp()
        os.environ["TICKTICK_SYNC_DATA"] = target
        os.environ.pop("LOCALAPPDATA", None)

        importlib.reload(sync)

        self.assertEqual(os.path.normcase(target), os.path.normcase(str(sync.DATA)))


if __name__ == "__main__":
    unittest.main()

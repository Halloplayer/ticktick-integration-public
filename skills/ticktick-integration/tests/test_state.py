"""Tests for the cache. It is fast, not true -- but silence about its own
failure is what makes it dangerous."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import state  # noqa: E402


class StateTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "state.json")

    def test_a_missing_file_reads_as_a_fresh_start(self):
        """No file at all is the one honest zero: nothing has run here yet."""
        self.assertEqual(0, state.load_state(self.path)["last_count"])

    def test_what_is_saved_comes_back(self):
        state.save_state(self.path, {"last_count": 18, "ids": {"gh-1": "t1"}})

        self.assertEqual("t1", state.load_state(self.path)["ids"]["gh-1"])

    def test_a_crashed_save_leaves_no_partial_file(self):
        """Same reason as everywhere: half-written is worse than not written.

        The whole point is that nothing is left behind -- so what follows is a
        MISSING file, the legitimate fresh start, not an unreadable one.
        """
        with self.assertRaises(TypeError):
            state.save_state(self.path, {"last_count": 1, "ids": {object(): "x"}})

        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(0, state.load_state(self.path)["last_count"])


class UnreadableStateTest(unittest.TestCase):
    """FINDING I5: "absent" and "unreadable" are not the same answer.

    Both used to yield `last_count = 0`, and a zero `last_count` DISARMS the
    collapse guard -- `guard_collapse` only refuses a fall from non-zero. A
    state.json that could not be read for one run therefore turned the single
    safeguard against wiping the user's list into a no-op, at exactly the
    moment something was already wrong. A sharing violation against the
    `os.replace` in `save_state` is enough to trigger it.

    A file that is not there is a fresh start. A file that is there but cannot
    be read means the run does not know what it needs to know, and must refuse
    rather than proceed unguarded.
    """

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "state.json")

    def test_a_corrupt_file_raises_rather_than_reporting_a_fresh_start(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{broken")

        with self.assertRaises(state.StateUnreadable):
            state.load_state(self.path)

    def test_a_file_that_cannot_be_opened_raises(self):
        """The sharing violation, simulated: the file is there, the read fails."""
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{}")

        with mock.patch("builtins.open", side_effect=PermissionError("in use")):
            with self.assertRaises(state.StateUnreadable):
                state.load_state(self.path)

    def test_a_file_holding_something_other_than_an_object_raises(self):
        """A JSON list parses perfectly well and is still not a state file."""
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("[1, 2, 3]")

        with self.assertRaises(state.StateUnreadable):
            state.load_state(self.path)

    def test_the_error_names_the_file_so_it_can_be_deleted(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{broken")

        with self.assertRaises(state.StateUnreadable) as caught:
            state.load_state(self.path)

        self.assertIn("state.json", str(caught.exception))

    def test_it_is_an_exception_not_a_base_exception(self):
        """main() catches `Exception`; anything outside that leaves no line in
        sync.log, which under pythonw.exe means no trace anywhere at all."""
        self.assertTrue(issubclass(state.StateUnreadable, Exception))


if __name__ == "__main__":
    unittest.main()

"""Tests for the cache. It is fast, not true."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import state  # noqa: E402


class StateTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "state.json")

    def test_a_missing_file_reads_as_a_fresh_start(self):
        self.assertEqual(0, state.load_state(self.path)["last_count"])

    def test_a_corrupt_file_reads_as_a_fresh_start_rather_than_crashing(self):
        """A broken cache must not halt the run -- being rebuildable is its
        whole nature."""
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{broken")

        self.assertEqual(0, state.load_state(self.path)["last_count"])

    def test_what_is_saved_comes_back(self):
        state.save_state(self.path, {"last_count": 18, "ids": {"gh-1": "t1"}})

        self.assertEqual("t1", state.load_state(self.path)["ids"]["gh-1"])

    def test_a_crashed_save_leaves_no_partial_file(self):
        """Same reason as everywhere: half-written is worse than not written."""
        with self.assertRaises(TypeError):
            state.save_state(self.path, {"last_count": 1, "ids": {object(): "x"}})

        self.assertEqual(0, state.load_state(self.path)["last_count"])


if __name__ == "__main__":
    unittest.main()

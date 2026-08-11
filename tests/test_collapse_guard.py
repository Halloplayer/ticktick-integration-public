"""The guard against the one bug that destroys data.

A failed read looks exactly like "nothing is open any more". A naive mirror
would tick off the entire list in response.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import models  # noqa: E402
from ticktick_sync.reconcile import CollapseRefused, guard_collapse  # noqa: E402


def item(key):
    return models.Item(key=key, title="T", body=models.marker(key))


class CollapseTest(unittest.TestCase):
    def test_a_collapse_from_many_to_zero_is_refused(self):
        with self.assertRaises(CollapseRefused):
            guard_collapse({}, last_count=18)

    def test_a_genuinely_empty_first_run_is_allowed(self):
        """On a first run there is no previous state, so empty is normal."""
        guard_collapse({}, last_count=0)

    def test_a_non_empty_set_is_always_allowed(self):
        guard_collapse({"gh-1": item("gh-1")}, last_count=18)

    def test_shrinking_without_reaching_zero_is_allowed(self):
        """Real work closes items. Only the fall to zero is suspicious."""
        guard_collapse({"gh-1": item("gh-1")}, last_count=18)

    def test_the_refusal_says_how_to_recover(self):
        """A guard that leaves you stuck gets switched off instead of understood."""
        with self.assertRaises(CollapseRefused) as caught:
            guard_collapse({}, last_count=18)

        self.assertIn("state.json", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

"""The guard against the one bug that destroys data.

A failed read looks exactly like "nothing is open any more". A naive mirror
would tick off the entire list in response.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import github, models  # noqa: E402
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
        """Real work closes items. Only the fall to zero is suspicious.

        A real shrink, not a copy of the test above: fifteen desired entries
        where there were eighteen. Three items genuinely got closed, and the
        guard must not stand in the way of that.
        """
        fifteen = {"gh-%d" % n: item("gh-%d" % n) for n in range(15)}

        guard_collapse(fifteen, last_count=18)

    def test_the_guard_cannot_catch_a_partial_collapse(self):
        """FINDING C1, stated as the guard's own limit -- and the reason the
        guard is not the defence against a malformed item list.

        Twelve of the fifteen desired entries come from `open-items.toml`. A
        file that parses but has the wrong shape yields zero of them, so
        desired falls 15 -> 3 and twelve real tasks in the user's own list get
        completed. The guard waves that through, exactly as pinned here, BY
        DESIGN: it cannot tell a partial read failure from real progress. The
        refusal therefore has to happen earlier, in `toml_to_items`.
        """
        three = {"gh-%d" % n: item("gh-%d" % n) for n in range(3)}

        guard_collapse(three, last_count=15)  # allowed -- must not raise

    def test_a_wrongly_shaped_item_file_never_reaches_the_guard(self):
        """The C1 regression beside it: the shrink the guard cannot see must be
        impossible to produce in the first place. Full coverage of the shapes
        lives in `test_github.FileShapeTest`."""
        with self.assertRaises(github.GitHubReadFailed):
            github.toml_to_items("version = 1\n")  # truncated: no items table

    def test_the_refusal_says_how_to_recover(self):
        """A guard that leaves you stuck gets switched off instead of understood."""
        with self.assertRaises(CollapseRefused) as caught:
            guard_collapse({}, last_count=18)

        self.assertIn("state.json", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

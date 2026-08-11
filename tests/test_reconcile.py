"""Tests for the reconcile step -- the heart, with no network.

The mirror has exactly one rule: the list shows what the repo says.
Everything here checks a consequence of that rule.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import models  # noqa: E402
from ticktick_sync.reconcile import reconcile  # noqa: E402


def item(key, title="Title", body="", priority=0):
    return models.Item(key=key, title=title, body=body or models.marker(key), priority=priority)


def task(key, task_id="t1", title="Title", body=None, priority=0, completed=False):
    return models.Task(key=key, task_id=task_id, title=title,
                       body=models.marker(key) if body is None else body,
                       priority=priority, completed=completed)


class ReconcileTest(unittest.TestCase):
    def test_a_desired_item_with_no_task_is_created(self):
        self.assertEqual([models.Create(item("gh-1"))], reconcile({"gh-1": item("gh-1")}, {}))

    def test_an_unchanged_pair_produces_nothing(self):
        self.assertEqual([], reconcile({"gh-1": item("gh-1")}, {"gh-1": task("gh-1")}))

    def test_a_changed_title_produces_an_update(self):
        actions = reconcile({"gh-1": item("gh-1", title="new")},
                            {"gh-1": task("gh-1", title="old")})

        self.assertEqual([models.Update("t1", item("gh-1", title="new"))], actions)

    def test_a_changed_priority_produces_an_update(self):
        actions = reconcile({"gh-1": item("gh-1", priority=5)},
                            {"gh-1": task("gh-1", priority=3)})

        self.assertEqual(1, len(actions))
        self.assertIsInstance(actions[0], models.Update)

    def test_a_task_whose_source_is_gone_is_completed(self):
        self.assertEqual([models.Complete("t1", "gh-1")], reconcile({}, {"gh-1": task("gh-1")}))

    def test_an_already_completed_orphan_is_left_alone(self):
        """Otherwise every run would re-send the same completion forever."""
        self.assertEqual([], reconcile({}, {"gh-1": task("gh-1", completed=True)}))


class RepoWinsTest(unittest.TestCase):
    """Ticked off by hand while the source is still open.

    Task 1 measured that a completed task VANISHES from the current state --
    TickTick's project-data endpoint returns open tasks only. So the interesting
    case is not "present but completed", it is "gone entirely, and we remember
    having made it".
    """

    def test_a_vanished_task_we_remember_is_reopened_not_recreated(self):
        actions = reconcile({"gh-1": item("gh-1")}, {}, known_ids={"gh-1": "t1"})

        self.assertEqual([models.Reopen("t1", item("gh-1"))], actions)

    def test_a_vanished_task_we_do_not_remember_is_created(self):
        """Without state.json we cannot know the old id. Creating is the
        degraded-but-correct fallback: the user gets their task back."""
        actions = reconcile({"gh-1": item("gh-1")}, {}, known_ids={})

        self.assertEqual([models.Create(item("gh-1"))], actions)

    def test_a_visible_task_is_never_reopened_even_if_remembered(self):
        """Remembering an id must not turn an ordinary no-op into a write."""
        actions = reconcile({"gh-1": item("gh-1")}, {"gh-1": task("gh-1")},
                            known_ids={"gh-1": "t1"})

        self.assertEqual([], actions)


class IdempotencyTest(unittest.TestCase):
    def test_applying_the_result_twice_produces_nothing_the_second_time(self):
        desired = {"gh-1": item("gh-1", title="T")}
        self.assertEqual(1, len(reconcile(desired, {})))

        current = {"gh-1": task("gh-1", title="T", body=models.marker("gh-1"))}

        self.assertEqual([], reconcile(desired, current))

    def test_actions_are_ordered_creates_updates_completes(self):
        """A fixed order makes a run reproducible."""
        desired = {"gh-2": item("gh-2"), "gh-3": item("gh-3", title="new")}
        current = {"gh-3": task("gh-3", task_id="t3", title="old"),
                   "gh-9": task("gh-9", task_id="t9")}

        kinds = [type(a).__name__ for a in reconcile(desired, current)]

        self.assertEqual(["Create", "Update", "Complete"], kinds)


if __name__ == "__main__":
    unittest.main()

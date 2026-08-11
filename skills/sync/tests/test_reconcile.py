"""Tests for the reconcile step -- the heart, with no network.

The mirror has exactly one rule: the list shows what the repo says.
Everything here checks a consequence of that rule.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import models  # noqa: E402
from reconcile import reconcile  # noqa: E402


def item(key, title="Title", body="", tags=()):
    return models.Item(key=key, title=title, body=body or models.marker(key),
                       tags=models.tag_set(tags))


def task(key, task_id="t1", title="Title", body=None, tags=(), completed=False, priority=0):
    return models.Task(key=key, task_id=task_id, title=title,
                       body=models.marker(key) if body is None else body,
                       tags=models.tag_set(tags), completed=completed, priority=priority)


class ReconcileTest(unittest.TestCase):
    def test_a_desired_item_with_no_task_is_created(self):
        self.assertEqual([models.Create(item("gh-1"))], reconcile({"gh-1": item("gh-1")}, {}))

    def test_an_unchanged_pair_produces_nothing(self):
        self.assertEqual([], reconcile({"gh-1": item("gh-1")}, {"gh-1": task("gh-1")}))

    def test_a_changed_title_produces_an_update(self):
        actions = reconcile({"gh-1": item("gh-1", title="new")},
                            {"gh-1": task("gh-1", title="old")})

        self.assertEqual([models.Update("t1", item("gh-1", title="new"))], actions)

    def test_a_changed_tag_produces_an_update(self):
        actions = reconcile({"gh-1": item("gh-1", tags=["P1"])},
                            {"gh-1": task("gh-1", tags=["P2"])})

        self.assertEqual(1, len(actions))
        self.assertIsInstance(actions[0], models.Update)

    def test_a_task_whose_source_is_gone_is_completed(self):
        self.assertEqual([models.Complete("t1", "gh-1")], reconcile({}, {"gh-1": task("gh-1")}))

    def test_an_already_completed_orphan_is_left_alone(self):
        """Otherwise every run would re-send the same completion forever."""
        self.assertEqual([], reconcile({}, {"gh-1": task("gh-1", completed=True)}))


class StalePriorityTest(unittest.TestCase):
    """Sending `priority: 0` only helps if something makes us send anything.

    Nine live tasks were created before tags existed and still carry their old
    priority flags. Everything else about them now matches the repo, so
    reconcile produces no action for them, so no payload is ever sent, so the
    explicit zero never reaches them and the flags survive forever. The write
    fix and this comparison are two halves of one repair.

    This is not "using priorities": the mirror asserts there is no priority,
    and a task that disagrees has drifted from what the repo says.
    """

    def test_a_task_still_carrying_a_priority_is_updated_back_to_none(self):
        actions = reconcile({"gh-1": item("gh-1")}, {"gh-1": task("gh-1", priority=3)})

        self.assertEqual([models.Update("t1", item("gh-1"))], actions)

    def test_a_task_at_priority_zero_produces_nothing(self):
        """And once cleared it must stay quiet -- otherwise this repair
        becomes its own churn loop, rewriting all fifteen every five minutes."""
        self.assertEqual([], reconcile({"gh-1": item("gh-1")}, {"gh-1": task("gh-1", priority=0)}))


class TagChurnTest(unittest.TestCase):
    """The most important test in the tag rework.

    TickTick stores a task's tags as their LOWERCASE names: send `["P1"]` on
    create and the account holds `["p1"]`. An update, by contrast, echoes back
    whatever case it was sent. So a comparison that respected case -- or order,
    since the API returns a list -- would find a difference on every single run
    and rewrite all fifteen tasks every five minutes, forever. Comparing a
    frozenset of lowercased names is what makes the mirror quiet.
    """

    def test_tags_differing_only_in_case_produce_no_action(self):
        actions = reconcile({"oi-x": item("oi-x", tags=["Draft", "P1"])},
                            {"oi-x": task("oi-x", tags=["draft", "p1"])})

        self.assertEqual([], actions)

    def test_tags_differing_only_in_order_produce_no_action(self):
        actions = reconcile({"oi-x": item("oi-x", tags=["Draft", "P1"])},
                            {"oi-x": task("oi-x", tags=["P1", "Draft"])})

        self.assertEqual([], actions)

    def test_tags_differing_in_case_and_order_at_once_produce_no_action(self):
        """Exactly what the live list returns the run after a create."""
        actions = reconcile({"oi-x": item("oi-x", tags=["Draft", "P1"])},
                            {"oi-x": task("oi-x", tags=["p1", "draft"])})

        self.assertEqual([], actions)

    def test_a_genuinely_different_tag_set_still_produces_an_update(self):
        """The quiet must not be bought by comparing nothing at all."""
        actions = reconcile({"oi-x": item("oi-x", tags=["Draft", "P1"])},
                            {"oi-x": task("oi-x", tags=["draft"])})

        self.assertEqual(1, len(actions))
        self.assertIsInstance(actions[0], models.Update)


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

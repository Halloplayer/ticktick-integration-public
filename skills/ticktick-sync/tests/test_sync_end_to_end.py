"""The whole circle against a fake TickTick -- no network."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import models, state, sync_core, ticktick  # noqa: E402


class FakeClient:
    def __init__(self, tasks=None):
        self.tasks = tasks or {}
        self.created, self.updated, self.completed = [], [], []

    def resolve_list(self, name, list_id=None):
        return "p1"

    def read_tasks(self, project_id):
        return dict(self.tasks)

    def create(self, project_id, item):
        self.created.append(item.key)

    def update(self, project_id, task_id, item):
        self.updated.append(item.key)

    def complete(self, project_id, task_id):
        self.completed.append(task_id)


def item(key):
    return models.Item(key=key, title="T " + key, body=models.marker(key))


class CircleTest(unittest.TestCase):
    def setUp(self):
        self.state_path = os.path.join(tempfile.mkdtemp(), "state.json")

    def test_a_first_run_creates_every_desired_item(self):
        client = FakeClient()

        result = sync_core.run_sync({"list_name": "L"}, client,
                                    {"gh-1": item("gh-1")}, self.state_path)

        self.assertEqual(["gh-1"], client.created)
        self.assertEqual(1, result["created"])

    def test_a_second_identical_run_changes_nothing(self):
        client = FakeClient(tasks={"gh-1": models.Task(
            key="gh-1", task_id="t1", title="T gh-1", body=models.marker("gh-1"))})

        sync_core.run_sync({"list_name": "L"}, client, {"gh-1": item("gh-1")}, self.state_path)

        self.assertEqual([], client.created)
        self.assertEqual([], client.updated)

    def test_a_collapse_to_zero_completes_nothing(self):
        """The most important test in this project."""
        client = FakeClient(tasks={"gh-1": models.Task(
            key="gh-1", task_id="t1", title="T gh-1", body=models.marker("gh-1"))})
        sync_core.run_sync({"list_name": "L"}, client, {"gh-1": item("gh-1")}, self.state_path)

        with self.assertRaises(Exception):
            sync_core.run_sync({"list_name": "L"}, client, {}, self.state_path)

        self.assertEqual([], client.completed)

    def test_a_real_shrink_completes_exactly_what_is_gone(self):
        """Eighteen were open, two still are. Sixteen get ticked off -- and
        nothing gets created, because the two survivors are already there.

        The counterpart to the collapse test above: the mirror must actually do
        its job on a genuine shrink, not just refuse the dangerous one.
        """
        tasks = {"gh-%d" % n: models.Task(key="gh-%d" % n, task_id="t%d" % n,
                                          title="T gh-%d" % n,
                                          body=models.marker("gh-%d" % n))
                 for n in range(18)}
        client = FakeClient(tasks=tasks)
        survivors = {"gh-0": item("gh-0"), "gh-1": item("gh-1")}
        state.save_state(self.state_path, {"last_count": 18, "ids": {}})

        result = sync_core.run_sync({"list_name": "L"}, client, survivors, self.state_path)

        self.assertEqual(16, result["completed"])
        self.assertEqual(16, len(client.completed))
        self.assertEqual([], client.created)
        self.assertEqual(0, result["created"])
        self.assertNotIn("t0", client.completed)
        self.assertNotIn("t1", client.completed)


class ReopenClient:
    """A fake whose `update()` behaves one of the three ways the API might.

    - `error`  -- update raises. What `sync_core` was WRITTEN to assume.
    - `silent` -- update answers 200 and changes nothing. What was MEASURED
      against the live API for a deleted id (docs/api-notes.md section 7).
    - `works`  -- update genuinely brings the task back.
    """

    def __init__(self, mode):
        self.mode = mode
        self.tasks = {}
        self.created, self.updated, self.completed = [], [], []
        self._minted = 0

    def resolve_list(self, name, list_id=None):
        return "p1"

    def read_tasks(self, project_id):
        return dict(self.tasks)

    def _task(self, task_id, item):
        return models.Task(key=item.key, task_id=task_id, title=item.title,
                           body=item.body, tags=item.tags)

    def create(self, project_id, item):
        self._minted += 1
        new_id = "new-%d" % self._minted
        self.created.append(item.key)
        self.tasks[item.key] = self._task(new_id, item)
        return new_id

    def update(self, project_id, task_id, item):
        self.updated.append(item.key)
        if self.mode == "error":
            raise ticktick.TickTickError("POST /task/%s -> 404" % task_id)
        if self.mode == "works":
            self.tasks[item.key] = self._task(task_id, item)
        # "silent": returns normally and nothing changes.

    def complete(self, project_id, task_id):
        self.completed.append(task_id)


class ReopenFallbackTest(unittest.TestCase):
    """FINDING C2: the Reopen -> Create fallback rested on unmeasured belief.

    A remembered id whose task is no longer in the list produces a Reopen. If
    that id was DELETED rather than completed, the reopen writes into the void
    -- and the live API answers 200 while doing so, so nothing raises. Trusting
    the status code means reporting `reopened=1` on every run forever while the
    item never comes back and the dead id is never evicted.
    """

    def setUp(self):
        self.state_path = os.path.join(tempfile.mkdtemp(), "state.json")
        # A remembered id, and a list that does not contain its task.
        state.save_state(self.state_path, {"last_count": 1, "ids": {"gh-1": "dead-id"}})

    def run_one(self, mode):
        client = ReopenClient(mode)
        result = sync_core.run_sync({"list_name": "L"}, client,
                                    {"gh-1": item("gh-1")}, self.state_path)
        return client, result

    def test_a_reopen_that_errors_falls_back_to_creating_the_task(self):
        client, result = self.run_one("error")

        self.assertEqual(["gh-1"], client.created)
        self.assertEqual(1, result["created"])
        self.assertEqual(0, result["reopened"])

    def test_a_reopen_that_errors_persists_the_new_id(self):
        """Without this the dead id survives in state.json and the next run
        walks into the same hole."""
        self.run_one("error")

        self.assertEqual("new-1", state.load_state(self.state_path)["ids"]["gh-1"])

    def test_a_reopen_that_silently_does_nothing_still_falls_back(self):
        """THE MEASURED CASE. A 200 on a deleted id is not evidence the task
        exists -- the run has to look at the list to find out."""
        client, result = self.run_one("silent")

        self.assertEqual(["gh-1"], client.created)
        self.assertEqual(1, result["created"])
        self.assertEqual(0, result["reopened"],
                         "reported a reopen that never happened")

    def test_a_silent_failure_evicts_the_dead_id(self):
        self.run_one("silent")

        self.assertEqual("new-1", state.load_state(self.state_path)["ids"]["gh-1"])

    def test_a_reopen_that_genuinely_works_creates_nothing(self):
        """The other side of it: a working reopen must not mint a duplicate."""
        client, result = self.run_one("works")

        self.assertEqual([], client.created)
        self.assertEqual(1, result["reopened"])
        self.assertEqual(0, result["created"])
        self.assertEqual("dead-id", state.load_state(self.state_path)["ids"]["gh-1"])


if __name__ == "__main__":
    unittest.main()

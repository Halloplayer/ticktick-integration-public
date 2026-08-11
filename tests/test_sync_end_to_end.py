"""The whole circle against a fake TickTick -- no network."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import models, sync_core  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()

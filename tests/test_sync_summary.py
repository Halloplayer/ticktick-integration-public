"""The summary line is sync.log's only report of what happened -- under
pythonw.exe there is no console, so a count silently dropped from the format
string means an entire class of action becomes invisible. Reopening is not a
rare path: it fires every time the user ticks something off while the source
is still open, which is the single most likely way they interact with the
list. These tests drive the real format string through main(), not a
reimplementation of it.
"""
import contextlib
import importlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import sync  # noqa: E402
from ticktick_sync import models, state  # noqa: E402


class FakeClient:
    """Mirrors ticktick.Client's interface, no network.

    `update` puts the task into the visible list, because that is what the live
    API does: a `status: 0` write on a real id brings the task back into
    `GET /project/{id}/data` (docs/api-notes.md section 4). This fake used to
    accept the update and leave the list untouched -- which, measured, is the
    behaviour of a DELETED id (section 7), not a re-openable one. Now that
    `run_sync` checks the list instead of trusting the status code, the old
    fake would have been describing a dead task and would rightly have sent the
    run down the create path.
    """

    def __init__(self, tasks=None):
        self.tasks = tasks or {}
        self.created, self.updated, self.completed = [], [], []

    def resolve_list(self, name, list_id=None):
        return "p1"

    def read_tasks(self, project_id):
        return dict(self.tasks)

    def _remember(self, task_id, item):
        self.tasks[item.key] = models.Task(
            key=item.key, task_id=task_id, title=item.title, body=item.body,
            priority=item.priority)

    def create(self, project_id, item):
        self.created.append(item.key)
        self._remember("new-" + item.key, item)
        return "new-" + item.key

    def update(self, project_id, task_id, item):
        self.updated.append(item.key)
        self._remember(task_id, item)

    def complete(self, project_id, task_id):
        self.completed.append(task_id)


def item(key):
    return models.Item(key=key, title="T " + key, body=models.marker(key))


class SummaryLineTest(unittest.TestCase):
    """Points sync.DATA at a private temp dir via TICKTICK_SYNC_DATA, and
    stubs both the GitHub read and the TickTick client, so nothing here ever
    touches the network, the real `gh`, or the real
    %LOCALAPPDATA%\\ticktick-sync\\.env / state.json -- that state is now
    LIVE and backs a real task list.
    """

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self._old_env = os.environ.get("TICKTICK_SYNC_DATA")
        os.environ["TICKTICK_SYNC_DATA"] = self.data_dir
        importlib.reload(sync)
        # token() only needs a syntactically valid credential; the TickTick
        # client itself is stubbed out below, so this value is never sent
        # anywhere.
        with open(os.path.join(self.data_dir, ".env"), "w", encoding="utf-8") as handle:
            handle.write("TICKTICK_TOKEN=fake-token-for-tests\n")

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("TICKTICK_SYNC_DATA", None)
        else:
            os.environ["TICKTICK_SYNC_DATA"] = self._old_env
        importlib.reload(sync)

    def _run_main(self, desired, fake_client):
        out = io.StringIO()
        with mock.patch.object(sync.github, "read_desired", return_value=desired), \
             mock.patch.object(sync.ticktick, "Client", lambda *a, **kw: fake_client), \
             contextlib.redirect_stdout(out):
            exit_code = sync.main([])
        return exit_code, out.getvalue()

    def test_the_summary_line_names_reopened(self):
        client = FakeClient()

        exit_code, printed = self._run_main({"gh-1": item("gh-1")}, client)

        self.assertEqual(0, exit_code)
        self.assertIn("reopened=", printed)

    def test_a_run_that_reopens_something_reports_a_non_zero_count(self):
        """Proves the defect is actually closed: a hardcoded `reopened=0`
        would satisfy the substring check above but fail this one."""
        # gh-1 is remembered from a previous run (known_ids) but is not among
        # the currently visible tasks -- exactly what happens when the user
        # ticks it off by hand while the source is still open. That is a
        # Reopen, not a Create.
        state.save_state(os.path.join(self.data_dir, "state.json"),
                         {"last_count": 1, "ids": {"gh-1": "t1"}})
        client = FakeClient(tasks={})

        exit_code, printed = self._run_main({"gh-1": item("gh-1")}, client)

        self.assertEqual(0, exit_code)
        self.assertEqual(["gh-1"], client.updated)
        self.assertIn("reopened=1", printed)


if __name__ == "__main__":
    unittest.main()

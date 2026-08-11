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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import sync  # noqa: E402
import models, state  # noqa: E402


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
            tags=item.tags)

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
        # One configured repository, in the per-repo layout the mirror now
        # discovers. `main([])` syncs everything it finds, so "everything" is
        # exactly this one, and its state file sits beside its own config.
        self.repo_dir = os.path.join(self.data_dir, "repos", "acme__widgets")
        os.makedirs(self.repo_dir)
        with open(os.path.join(self.repo_dir, "config.toml"), "w", encoding="utf-8") as handle:
            handle.write('repo = "acme/widgets"\nitems_path = "open-items.toml"\n'
                         'list_name = "Widgets"\n')

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
        state.save_state(os.path.join(self.repo_dir, "state.json"),
                         {"last_count": 1, "ids": {"gh-1": "t1"}})
        client = FakeClient(tasks={})

        exit_code, printed = self._run_main({"gh-1": item("gh-1")}, client)

        self.assertEqual(0, exit_code)
        self.assertEqual(["gh-1"], client.updated)
        self.assertIn("reopened=1", printed)

    def test_the_summary_line_carries_untranslated_when_above_zero(self):
        """A GitHub-issue task whose German excerpt has no cached English
        translation (or a stale one) is marked `Item.untranslated=True`. The
        summary line -- sync.log's only report under pythonw.exe, where there
        is no console -- must say so, or a translation cache going stale is
        invisible."""
        desired = {"gh-1": models.Item(key="gh-1", title="T gh-1", body=models.marker("gh-1"),
                                       untranslated=True)}

        exit_code, printed = self._run_main(desired, FakeClient())

        self.assertEqual(0, exit_code)
        self.assertIn("untranslated=1", printed)

    def test_the_summary_line_omits_untranslated_when_zero(self):
        """No noise on the common case: every real run has zero of these."""
        exit_code, printed = self._run_main({"gh-1": item("gh-1")}, FakeClient())

        self.assertEqual(0, exit_code)
        self.assertNotIn("untranslated", printed)


if __name__ == "__main__":
    unittest.main()

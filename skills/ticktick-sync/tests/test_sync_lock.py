"""FINDING I3: two runs at once mint a twin that can never be cleaned up.

The scheduled task is `MultipleInstances = IgnoreNew`, so it cannot overlap
itself -- but the skill starts an independent process, and nothing stops that
one from landing in the middle of a scheduled tick. Both runs read the list,
both see an item that is absent from `current` and from `ids`, and both create
it.

The damage is permanent, not transient. `tasks_from_payload` keys tasks by
their marker, so of the two identical markers only one is ever seen again. The
other is invisible to every future run: never updated, never completed, and
stranded for good in the user's own task list. A skipped run costs nothing by
comparison -- the next tick five minutes later reconciles everything.
"""
import contextlib
import importlib
import io
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import sync  # noqa: E402
import models  # noqa: E402

CONFIG = 'repo = "x/y"\nitems_path = "open-items.toml"\nlist_name = "L"\n'


def item(key):
    return models.Item(key=key, title="T " + key, body=models.marker(key))


class FakeClient:
    def __init__(self):
        self.tasks = {}
        self.created, self.updated, self.completed = [], [], []

    def resolve_list(self, name, list_id=None):
        return "p1"

    def read_tasks(self, project_id):
        return dict(self.tasks)

    def create(self, project_id, item):
        self.created.append(item.key)
        self.tasks[item.key] = models.Task(
            key=item.key, task_id="new-%d" % len(self.created), title=item.title,
            body=item.body, tags=item.tags)
        return "new-%d" % len(self.created)

    def update(self, project_id, task_id, item):
        self.updated.append(item.key)
        self.tasks[item.key] = models.Task(
            key=item.key, task_id=task_id, title=item.title, body=item.body,
            tags=item.tags)

    def complete(self, project_id, task_id):
        self.completed.append(task_id)


class LockTestBase(unittest.TestCase):
    """Everything points at a private temp dir; no network, no real `gh`, and
    never the LIVE %LOCALAPPDATA%\\ticktick-sync."""

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self._old_env = os.environ.get("TICKTICK_SYNC_DATA")
        os.environ["TICKTICK_SYNC_DATA"] = self.data_dir
        importlib.reload(sync)
        self.config_path = os.path.join(self.data_dir, "config.toml")
        with open(self.config_path, "w", encoding="utf-8") as handle:
            handle.write(CONFIG)
        with open(os.path.join(self.data_dir, ".env"), "w", encoding="utf-8") as handle:
            handle.write("TICKTICK_TOKEN=fake-token-for-tests\n")

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("TICKTICK_SYNC_DATA", None)
        else:
            os.environ["TICKTICK_SYNC_DATA"] = self._old_env
        importlib.reload(sync)

    def run_main(self, client, desired=None, argv=None):
        desired = {"gh-1": item("gh-1")} if desired is None else desired
        out = io.StringIO()
        with mock.patch.object(sync.github, "read_desired", return_value=desired), \
             mock.patch.object(sync.ticktick, "Client", lambda *a, **kw: client), \
             contextlib.redirect_stdout(out):
            return sync.main(argv or ["--quiet", "--config", self.config_path])

    def log_text(self):
        path = os.path.join(self.data_dir, "sync.log")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def lock_path(self):
        return str(sync.LOCK)


class OverlappingRunsTest(LockTestBase):
    def test_two_overlapping_runs_do_not_create_the_same_marker_twice(self):
        """The race, reproduced without threads.

        The outer run reads the list, and at that exact moment a second run
        happens from start to finish -- the scheduler firing while the skill's
        run is in flight. The outer run then carries on with the view it
        already had, in which the item is still absent. Both would create it.
        """
        client = FakeClient()
        inner = {}
        real_read = client.read_tasks

        def read_then_let_the_other_run_happen(project_id):
            snapshot = real_read(project_id)  # what THIS run sees
            if "exit" not in inner:
                inner["exit"] = None  # guard against unbounded re-entry
                inner["exit"] = self.run_main(client)
            return snapshot  # ... and proceeds on its now-stale view

        client.read_tasks = read_then_let_the_other_run_happen

        exit_code = self.run_main(client)

        self.assertEqual(0, exit_code)
        self.assertEqual(["gh-1"], client.created,
                         "the same marker was created twice -- one twin is now "
                         "invisible to every future run")

    def test_the_run_that_loses_the_race_exits_zero(self):
        """A skipped run is not a failure: the next tick reconciles. Exiting
        non-zero would make the Scheduled Task history look broken."""
        client = FakeClient()
        inner = {}
        real_read = client.read_tasks

        def read_then_reenter(project_id):
            snapshot = real_read(project_id)
            if "exit" not in inner:
                inner["exit"] = None
                inner["exit"] = self.run_main(client)
            return snapshot

        client.read_tasks = read_then_reenter

        self.run_main(client)

        self.assertEqual(0, inner["exit"])

    def test_the_skipped_run_leaves_a_line_behind(self):
        """Silence is what this whole project is against."""
        client = FakeClient()
        inner = {}
        real_read = client.read_tasks

        def read_then_reenter(project_id):
            snapshot = real_read(project_id)
            if "exit" not in inner:
                inner["exit"] = None
                inner["exit"] = self.run_main(client)
            return snapshot

        client.read_tasks = read_then_reenter

        self.run_main(client)

        self.assertIn("lock", self.log_text().lower())


class LockLifecycleTest(LockTestBase):
    def test_a_finished_run_releases_the_lock(self):
        self.run_main(FakeClient())

        self.assertFalse(os.path.exists(self.lock_path()),
                         "the lock outlived the run that took it")

    def test_a_failed_run_releases_the_lock_too(self):
        """Released in a `finally`, or one crash wedges the mirror forever."""
        with mock.patch.object(sync.github, "load_config",
                               side_effect=RuntimeError("boom")):
            exit_code = sync.main(["--quiet", "--config", self.config_path])

        self.assertEqual(1, exit_code)
        self.assertFalse(os.path.exists(self.lock_path()))

    def test_a_second_run_after_the_first_finished_is_not_blocked(self):
        client = FakeClient()
        self.run_main(client)

        exit_code = self.run_main(client)

        self.assertEqual(0, exit_code)
        self.assertEqual(["gh-1"], client.created)  # created once, then left alone

    def test_a_lock_held_right_now_skips_the_run_without_touching_anything(self):
        with open(self.lock_path(), "w", encoding="utf-8") as handle:
            handle.write("99999")
        client = FakeClient()

        exit_code = self.run_main(client)

        self.assertEqual(0, exit_code)
        self.assertEqual([], client.created)
        self.assertTrue(os.path.exists(self.lock_path()),
                        "the skipped run deleted the other run's lock")


class StaleLockTest(LockTestBase):
    """A killed process leaves its lock behind. Without a way out, the mirror
    would stay silently dead until somebody deleted the file by hand -- which
    nobody would, because nothing says it is there."""

    def hold_lock(self, age_seconds):
        with open(self.lock_path(), "w", encoding="utf-8") as handle:
            handle.write("99999")
        when = time.time() - age_seconds
        os.utime(self.lock_path(), (when, when))

    def test_a_lock_abandoned_long_ago_is_taken_over(self):
        self.hold_lock(11 * 60)
        client = FakeClient()

        exit_code = self.run_main(client)

        self.assertEqual(0, exit_code)
        self.assertEqual(["gh-1"], client.created)

    def test_taking_over_a_stale_lock_is_logged(self):
        """Taking someone else's lock is exactly the kind of thing that must
        never happen quietly."""
        self.hold_lock(11 * 60)

        self.run_main(FakeClient())

        self.assertIn("stale", self.log_text().lower())

    def test_a_lock_taken_nine_minutes_ago_is_still_respected(self):
        """Under the threshold: a long-running run is not an abandoned one."""
        self.hold_lock(9 * 60)
        client = FakeClient()

        exit_code = self.run_main(client)

        self.assertEqual(0, exit_code)
        self.assertEqual([], client.created)


if __name__ == "__main__":
    unittest.main()

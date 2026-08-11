"""One process, every configured repository -- and one failure that does not
take the others down with it.

`run_sync` still syncs exactly one repo against one config, unchanged. What is
new sits above it: discovery, a loop, and the accounting that keeps the
Scheduled Task's result code meaningful. A repo that fails is caught, named in
the log and counted; the others still run; the process still exits non-zero, so
"the last run failed" does not quietly become "the last run was fine".
"""
import contextlib
import importlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import sync  # noqa: E402
import models  # noqa: E402


def item(key):
    return models.Item(key=key, title="T " + key, body=models.marker(key))


class FakeClient:
    def __init__(self):
        self.tasks = {}
        self.created = []

    def resolve_list(self, name, list_id=None):
        return "p-" + name

    def read_tasks(self, project_id):
        return dict(self.tasks)

    def create(self, project_id, item):
        self.created.append(item.key)
        task_id = "new-%d" % len(self.created)
        self.tasks[item.key] = models.Task(key=item.key, task_id=task_id, title=item.title,
                                           body=item.body, tags=item.tags)
        return task_id

    def update(self, project_id, task_id, item):
        self.tasks[item.key] = models.Task(key=item.key, task_id=task_id, title=item.title,
                                           body=item.body, tags=item.tags)

    def complete(self, project_id, task_id):
        pass


class MultiRepoTestBase(unittest.TestCase):
    """A private data directory -- never the LIVE %LOCALAPPDATA%\\ticktick-integration,
    which backs seventeen real tasks."""

    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data_dir, True)
        self._old_env = os.environ.get("TICKTICK_INTEGRATION_DATA")
        os.environ["TICKTICK_INTEGRATION_DATA"] = self.data_dir
        importlib.reload(sync)
        with open(os.path.join(self.data_dir, ".env"), "w", encoding="utf-8") as handle:
            handle.write("TICKTICK_TOKEN=fake-token-for-tests\n")

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("TICKTICK_INTEGRATION_DATA", None)
        else:
            os.environ["TICKTICK_INTEGRATION_DATA"] = self._old_env
        importlib.reload(sync)

    def configure(self, slug, repo=None):
        directory = os.path.join(self.data_dir, "repos", slug)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "config.toml"), "w", encoding="utf-8") as handle:
            handle.write('repo = "%s"\nitems_path = "open-items.toml"\nlist_name = "%s"\n'
                         % (repo or slug.replace("__", "/"), slug))
        return directory

    def run_main(self, argv=None, desired=None, client=None):
        """No network, no `gh`: the GitHub read and the TickTick client are
        both fakes, and the token comes from the temp .env."""
        client = client or FakeClient()

        def read(config, *args, **kwargs):
            if callable(desired):
                return desired(config)
            return {"gh-1": item("gh-1")} if desired is None else desired

        out = io.StringIO()
        with mock.patch.object(sync.github, "read_desired", side_effect=read), \
             mock.patch.object(sync.ticktick, "Client", lambda *a, **kw: client), \
             contextlib.redirect_stdout(out):
            code = sync.main(argv if argv is not None else ["--quiet"])
        self.stdout = out.getvalue()
        return code

    def log_text(self):
        path = os.path.join(self.data_dir, "sync.log")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as handle:
            return handle.read()


class EveryConfiguredRepoRunsTest(MultiRepoTestBase):
    def test_both_repositories_are_synced_in_one_run(self):
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        code = self.run_main()

        self.assertEqual(0, code)
        for slug in ("acme__widgets", "globex__toolkit"):
            self.assertTrue(os.path.isfile(
                os.path.join(self.data_dir, "repos", slug, "state.json")),
                "%s never got its own state.json" % slug)

    def test_each_repo_gets_its_own_log_line_carrying_its_slug(self):
        """One shared log for all repositories, so every line has to say which
        one it is about -- otherwise the log stops being readable the moment a
        second repo exists."""
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        self.run_main()

        text = self.log_text()
        self.assertIn("acme__widgets ok desired=", text)
        self.assertIn("globex__toolkit ok desired=", text)

    def test_a_repos_state_stays_inside_its_own_directory(self):
        """Two repositories sharing one state.json would trade task ids and
        collapse counts -- the second run would then complete the first repo's
        tasks."""
        self.configure("acme__widgets")

        self.run_main()

        self.assertFalse(os.path.exists(os.path.join(self.data_dir, "state.json")),
                         "state.json was written to the shared data directory again")

    def test_no_repository_configured_at_all_is_reported_not_silent(self):
        code = self.run_main()

        self.assertEqual(0, code, "nothing to do is not a failure")
        self.assertIn("no repositories configured", self.log_text())


class OneFailingRepoTest(MultiRepoTestBase):
    """The whole point of the loop: a broken repo is one broken repo."""

    def failing_read(self, bad_repo):
        def read(config, *args, **kwargs):
            if config["repo"] == bad_repo:
                raise RuntimeError("boom")
            return {"gh-1": item("gh-1")}
        return read

    def test_a_repo_that_raises_does_not_stop_the_others(self):
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        self.run_main(desired=self.failing_read("acme/widgets"))

        self.assertTrue(os.path.isfile(os.path.join(
            self.data_dir, "repos", "globex__toolkit", "state.json")),
            "the healthy repository never ran")

    def test_the_failure_is_logged_against_its_own_slug(self):
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        self.run_main(desired=self.failing_read("acme/widgets"))

        self.assertIn("acme__widgets ERROR RuntimeError: boom", self.log_text())

    def test_the_process_still_exits_non_zero(self):
        """The Scheduled Task's result code is the only signal a background job
        has. Swallowing a failure to keep the run 'green' would make it lie."""
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        code = self.run_main(desired=self.failing_read("acme/widgets"))

        self.assertEqual(1, code)

    def test_a_run_where_every_repo_succeeds_exits_zero(self):
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        self.assertEqual(0, self.run_main())


class SingleRepoFlagTest(MultiRepoTestBase):
    def test_the_flag_syncs_only_the_named_repository(self):
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        code = self.run_main(["--quiet", "--repo", "acme__widgets"])

        self.assertEqual(0, code)
        self.assertTrue(os.path.isfile(os.path.join(
            self.data_dir, "repos", "acme__widgets", "state.json")))
        self.assertFalse(os.path.isfile(os.path.join(
            self.data_dir, "repos", "globex__toolkit", "state.json")),
            "--repo synced a repository it was not asked to")

    def test_the_default_is_still_every_repository(self):
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        self.run_main(["--quiet"])

        for slug in ("acme__widgets", "globex__toolkit"):
            self.assertTrue(os.path.isfile(
                os.path.join(self.data_dir, "repos", slug, "state.json")))

    def test_an_unknown_slug_fails_rather_than_silently_doing_nothing(self):
        self.configure("acme__widgets")

        code = self.run_main(["--quiet", "--repo", "acme__gadgets"])

        self.assertEqual(1, code)

    def test_an_unknown_slug_names_what_is_actually_configured(self):
        """A typo in a slug is the likeliest way to use this flag wrong, and
        'unknown repo' alone leaves the user guessing at a directory name."""
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        self.run_main(["--quiet", "--repo", "acme__gadgets"])

        text = self.log_text()
        self.assertIn("acme__gadgets", text)
        self.assertIn("acme__widgets", text)
        self.assertIn("globex__toolkit", text)

    def test_a_traversing_slug_is_refused(self):
        """--repo also reaches the filesystem; it is not more trusted than a
        git remote is."""
        self.configure("acme__widgets")

        self.assertEqual(1, self.run_main(["--quiet", "--repo", "..\\..\\windows"]))


class MigrationOnFirstRunTest(MultiRepoTestBase):
    """The live installation must keep working across the very first run of the
    new layout, without anybody being asked to do anything."""

    def test_the_legacy_layout_is_migrated_and_then_synced(self):
        with open(os.path.join(self.data_dir, "state.json"), "w", encoding="utf-8") as handle:
            handle.write('{"last_count": 17, "ids": {}}')

        code = self.run_main()

        self.assertEqual(0, code)
        self.assertIn("globex__toolkit ok desired=", self.log_text())

    def test_the_migration_itself_is_logged(self):
        with open(os.path.join(self.data_dir, "state.json"), "w", encoding="utf-8") as handle:
            handle.write('{"last_count": 17, "ids": {}}')

        self.run_main()

        self.assertIn("migrated", self.log_text())


if __name__ == "__main__":
    unittest.main()

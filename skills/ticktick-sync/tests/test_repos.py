"""Per-repo data directories: slugs, discovery, and the one-shot migration.

The mirror used to serve exactly one repository. Its configuration sat at the
plugin root -- a version-scoped cache directory that a plugin update replaces
WHOLESALE, so a user's own settings were one update away from being deleted --
and its `state.json` sat alone in the data directory. Both are single-tenant by
construction. These tests pin the replacement: one directory per repository
under `repos/`, keyed by a slug that comes from a git remote and is therefore
never trusted blindly.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import repos  # noqa: E402


class SlugFromRemoteTest(unittest.TestCase):
    """`git remote get-url origin` speaks several dialects for one repository.

    All of them must land on the same directory name, or the same repo gets
    mirrored twice under two slugs -- two states, two sets of task ids, and a
    duplicate of every task in the user's own list.
    """

    def test_an_https_remote_yields_owner_and_repo(self):
        self.assertEqual("acme__widgets",
                         repos.slug_from_remote("https://github.com/acme/widgets.git"))

    def test_an_https_remote_without_the_git_suffix_yields_the_same_slug(self):
        self.assertEqual("acme__widgets",
                         repos.slug_from_remote("https://github.com/acme/widgets"))

    def test_an_scp_style_ssh_remote_yields_the_same_slug(self):
        self.assertEqual("acme__widgets",
                         repos.slug_from_remote("git@github.com:acme/widgets.git"))

    def test_an_ssh_url_remote_yields_the_same_slug(self):
        self.assertEqual("acme__widgets",
                         repos.slug_from_remote("ssh://git@github.com/acme/widgets.git"))

    def test_trailing_whitespace_and_slashes_do_not_change_the_slug(self):
        """`git remote get-url` output arrives with a newline on it."""
        self.assertEqual("acme__widgets",
                         repos.slug_from_remote("https://github.com/acme/widgets.git/\n"))

    def test_the_repo_slug_of_the_live_installation_is_the_documented_one(self):
        self.assertEqual("globex__toolkit",
                         repos.slug_from_remote("git@github.com:globex/toolkit.git"))

    def test_the_owner_repo_pair_is_recoverable_from_the_slug(self):
        """config.toml needs `owner/repo`; the directory name carries it."""
        self.assertEqual("acme/widgets", repos.repo_from_slug("acme__widgets"))


class SlugIsNotTrustedTest(unittest.TestCase):
    """The slug comes from a git remote -- attacker-controllable in principle
    and typo-controllable in practice. It becomes a path under the data
    directory, so anything that could escape that directory is refused.
    """

    def test_a_forward_slash_is_rejected(self):
        with self.assertRaises(repos.SlugError):
            repos.check_slug("acme/widgets")

    def test_a_backslash_is_rejected(self):
        with self.assertRaises(repos.SlugError):
            repos.check_slug("acme\\widgets")

    def test_a_parent_directory_traversal_is_rejected(self):
        with self.assertRaises(repos.SlugError):
            repos.check_slug("..")

    def test_a_traversal_hidden_inside_a_plausible_slug_is_rejected(self):
        with self.assertRaises(repos.SlugError):
            repos.check_slug("acme__..__widgets")

    def test_an_absolute_path_is_rejected(self):
        with self.assertRaises(repos.SlugError):
            repos.check_slug("C:\\Windows\\Temp")

    def test_an_empty_slug_is_rejected(self):
        with self.assertRaises(repos.SlugError):
            repos.check_slug("")

    def test_a_traversing_remote_never_becomes_a_slug(self):
        """The rejection must happen on the derivation path too, not only when
        somebody remembers to call the checker."""
        with self.assertRaises(repos.SlugError):
            repos.slug_from_remote("https://github.com/../..")

    def test_a_legitimate_slug_passes_and_is_returned(self):
        self.assertEqual("acme__widgets-2.0", repos.check_slug("acme__widgets-2.0"))


class DiscoveryTest(unittest.TestCase):
    """Every configured repository runs; nothing else does."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)

    def configure(self, slug):
        directory = os.path.join(self.data, "repos", slug)
        os.makedirs(directory)
        path = os.path.join(directory, "config.toml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('repo = "%s"\nlist_name = "L"\nitems_path = "open-items.toml"\n'
                         % repos.repo_from_slug(slug))
        return path

    def test_no_repos_directory_at_all_is_an_empty_list_not_a_crash(self):
        self.assertEqual([], repos.discover(self.data))

    def test_every_configured_repo_is_found(self):
        self.configure("acme__widgets")
        self.configure("globex__toolkit")

        found = repos.discover(self.data)

        self.assertEqual(["globex__toolkit", "acme__widgets"],
                         [slug for slug, _ in found])

    def test_the_config_path_points_at_the_repos_own_config(self):
        expected = self.configure("acme__widgets")

        self.assertEqual([os.path.normcase(expected)],
                         [os.path.normcase(path) for _, path in repos.discover(self.data)])

    def test_a_stray_file_in_the_repos_directory_is_ignored(self):
        self.configure("acme__widgets")
        with open(os.path.join(self.data, "repos", "notes.txt"), "w", encoding="utf-8") as handle:
            handle.write("scratch\n")

        self.assertEqual(["acme__widgets"], [slug for slug, _ in repos.discover(self.data)])

    def test_a_directory_without_a_config_is_ignored(self):
        """A half-finished setup must not abort every other repository."""
        self.configure("acme__widgets")
        os.makedirs(os.path.join(self.data, "repos", "abandoned__setup"))

        self.assertEqual(["acme__widgets"], [slug for slug, _ in repos.discover(self.data)])

    def test_the_shared_files_beside_repos_are_not_mistaken_for_a_repo(self):
        """.env, sync.log and launcher.pyw live one level up, deliberately --
        one credential, one log, one launcher for all repositories."""
        self.configure("acme__widgets")
        for name in (".env", "sync.log", "launcher.pyw", "state.json"):
            with open(os.path.join(self.data, name), "w", encoding="utf-8") as handle:
                handle.write("x")

        self.assertEqual(["acme__widgets"], [slug for slug, _ in repos.discover(self.data)])


LIVE_STATE = {
    "last_count": 17,
    "ids": {"gh-11": "abc123", "oi-something": "def456"},
}


class MigrationTest(unittest.TestCase):
    """A working single-repo installation exists RIGHT NOW, mirroring
    seventeen real tasks. `state.json` carries `last_count`, which is what ARMS
    the collapse guard: lose it and the guard is disarmed for one run, on a
    live list. So the migration copies it verbatim rather than regenerating
    anything, and it happens once.
    """

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)
        self.seed = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.seed, True)
        with open(os.path.join(self.seed, "config.toml"), "w", encoding="utf-8") as handle:
            handle.write('repo = "globex/toolkit"\n'
                         'items_path = "open-items.toml"\n'
                         'list_id = "6f1e2d3c4b5a69788796a5b4"\n'
                         'list_name = "L"\n')
        with open(os.path.join(self.seed, "issue-descriptions.toml"), "w",
                  encoding="utf-8") as handle:
            handle.write('[[issues]]\nnumber = 11\nsource_sha256 = "aa"\n'
                         'description = "English."\n')

    def write_legacy_state(self, payload=None):
        path = os.path.join(self.data, "state.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload or LIVE_STATE, handle, indent=2)
        return path

    def migrated(self, *parts):
        return os.path.join(self.data, "repos", repos.LEGACY_SLUG, *parts)

    def test_the_legacy_state_moves_into_the_repo_directory(self):
        self.write_legacy_state()

        self.assertEqual(repos.LEGACY_SLUG, repos.migrate_legacy(self.data, self.seed))

        self.assertTrue(os.path.isfile(self.migrated("state.json")))

    def test_last_count_survives_exactly(self):
        """Seventeen real tasks depend on this number being carried over, not
        recomputed: a zero here disarms the collapse guard for one run."""
        self.write_legacy_state()

        repos.migrate_legacy(self.data, self.seed)

        with open(self.migrated("state.json"), encoding="utf-8") as handle:
            self.assertEqual(17, json.load(handle)["last_count"])

    def test_the_whole_state_file_is_preserved_byte_for_byte(self):
        legacy = self.write_legacy_state()
        with open(legacy, "rb") as handle:
            before = handle.read()

        repos.migrate_legacy(self.data, self.seed)

        with open(self.migrated("state.json"), "rb") as handle:
            self.assertEqual(before, handle.read())

    def test_the_task_id_map_survives(self):
        self.write_legacy_state()

        repos.migrate_legacy(self.data, self.seed)

        with open(self.migrated("state.json"), encoding="utf-8") as handle:
            self.assertEqual(LIVE_STATE["ids"], json.load(handle)["ids"])

    def test_the_config_and_the_translation_cache_come_along(self):
        self.write_legacy_state()

        repos.migrate_legacy(self.data, self.seed)

        self.assertTrue(os.path.isfile(self.migrated("config.toml")))
        self.assertTrue(os.path.isfile(self.migrated("issue-descriptions.toml")))

    def test_the_migrated_config_names_the_live_repository(self):
        self.write_legacy_state()

        repos.migrate_legacy(self.data, self.seed)

        with open(self.migrated("config.toml"), encoding="utf-8") as handle:
            self.assertIn("globex/toolkit", handle.read())

    def test_a_second_run_does_nothing(self):
        self.write_legacy_state()
        repos.migrate_legacy(self.data, self.seed)

        self.assertIsNone(repos.migrate_legacy(self.data, self.seed))

    def test_a_second_run_cannot_overwrite_a_state_that_moved_on(self):
        """The live state changes every five minutes. A migration that ran
        twice would stamp a stale copy over it and reset the guard."""
        self.write_legacy_state()
        repos.migrate_legacy(self.data, self.seed)
        with open(self.migrated("state.json"), "w", encoding="utf-8") as handle:
            json.dump({"last_count": 19, "ids": {}}, handle)

        repos.migrate_legacy(self.data, self.seed)

        with open(self.migrated("state.json"), encoding="utf-8") as handle:
            self.assertEqual(19, json.load(handle)["last_count"])

    def test_a_fresh_installation_has_nothing_to_migrate(self):
        """No legacy state.json: this machine never ran the single-repo
        version, and inventing a Work repository for it would be absurd."""
        self.assertIsNone(repos.migrate_legacy(self.data, self.seed))
        self.assertFalse(os.path.exists(os.path.join(self.data, "repos")))

    def test_an_already_multi_repo_installation_is_left_alone(self):
        """Somebody could restore an old state.json by hand next to a data
        directory that has already moved on. The target's existence decides."""
        os.makedirs(self.migrated())
        with open(self.migrated("config.toml"), "w", encoding="utf-8") as handle:
            handle.write('repo = "globex/toolkit"\nlist_name = "L"\n')
        self.write_legacy_state()

        self.assertIsNone(repos.migrate_legacy(self.data, self.seed))

    def test_a_missing_seed_refuses_rather_than_half_migrating(self):
        """Without the seed there is no config to write, and a repo directory
        holding only a state.json is invisible to discovery -- so the run
        would look healthy while mirroring nothing, and the legacy state would
        already have been renamed out of the way. Fail loudly instead."""
        self.write_legacy_state()
        os.remove(os.path.join(self.seed, "config.toml"))

        with self.assertRaises(repos.MigrationFailed):
            repos.migrate_legacy(self.data, self.seed)

        self.assertTrue(os.path.isfile(os.path.join(self.data, "state.json")),
                        "the legacy state was disturbed by a migration that could "
                        "not finish")

    def test_the_legacy_state_is_kept_as_a_backup_under_a_dead_name(self):
        """Copied, not moved: the original stays recoverable if anything about
        the new layout turns out wrong on a live list. Renamed, so no later
        run can mistake it for live state and migrate a second time."""
        self.write_legacy_state()

        repos.migrate_legacy(self.data, self.seed)

        self.assertFalse(os.path.exists(os.path.join(self.data, "state.json")))
        self.assertTrue(os.path.isfile(
            os.path.join(self.data, "state.json." + repos.BACKUP_SUFFIX)))


if __name__ == "__main__":
    unittest.main()

"""Per-repo data directories: slugs and discovery.

Configuration must never sit at the plugin root -- a version-scoped cache
directory that a plugin update replaces WHOLESALE, so a user's own settings
would be one update away from being deleted. These tests pin the layout that
replaces it: one directory per repository under `repos/`, keyed by a slug that
comes from a git remote and is therefore never trusted blindly.
"""
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

    def test_a_repo_name_containing_a_single_underscore_survives(self):
        """A single underscore is legal on both sides of the pair; only the
        doubled separator is reserved."""
        self.assertEqual("acme__my_widgets",
                         repos.slug_from_remote("https://github.com/acme/my_widgets.git"))

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

        self.assertEqual(["acme__widgets", "globex__toolkit"],
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


if __name__ == "__main__":
    unittest.main()

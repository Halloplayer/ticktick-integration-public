"""Setting a new repository up -- and the wall between setup and sync.

Setup may create a TickTick list, once, on an explicit confirmation. The SYNC
never may: a mirror that creates its own list turns "there is no list named X"
-- a configuration mistake, loudly recoverable -- into a second, silently empty
list in somebody's personal task manager. That rule is not softened by the
existence of setup; it is fenced off from it, and these tests are the fence.

Creating a list through the API is UNVERIFIED: `POST /open/v1/tag` answers 500
on this API, so `POST /open/v1/project` may well do the same. It is deliberately
never probed speculatively -- a half-successful probe would leave a stray list
in a real account that the API cannot delete again. So the code attempts it and
falls back to an instruction the user can follow by hand.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import repos  # noqa: E402
import repo_setup as setup_lib  # noqa: E402
import ticktick  # noqa: E402

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib")
SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


class SyncCannotCreateAListTest(unittest.TestCase):
    """Unchanged behaviour, pinned again because setup now CAN create one."""

    def test_resolve_list_raises_when_the_named_list_does_not_exist(self):
        client = ticktick.Client("t", calls=lambda method, path, payload=None: [
            {"id": "p1", "name": "Something Else"}])

        with self.assertRaises(ticktick.TickTickError) as caught:
            client.resolve_list("Not There")

        self.assertIn("never creates lists itself", str(caught.exception))

    def test_resolve_list_names_the_list_it_could_not_find(self):
        client = ticktick.Client("t", calls=lambda method, path, payload=None: [])

        with self.assertRaises(ticktick.TickTickError) as caught:
            client.resolve_list("Not There")

        self.assertIn("Not There", str(caught.exception))

    def test_resolve_list_never_posts_anything(self):
        """The proof that the refusal is a refusal: a missing list must not
        cause a single write, not even an attempted one."""
        calls = []

        def record(method, path, payload=None):
            calls.append((method, path))
            return []

        with self.assertRaises(ticktick.TickTickError):
            ticktick.Client("t", calls=record).resolve_list("Not There")

        self.assertEqual([("GET", "/project")], calls)

    def test_the_sync_engine_holds_no_reference_to_list_creation(self):
        """Structural, on purpose. A future edit that wires create_list into
        the sync path would pass every behavioural test above, because a fake
        client can always be asked nicely. This one fails instead."""
        for name in (os.path.join(LIB, "sync_core.py"),
                     os.path.join(LIB, "reconcile.py"),
                     os.path.join(SCRIPTS, "sync.py")):
            with open(name, encoding="utf-8") as handle:
                self.assertNotIn("create_list", handle.read(),
                                 "%s reaches into list creation -- the sync path must not"
                                 % os.path.basename(name))


class SetupMayCreateAListTest(unittest.TestCase):
    def test_an_existing_list_is_resolved_and_nothing_is_created(self):
        calls = []

        def record(method, path, payload=None):
            calls.append((method, path))
            return [{"id": "p1", "name": "Widgets"}]

        list_id, created = setup_lib.ensure_list(ticktick.Client("t", calls=record), "Widgets")

        self.assertEqual("p1", list_id)
        self.assertFalse(created)
        self.assertEqual([("GET", "/project")], calls)

    def test_a_missing_list_is_created_and_its_id_returned(self):
        def fake(method, path, payload=None):
            if method == "GET":
                return []
            return {"id": "new-p", "name": payload["name"]}

        list_id, created = setup_lib.ensure_list(ticktick.Client("t", calls=fake), "Widgets")

        self.assertEqual("new-p", list_id)
        self.assertTrue(created)

    def test_a_refused_create_becomes_an_instruction_not_a_dead_end(self):
        """`POST /open/v1/tag` answers 500 on this API; the project endpoint is
        unverified and may do the same. The user must never be left stuck."""
        def fake(method, path, payload=None):
            if method == "GET":
                return []
            raise ticktick.TickTickError("POST /project -> 500")

        with self.assertRaises(setup_lib.SetupFailed) as caught:
            setup_lib.ensure_list(ticktick.Client("t", calls=fake), "Widgets")

        message = str(caught.exception)
        self.assertIn("Widgets", message)
        self.assertIn("by hand", message)
        self.assertIn("again", message, "the fallback must say what to do next")

    def test_a_create_that_answers_without_an_id_is_treated_as_a_failure(self):
        """A 200 that stores nothing is this API's known failure mode (a
        deleted task id answers 200 with a plausible object). An id-less
        reply is not proof of a list."""
        def fake(method, path, payload=None):
            return [] if method == "GET" else {"name": "Widgets"}

        with self.assertRaises(setup_lib.SetupFailed):
            setup_lib.ensure_list(ticktick.Client("t", calls=fake), "Widgets")


class WriteRepoConfigTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)

    def test_the_config_lands_in_the_repos_own_directory(self):
        path = setup_lib.write_repo_config(self.data, "acme__widgets", repo="acme/widgets",
                                           list_id="p1", list_name="Widgets")

        self.assertEqual(os.path.normcase(os.path.join(
            self.data, "repos", "acme__widgets", "config.toml")), os.path.normcase(path))

    def test_the_written_config_is_readable_by_the_engine(self):
        import github

        path = setup_lib.write_repo_config(self.data, "acme__widgets", repo="acme/widgets",
                                           list_id="p1", list_name="Widgets")

        config = github.load_config(path)
        self.assertEqual("acme/widgets", config["repo"])
        self.assertEqual("p1", config["list_id"])
        self.assertEqual("Widgets", config["list_name"])
        self.assertEqual("open-items.toml", config["items_path"])

    def test_a_traversing_slug_never_becomes_a_directory(self):
        with self.assertRaises(repos.SlugError):
            setup_lib.write_repo_config(self.data, "..\\..\\evil", repo="a/b",
                                        list_id="p1", list_name="L")


class OpenItemsTemplateTest(unittest.TestCase):
    """The one file this project writes into somebody else's repository. A
    fixed constraint: the mirrored repo must not learn the mirror exists."""

    def test_the_template_never_mentions_the_mirror(self):
        text = setup_lib.open_items_template().lower()

        for word in ("ticktick", "sync", "mirror"):
            self.assertNotIn(word, text, "the template leaks '%s' into the target repo" % word)

    def test_the_template_parses_as_an_empty_item_list(self):
        import github

        with self.assertRaises(github.GitHubReadFailed):
            # An empty list is legitimate and must NOT raise; a wrong shape
            # must. This asserts the shape by proving the guard has teeth.
            github.toml_to_items("version = 1\n")

        self.assertEqual({}, github.toml_to_items(setup_lib.open_items_template()))

    def test_the_template_declares_the_version_the_reader_expects(self):
        self.assertIn("version = 1", setup_lib.open_items_template())


if __name__ == "__main__":
    unittest.main()

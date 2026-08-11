"""Tests for the GitHub adapter -- against recorded shapes, not the network."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import github  # noqa: E402

ISSUES = [
    {"number": 12, "title": "Pruefung der importierten Datensaetze",
     "url": "https://github.com/globex/toolkit/issues/12",
     "labels": [{"name": "P2"}]},
    {"number": 11, "title": "Neues Werkzeug zur Berichterstellung",
     "url": "https://github.com/globex/toolkit/issues/11",
     "labels": []},
]

ITEMS_TOML = """
version = 1

[[items]]
id = "abgleich-modus-c"
title = "abgleich: record list + priority"
status = "open"
priority = "P1"
note = "Blocks review -> release."

[[items]]
id = "already-done"
title = "Something finished"
status = "done"
"""


class IssueMappingTest(unittest.TestCase):
    def test_every_open_issue_becomes_one_item(self):
        self.assertEqual({"gh-12", "gh-11"}, set(github.issues_to_items(ISSUES)))

    def test_the_title_carries_the_issue_number(self):
        self.assertEqual("#12 Pruefung der importierten Datensaetze",
                         github.issues_to_items(ISSUES)["gh-12"].title)

    def test_the_body_carries_the_key_and_the_url(self):
        body = github.issues_to_items(ISSUES)["gh-12"].body

        self.assertIn("[sync:gh-12]", body)
        self.assertIn("https://github.com/globex/toolkit/issues/12", body)

    def test_a_priority_label_maps_to_a_ticktick_priority(self):
        self.assertEqual(3, github.issues_to_items(ISSUES)["gh-12"].priority)

    def test_an_issue_without_a_priority_label_is_zero(self):
        self.assertEqual(0, github.issues_to_items(ISSUES)["gh-11"].priority)


class ItemFileTest(unittest.TestCase):
    def test_an_open_item_becomes_an_item(self):
        self.assertIn("oi-abgleich-modus-c", github.toml_to_items(ITEMS_TOML))

    def test_a_done_item_is_left_out(self):
        """`done` means: it should no longer appear in the list."""
        self.assertNotIn("oi-already-done", github.toml_to_items(ITEMS_TOML))

    def test_the_note_lands_in_the_body(self):
        self.assertIn("Blocks review -> release.",
                      github.toml_to_items(ITEMS_TOML)["oi-abgleich-modus-c"].body)

    def test_malformed_toml_raises_rather_than_returning_empty(self):
        """Returning empty would mean "everything is done" -- the most dangerous
        possible response to a broken file."""
        with self.assertRaises(github.GitHubReadFailed):
            github.toml_to_items("[[items]\nid = broken")


class ReadFailureTest(unittest.TestCase):
    def test_a_failing_gh_call_raises(self):
        def failing(*args, **kwargs):
            raise OSError("gh not found")

        with self.assertRaises(github.GitHubReadFailed):
            github.read_desired({"repo": "x/y", "items_path": "open-items.toml"}, run=failing)


if __name__ == "__main__":
    unittest.main()

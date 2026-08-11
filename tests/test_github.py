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


class FindingATest(unittest.TestCase):
    def test_a_typo_in_status_raises_and_names_the_value_and_id(self):
        """FINDING A: A typo like 'opne' silently drops the item. Must raise."""
        bad_toml = """
version = 1

[[items]]
id = "test-item"
title = "Test"
status = "opne"
"""
        with self.assertRaises(github.GitHubReadFailed) as ctx:
            github.toml_to_items(bad_toml)

        error_msg = str(ctx.exception)
        self.assertIn("opne", error_msg, "Error must name the bad status value")
        self.assertIn("test-item", error_msg, "Error must name the item id")

    def test_status_must_be_exactly_open_or_done(self):
        """Only 'open' and 'done' are valid."""
        for bad_status in ["active", "pending", "closed", ""]:
            bad_toml = f"""
version = 1

[[items]]
id = "item-{bad_status}"
title = "Test"
status = "{bad_status}"
"""
            with self.assertRaises(github.GitHubReadFailed):
                github.toml_to_items(bad_toml)


class FindingBTest(unittest.TestCase):
    def test_hitting_the_limit_on_issue_list_raises(self):
        """FINDING B: If gh returns exactly --limit issues, we cannot trust
        completeness; raise rather than silently truncate."""
        # Simulate gh returning exactly 200 issues (the limit)
        class FakeResult:
            def __init__(self, stdout):
                self.returncode = 0
                self.stderr = ""
                self.stdout = stdout

        def fake_gh_at_limit(*args, **kwargs):
            if "issue" in args[0]:
                # Return exactly 200 issues (at the limit)
                import json
                issues = [{"number": i, "title": f"Issue {i}",
                          "url": f"https://github.com/x/y/issues/{i}",
                          "labels": []} for i in range(1, 201)]
                return FakeResult(json.dumps(issues))
            # For the item file request
            import json
            import base64
            return FakeResult(json.dumps({"content": base64.b64encode(b"version = 1").decode()}))

        with self.assertRaises(github.GitHubReadFailed) as ctx:
            github.read_desired({"repo": "x/y", "items_path": "open-items.toml"},
                              run=fake_gh_at_limit)

        error_msg = str(ctx.exception)
        self.assertIn("limit", error_msg.lower(), "Error must mention the limit cap")


class FindingCTest(unittest.TestCase):
    def test_bad_item_id_raises_github_read_failed_not_value_error(self):
        """FINDING C: item_key() raises ValueError for bad chars. Convert it to
        GitHubReadFailed for consistency."""
        bad_toml = """
version = 1

[[items]]
id = "item:with:colons"
title = "Test"
"""
        with self.assertRaises(github.GitHubReadFailed):
            github.toml_to_items(bad_toml)


class UntestableBranchesTest(unittest.TestCase):
    def test_gh_exit_non_zero_raises(self):
        """gh exiting with non-zero status must raise."""
        class FakeResult:
            returncode = 1
            stderr = "Permission denied"
            stdout = ""

        def fake_run(*args, **kwargs):
            return FakeResult()

        with self.assertRaises(github.GitHubReadFailed):
            github.read_desired({"repo": "x/y", "items_path": "open-items.toml"},
                              run=fake_run)

    def test_gh_returning_non_json_raises(self):
        """gh returning invalid JSON must raise."""
        def fake_run(*args, **kwargs):
            class FakeResult:
                returncode = 0
                stdout = "not valid json {{"
                stderr = ""
            return FakeResult()

        with self.assertRaises(github.GitHubReadFailed):
            github.read_desired({"repo": "x/y", "items_path": "open-items.toml"},
                              run=fake_run)

    def test_item_file_content_undecodable_raises(self):
        """Item file with invalid base64 or non-UTF8 must raise."""
        class FakeResult:
            def __init__(self, stdout):
                self.returncode = 0
                self.stderr = ""
                self.stdout = stdout

        def fake_run(*args, **kwargs):
            if "issue" in args[0]:
                import json
                return FakeResult(json.dumps([]))  # Empty issue list
            # Return malformed content
            import json
            return FakeResult(json.dumps({"content": "not-valid-base64!!!"}))

        with self.assertRaises(github.GitHubReadFailed):
            github.read_desired({"repo": "x/y", "items_path": "open-items.toml"},
                              run=fake_run)


if __name__ == "__main__":
    unittest.main()

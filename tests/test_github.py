"""Tests for the GitHub adapter -- against recorded shapes, not the network."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import github  # noqa: E402

ISSUES = [
    {"number": 12, "title": "Pruefung der importierten Datensaetze",
     "url": "https://github.com/globex/toolkit/issues/12",
     "labels": [{"name": "P1"}, {"name": "enhancement"}],
     "body": "## Problem\n\nDie Datensaetze im Archiv sind nicht geprueft. Siehe #11 "
             "fuer den Kontext.\n\n## Vorschlag\n\nEin Feld pro Eintrag."},
    {"number": 11, "title": "Neues Werkzeug zur Berichterstellung",
     "url": "https://github.com/globex/toolkit/issues/11",
     "labels": [],
     "body": ""},
]

ITEMS_TOML = """
version = 1

[[items]]
id = "abgleich-modus-c"
title = "abgleich: record list still missing"
status = "open"
tags = ["Draft", "Clarification"]
priority = "P1"
source = "ISSUE-20240115090000"
description = "Blocks review -> release."

[[items]]
id = "datensatz-geprueft-feld"
title = "Structured checked-record provenance field"
status = "open"
tags = ["Clarification"]
related = 12
description = "May become unnecessary if issue 12 removes the ambiguity."

[[items]]
id = "already-done"
title = "Something finished"
status = "done"
"""


class IssueMappingTest(unittest.TestCase):
    def test_every_open_issue_becomes_one_item(self):
        self.assertEqual({"gh-12", "gh-11"}, set(github.issues_to_items(ISSUES)))

    def test_the_title_is_the_github_title_and_nothing_else(self):
        """The `#12 ` prefix this mirror used to prepend was its own invention
        -- and TickTick turns any `#token` in a task's text into a TAG, so it
        was quietly minting tags named `12`, `11`, `14` in the owner's account.
        The issue's name is the issue's name."""
        self.assertEqual("Pruefung der importierten Datensaetze",
                         github.issues_to_items(ISSUES)["gh-12"].title)

    def test_the_body_carries_the_key_and_the_url(self):
        body = github.issues_to_items(ISSUES)["gh-12"].body

        self.assertIn("[sync:gh-12]", body)
        self.assertIn("https://github.com/globex/toolkit/issues/12", body)

    def test_the_body_opens_with_an_excerpt_of_the_issue_body(self):
        """Read cold on a phone, a task must say what it is about without
        opening anything. An excerpt is honest; a paraphrase invented by a
        script is not, so nothing here summarises."""
        body = github.issues_to_items(ISSUES)["gh-12"].body

        self.assertTrue(body.startswith("Die Datensaetze im Archiv sind nicht geprueft."),
                        "body starts: %r" % body[:80])

    def test_the_first_meaningful_paragraph_skips_a_markdown_heading(self):
        """`## Problem` alone says nothing worth reading on a phone."""
        self.assertNotIn("Problem", github.issues_to_items(ISSUES)["gh-12"].body)

    def test_the_marker_comes_last_so_the_description_reads_first(self):
        body = github.issues_to_items(ISSUES)["gh-12"].body

        self.assertTrue(body.rstrip().endswith("[sync:gh-12]"), "body ends: %r" % body[-40:])

    def test_the_url_is_labelled_as_the_source(self):
        body = github.issues_to_items(ISSUES)["gh-12"].body

        self.assertIn("Source: https://github.com/globex/toolkit/issues/12", body)

    def test_an_issue_with_an_empty_body_still_yields_a_usable_task(self):
        """Not every issue has prose. The task must still carry its source and
        its marker rather than breaking."""
        body = github.issues_to_items(ISSUES)["gh-11"].body

        self.assertIn("[sync:gh-11]", body)
        self.assertIn("Source: https://github.com/globex/toolkit/issues/11", body)

    def test_the_german_title_is_passed_through_verbatim(self):
        """The owner reads these on their phone as GitHub wrote them. Nothing
        here translates, trims or decorates an issue title."""
        self.assertEqual("Neues Werkzeug zur Berichterstellung",
                         github.issues_to_items(ISSUES)["gh-11"].title)

    def test_an_issue_title_never_gets_a_related_suffix(self):
        """`(issue N related)` marks an ITEM that points at an issue. An issue
        IS the issue, so the suffix would be nonsense on it."""
        for item in github.issues_to_items(ISSUES).values():
            self.assertNotIn("related", item.title)

    def test_a_priority_label_becomes_the_matching_tag(self):
        self.assertEqual({"p1"}, set(github.issues_to_items(ISSUES)["gh-12"].tags))

    def test_a_non_priority_label_does_not_become_a_tag(self):
        """Only P0-P3 count; the tracker's other labels are none of our
        business and would mint junk tags in the owner's account."""
        self.assertNotIn("enhancement", github.issues_to_items(ISSUES)["gh-12"].tags)

    def test_an_issue_without_a_priority_label_gets_no_tags(self):
        self.assertEqual(frozenset(), github.issues_to_items(ISSUES)["gh-11"].tags)


class ExcerptTest(unittest.TestCase):
    """An issue body is long, markdown-shaped and written for a browser."""

    def test_a_short_body_is_taken_whole(self):
        self.assertEqual("Short and complete.", github.excerpt("Short and complete."))

    def test_a_long_body_is_cut_at_a_sentence_boundary(self):
        text = ("A. " * 120) + "trailing words that overflow the limit"
        cut = github.excerpt(text)

        self.assertLessEqual(len(cut), github.EXCERPT_LIMIT + 3)
        self.assertTrue(cut.rstrip().endswith("."), "cut: %r" % cut[-40:])

    def test_a_long_body_without_sentences_is_cut_at_a_word_boundary(self):
        """Never mid-word: a truncated word reads like a bug."""
        text = "wordy " * 100
        cut = github.excerpt(text)

        self.assertNotIn("wor ", cut)
        self.assertNotIn("wordywordy", cut)
        for piece in cut.replace("...", "").split():
            self.assertEqual("wordy", piece)

    def test_the_lines_of_one_paragraph_are_joined_into_running_text(self):
        """Hard-wrapped markdown must not arrive as a column on a phone."""
        self.assertEqual("one two three", github.excerpt("one two\nthree"))

    def test_an_empty_body_yields_nothing_rather_than_failing(self):
        self.assertEqual("", github.excerpt(""))
        self.assertEqual("", github.excerpt(None))


class GhFieldsTest(unittest.TestCase):
    def test_the_issue_body_is_actually_requested_from_gh(self):
        """Without `body` in the --json list the description silently stays
        empty and every other test here would still pass."""
        captured = []

        class FakeResult:
            def __init__(self, stdout):
                self.returncode = 0
                self.stderr = ""
                self.stdout = stdout

        def capturing(*args, **kwargs):
            captured.append(args[0])
            if "issue" in args[0]:
                import json
                return FakeResult(json.dumps([]))
            import base64
            import json
            return FakeResult(json.dumps(
                {"content": base64.b64encode(b"version = 1\nitems = []").decode()}))

        github.read_desired({"repo": "x/y", "items_path": "open-items.toml"}, run=capturing)

        issue_call = [args for args in captured if "issue" in args][0]
        self.assertIn("body", issue_call[issue_call.index("--json") + 1])


class ItemFileTest(unittest.TestCase):
    def test_an_open_item_becomes_an_item(self):
        self.assertIn("oi-abgleich-modus-c", github.toml_to_items(ITEMS_TOML))

    def test_a_done_item_is_left_out(self):
        """`done` means: it should no longer appear in the list."""
        self.assertNotIn("oi-already-done", github.toml_to_items(ITEMS_TOML))

    def test_the_description_opens_the_body(self):
        """What the owner reads first on their phone."""
        body = github.toml_to_items(ITEMS_TOML)["oi-abgleich-modus-c"].body

        self.assertTrue(body.startswith("Blocks review -> release."), "body starts: %r" % body[:60])

    def test_the_marker_comes_last(self):
        body = github.toml_to_items(ITEMS_TOML)["oi-abgleich-modus-c"].body

        self.assertTrue(body.rstrip().endswith("[sync:oi-abgleich-modus-c]"),
                        "body ends: %r" % body[-40:])

    def test_the_source_sits_between_description_and_marker(self):
        body = github.toml_to_items(ITEMS_TOML)["oi-abgleich-modus-c"].body

        self.assertLess(body.index("Blocks seal"), body.index("Source: ISSUE-20240115090000"))
        self.assertLess(body.index("Source: ISSUE-20240115090000"), body.index("[sync:"))

    def test_the_tags_field_becomes_the_items_tags(self):
        self.assertEqual({"draft", "clarification"},
                         set(github.toml_to_items(ITEMS_TOML)["oi-abgleich-modus-c"].tags))

    def test_an_item_without_tags_has_none(self):
        text = 'version = 1\n\n[[items]]\nid = "a"\ntitle = "A"\n'
        self.assertEqual(frozenset(), github.toml_to_items(text)["oi-a"].tags)

    def test_a_leftover_priority_field_is_ignored_rather_than_fatal(self):
        """The field is meaningless now, but the file is edited by hand in a
        shared repo; a stray one must not abort an unattended run."""
        self.assertIn("oi-abgleich-modus-c", github.toml_to_items(ITEMS_TOML))

    def test_related_appends_the_issue_number_to_the_title(self):
        """The word `issue`, then a bare number -- deliberately NOT `#12`, see
        HashFreeTest below."""
        self.assertEqual("Structured checked-record provenance field (issue 12 related)",
                         github.toml_to_items(ITEMS_TOML)["oi-datensatz-geprueft-feld"].title)

    def test_without_related_the_title_carries_no_suffix(self):
        self.assertEqual("abgleich: record list still missing",
                         github.toml_to_items(ITEMS_TOML)["oi-abgleich-modus-c"].title)

    def test_a_tag_outside_the_permitted_set_raises_and_names_item_and_tag(self):
        """The Open API cannot create, rename or delete a tag (POST /tag is a
        500), so a typo would leave permanent litter in the owner's account
        that only they can clear by hand. Refuse it at the source."""
        bad = ('version = 1\n\n[[items]]\nid = "abgleich-modus-c"\n'
               'title = "T"\ntags = ["Drfat"]\n')

        with self.assertRaises(github.GitHubReadFailed) as caught:
            github.toml_to_items(bad)

        message = str(caught.exception)
        self.assertIn("abgleich-modus-c", message, "Error must name the item")
        self.assertIn("Drfat", message, "Error must name the offending tag")

    def test_malformed_toml_raises_rather_than_returning_empty(self):
        """Returning empty would mean "everything is done" -- the most dangerous
        possible response to a broken file."""
        with self.assertRaises(github.GitHubReadFailed):
            github.toml_to_items("[[items]\nid = broken")


class HashFreeTest(unittest.TestCase):
    """Ranked with the anti-churn test: a regression here pollutes a real
    person's tag list.

    Observed on the live account: TickTick makes a TAG out of any `#token` it
    finds in a task's text. The mirror's own `#12 ` title prefix was therefore
    minting tags named `12`, `11` and `14` in the owner's TickTick -- and the
    Open API cannot delete a tag (POST /tag answers 500), so only the owner
    can clear them, by hand, in the app. The single legitimate way to express
    a tag is the structured `tags` field, which takes plain strings. Hence:
    NO `#` in any string the mirror sends.
    """

    def test_no_issue_item_carries_a_hash_in_its_title_or_body(self):
        for key, item in github.issues_to_items(ISSUES).items():
            self.assertNotIn("#", item.title, "issue %s title would create a tag" % key)
            self.assertNotIn("#", item.body, "issue %s body would create a tag" % key)

    def test_no_file_item_carries_a_hash_in_its_title_or_body(self):
        """Covers an item WITH `related` set -- the suffix that used to read
        `(#12 related)` and now reads `(issue 12 related)`."""
        items = github.toml_to_items(ITEMS_TOML)
        self.assertIn("oi-datensatz-geprueft-feld", items, "the related-bearing item must be in scope")
        for key, item in items.items():
            self.assertNotIn("#", item.title, "item %s title would create a tag" % key)
            self.assertNotIn("#", item.body, "item %s body would create a tag" % key)

    def test_a_hash_in_an_item_title_is_sanitised_not_passed_on(self):
        text = 'version = 1\n\n[[items]]\nid = "abgleich-modus-c"\ntitle = "moot via #12"\n'

        self.assertEqual("moot via issue 12",
                         github.toml_to_items(text)["oi-abgleich-modus-c"].title)

    def test_a_hash_in_an_item_description_is_sanitised(self):
        """The description lands in the task's content, which TickTick scans
        just the same."""
        text = ('version = 1\n\n[[items]]\nid = "abgleich-modus-c"\ntitle = "T"\n'
                'description = "PO decision, or moot via #12"\n')

        body = github.toml_to_items(text)["oi-abgleich-modus-c"].body

        self.assertIn("moot via issue 12", body)
        self.assertNotIn("#", body)

    def test_a_markdown_heading_in_an_issue_body_never_reaches_the_task(self):
        """The sharpest case: issue bodies are full of `##` and `#12`, and now
        that text goes into a description."""
        issues = [{"number": 9, "title": "T", "url": "https://example.invalid/9",
                   "labels": [], "body": "## Heading\n\nSee #7 for context."}]

        item = github.issues_to_items(issues)["gh-9"]

        self.assertNotIn("#", item.body)
        self.assertIn("issue 7", item.body)


class FileShapeTest(unittest.TestCase):
    """FINDING C1: a file that PARSES but is not shaped like an item list.

    Twelve of the fifteen desired entries come from this file. Every case below
    used to return zero items in perfect silence, and the collapse guard waves
    that through because three is not zero -- so twelve real tasks in the
    user's own list would be ticked off. The file must be required to *look*
    like an item list before its contents are believed.
    """

    def test_a_singular_items_typo_raises_instead_of_dropping_everything(self):
        """`[[item]]` instead of `[[items]]` -- valid TOML, wrong shape."""
        text = 'version = 1\n\n[[item]]\nid = "a"\ntitle = "A"\n'
        with self.assertRaises(github.GitHubReadFailed):
            github.toml_to_items(text)

    def test_a_file_truncated_to_its_header_raises(self):
        """Half a file is not an empty list of items."""
        with self.assertRaises(github.GitHubReadFailed):
            github.toml_to_items("version = 1\n")

    def test_an_empty_file_raises(self):
        with self.assertRaises(github.GitHubReadFailed):
            github.toml_to_items("")

    def test_a_missing_version_raises(self):
        text = '[[items]]\nid = "a"\ntitle = "A"\n'
        with self.assertRaises(github.GitHubReadFailed):
            github.toml_to_items(text)

    def test_an_unknown_version_raises_rather_than_guessing_the_layout(self):
        """A version we have never seen may mean anything at all."""
        text = 'version = 99\n\n[[items]]\nid = "a"\ntitle = "A"\n'
        with self.assertRaises(github.GitHubReadFailed):
            github.toml_to_items(text)

    def test_the_error_says_which_file_is_wrong(self):
        with self.assertRaises(github.GitHubReadFailed) as caught:
            github.toml_to_items("version = 1\n")

        self.assertIn("open-items.toml", str(caught.exception))

    def test_a_present_but_genuinely_empty_items_list_is_allowed(self):
        """The one legitimate way to say "nothing is open".

        This is the whole point of the distinction: refuse a file that does not
        have the shape we expect, but believe a well-formed file that says
        there is nothing.
        """
        self.assertEqual({}, github.toml_to_items("version = 1\nitems = []\n"))

    def test_a_file_whose_items_are_all_done_is_allowed(self):
        """Same thing by the other route -- shaped right, nothing open."""
        text = 'version = 1\n\n[[items]]\nid = "a"\ntitle = "A"\nstatus = "done"\n'
        self.assertEqual({}, github.toml_to_items(text))


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


class GhTimeoutTest(unittest.TestCase):
    """A hung `gh` under pythonw.exe is an invisible zombie: it never
    completes, never logs, and the stale-lock logic lets another run start
    every 10 minutes, which can hang the same way. A bounded timeout turns
    that silent accumulation into a single logged failure."""

    def test_a_hung_gh_call_raises_github_read_failed_not_timeout_expired(self):
        """The load-bearing case: a hang must reach the logged failure path
        instead of escaping as an unhandled TimeoutExpired."""
        import subprocess

        def hanging(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

        with self.assertRaises(github.GitHubReadFailed):
            github.read_desired({"repo": "x/y", "items_path": "open-items.toml"}, run=hanging)

    def test_the_error_names_the_timeout_value(self):
        """Someone reading sync.log at 8am should learn what happened, not
        just that something did."""
        import subprocess

        def hanging(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

        with self.assertRaises(github.GitHubReadFailed) as caught:
            github.read_desired({"repo": "x/y", "items_path": "open-items.toml"}, run=hanging)

        self.assertIn(str(github.GH_TIMEOUT_SECONDS), str(caught.exception))

    def test_the_timeout_is_actually_passed_to_run(self):
        """Without this, someone could later delete the argument and every
        other test here would still pass."""
        captured = []

        class FakeResult:
            def __init__(self, stdout):
                self.returncode = 0
                self.stderr = ""
                self.stdout = stdout

        def capturing(*args, **kwargs):
            captured.append(kwargs)
            if "issue" in args[0]:
                import json
                return FakeResult(json.dumps([]))
            import json
            import base64
            return FakeResult(json.dumps({"content": base64.b64encode(b"version = 1\nitems = []").decode()}))

        github.read_desired({"repo": "x/y", "items_path": "open-items.toml"}, run=capturing)

        self.assertTrue(captured, "run() was never called")
        for kwargs in captured:
            self.assertIn("timeout", kwargs)
            self.assertEqual(github.GH_TIMEOUT_SECONDS, kwargs["timeout"])


if __name__ == "__main__":
    unittest.main()

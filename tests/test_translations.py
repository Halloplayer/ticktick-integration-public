"""Tests for cached English translations of GitHub issue descriptions.

The sync has no LLM and no translation API -- adding either would break its
determinism and its zero-dependency rule -- so an issue's English description
is translated by hand, out of band, and cached in issue-descriptions.toml,
fingerprinted by a hash of the exact excerpt it was translated from.
ticktick_sync.github recomputes that hash for every open issue on every run:

- a matching hash uses the cached English text
- a differing hash, or no entry at all, falls back to the German excerpt,
  visibly prefixed `[untranslated] ` and counted

A silently stale translation would claim the issue still says what it no
longer does -- confidently, in the owner's own task list. The prefix and the
count exist so that never happens quietly.
"""
import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import github  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _issue(number, body):
    return {"number": number, "title": "T", "url": "https://example.invalid/%d" % number,
            "labels": [], "body": body}


class CacheHitTest(unittest.TestCase):
    def test_a_matching_hash_yields_the_english_description(self):
        """The excerpt is hashed AFTER sanitising and trimming -- the exact
        string that would otherwise have reached TickTick -- so the cache key
        used here must be computed the same way."""
        body = "Ein deutscher Absatz, der uebersetzt werden muss."
        digest = hashlib.sha256(github.excerpt(body).encode("utf-8")).hexdigest()
        translations = {9: (digest, "An English paragraph that needed translating.")}

        items = github.issues_to_items([_issue(9, body)], translations)

        self.assertIn("An English paragraph that needed translating.", items["gh-9"].body)
        self.assertNotIn("[untranslated]", items["gh-9"].body)
        self.assertFalse(items["gh-9"].untranslated)


class CacheMissTest(unittest.TestCase):
    def test_a_differing_hash_falls_back_to_the_german_excerpt_prefixed_and_counted(self):
        """A stale cache entry (the issue changed upstream) must not be
        trusted -- it would state something the source no longer says."""
        body = "Ein deutscher Absatz, der sich seitdem geaendert hat."
        translations = {9: ("0" * 64, "A stale English translation.")}

        items = github.issues_to_items([_issue(9, body)], translations)

        self.assertTrue(items["gh-9"].body.startswith("[untranslated] " + github.excerpt(body)),
                        "body starts: %r" % items["gh-9"].body[:120])
        self.assertNotIn("A stale English translation.", items["gh-9"].body)
        self.assertTrue(items["gh-9"].untranslated)


class NoEntryTest(unittest.TestCase):
    def test_a_number_with_no_cached_entry_behaves_like_a_differing_hash(self):
        body = "Niemand hat das hier je uebersetzt."

        items = github.issues_to_items([_issue(9, body)], {})

        self.assertTrue(items["gh-9"].body.startswith("[untranslated] " + github.excerpt(body)))
        self.assertTrue(items["gh-9"].untranslated)

    def test_no_translations_argument_at_all_behaves_the_same_way(self):
        """`translations` is not optional in spirit -- read_desired() always
        supplies it -- but a caller passing nothing must not be treated any
        differently from one passing an empty cache."""
        body = "Niemand hat das hier je uebersetzt."

        items = github.issues_to_items([_issue(9, body)])

        self.assertTrue(items["gh-9"].body.startswith("[untranslated] " + github.excerpt(body)))
        self.assertTrue(items["gh-9"].untranslated)


class GuardTest(unittest.TestCase):
    """Issues 11, 12 and 14 are the three real, currently-open issues this
    mirror translates by hand (see issue-descriptions.toml). This test reads
    their real bodies from a committed fixture -- no `gh` call, no network --
    and proves the cache is CURRENT: if somebody edits one of those issues
    upstream without updating the cache, this test fails the build instead of
    the mirror quietly showing German again.
    """

    def test_all_three_real_issues_resolve_to_a_cached_translation(self):
        with open(os.path.join(FIXTURES, "wiki_issues_11_12_14.json"), encoding="utf-8") as handle:
            issues = json.load(handle)
        translations = github.load_translations()

        items = github.issues_to_items(issues, translations)

        for number in (11, 12, 14):
            key = "gh-%d" % number
            self.assertIn(key, items)
            self.assertFalse(
                items[key].untranslated,
                "issue %d fell back to German -- issue-descriptions.toml is stale "
                "(the issue body changed upstream and needs re-translating)" % number)


if __name__ == "__main__":
    unittest.main()

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

from ticktick_sync import github, models  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _issue(number, body, title="T"):
    return {"number": number, "title": title, "url": "https://example.invalid/%d" % number,
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


class TitleCacheHitTest(unittest.TestCase):
    """An issue's title is German too (see 'Naming' in README.md), so it goes
    through the same hash-guarded cache as the description -- `title_sha256`
    over the sanitised title, `title_en` the hand-translated text. Computed
    by code, never hand-copied: a wrong hash silently disables the check."""

    def test_a_matching_title_hash_yields_the_translated_first_line(self):
        title = "Ein deutscher Titel, der uebersetzt werden muss."
        body = "Ein deutscher Absatz."
        title_digest = hashlib.sha256(models.sanitise(title).encode("utf-8")).hexdigest()
        desc_digest = hashlib.sha256(github.excerpt(body).encode("utf-8")).hexdigest()
        translations = {9: (desc_digest, "An English paragraph.",
                            title_digest, "An English title.")}

        items = github.issues_to_items([_issue(9, body, title=title)], translations)

        self.assertTrue(items["gh-9"].body.startswith("An English title.\n\n"),
                        "body starts: %r" % items["gh-9"].body[:100])
        self.assertNotIn("[untranslated] " + title, items["gh-9"].body)
        self.assertFalse(items["gh-9"].untranslated)


class TitleCacheMissTest(unittest.TestCase):
    def test_a_differing_title_hash_yields_the_untranslated_prefix_and_counts(self):
        """A stale title cache (the issue was renamed upstream) must not be
        trusted -- same discipline as a stale description."""
        title = "Ein deutscher Titel, der sich seitdem geaendert hat."
        body = "Ein deutscher Absatz."
        desc_digest = hashlib.sha256(github.excerpt(body).encode("utf-8")).hexdigest()
        translations = {9: (desc_digest, "An English paragraph.",
                            "0" * 64, "A stale English title.")}

        items = github.issues_to_items([_issue(9, body, title=title)], translations)

        self.assertTrue(items["gh-9"].body.startswith("[untranslated] " + title),
                        "body starts: %r" % items["gh-9"].body[:100])
        self.assertNotIn("A stale English title.", items["gh-9"].body)
        self.assertTrue(items["gh-9"].untranslated)


class GuardTest(unittest.TestCase):
    """Issues 11, 12 and 14 are the three real, currently-open issues this
    mirror translates by hand (see issue-descriptions.toml). This test reads
    their real bodies from a committed fixture -- no `gh` call, no network --
    and proves the cache is CURRENT: if somebody edits one of those issues
    upstream without updating the cache, this test fails the build instead of
    the mirror quietly showing German again.
    """

    TITLE_TRANSLATIONS = {
        11: "A new question-generation tool — self-checking test questions "
            "that expose as many coverage gaps as possible",
        12: "Verification that imported records resolve — does the index "
            "find the cited entries at all?",
        14: "Draw the seam — knowledge base and storage adapter as separate "
            "trees in the same repo",
    }

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

    def test_all_three_real_issue_titles_resolve_to_the_cached_translation(self):
        """Read cold on a phone, the first line of the task must be the
        English title -- not the German one this mirror is required to keep
        as the task's own name."""
        with open(os.path.join(FIXTURES, "wiki_issues_11_12_14.json"), encoding="utf-8") as handle:
            issues = json.load(handle)
        translations = github.load_translations()

        items = github.issues_to_items(issues, translations)

        for number, title_en in self.TITLE_TRANSLATIONS.items():
            key = "gh-%d" % number
            self.assertTrue(
                items[key].body.startswith(title_en + "\n\n"),
                "issue %d body starts: %r" % (number, items[key].body[:120]))


if __name__ == "__main__":
    unittest.main()

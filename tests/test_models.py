"""Tests for the mirror's data shapes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import models  # noqa: E402


class KeyTest(unittest.TestCase):
    def test_an_issue_key_is_derived_from_its_number(self):
        self.assertEqual("gh-12", models.issue_key(12))

    def test_an_item_key_is_derived_from_its_id(self):
        self.assertEqual("oi-abgleich-modus-c", models.item_key("abgleich-modus-c"))

    def test_the_two_key_spaces_cannot_collide(self):
        """Both sources land in ONE list; a collision would silently overwrite
        the wrong entry."""
        self.assertNotEqual(models.issue_key(12), models.item_key("12"))

    def test_item_key_accepts_ordinary_slug_form(self):
        """Hyphens, dots, and underscores are all permitted."""
        self.assertEqual("oi-abgleich-modus-c", models.item_key("abgleich-modus-c"))
        self.assertEqual("oi-example.value", models.item_key("example.value"))
        self.assertEqual("oi-example_value", models.item_key("example_value"))

    def test_item_key_raises_for_space(self):
        """A space in the id would break the marker round-trip."""
        with self.assertRaises(ValueError) as cm:
            models.item_key("gap fill")
        self.assertIn("gap fill", str(cm.exception))

    def test_item_key_raises_for_colon(self):
        """A colon in the id would break the marker round-trip."""
        with self.assertRaises(ValueError) as cm:
            models.item_key("entwurf:true")
        self.assertIn("entwurf:true", str(cm.exception))

    def test_item_key_raises_for_non_ascii(self):
        """Non-ASCII characters in the id would break the marker round-trip."""
        with self.assertRaises(ValueError) as cm:
            models.item_key("prüfung")
        self.assertIn("prüfung", str(cm.exception))

    def test_item_key_raises_for_trailing_newline(self):
        """A trailing newline would break the marker round-trip. Regression
        test for Python regex $-anchor matching before trailing newline."""
        with self.assertRaises(ValueError) as cm:
            models.item_key("abc\n")
        self.assertIn("abc\n", str(cm.exception))

    def test_marker_and_key_from_body_round_trip_for_valid_ids(self):
        """The invariant that marker() and key_from_body() round-trip must hold
        for every id that item_key() accepts."""
        valid_ids = ["abgleich-modus-c", "simple", "with.dots", "with_underscores",
                     "mixed-2024_review.final"]
        for item_id in valid_ids:
            key = models.item_key(item_id)
            body = models.marker(key) + "\nsome description"
            recovered = models.key_from_body(body)
            self.assertEqual(key, recovered,
                           f"Round-trip failed for id '{item_id}': "
                           f"marker(item_key('{item_id}')) -> key_from_body() != item_key('{item_id}')")


class TagTest(unittest.TestCase):
    """Tags replaced priorities entirely; the vocabulary is closed."""

    def test_the_permitted_vocabulary_is_exactly_the_agreed_twelve(self):
        """Two priority namespaces, deliberately: a plain `P2` is an AGREED
        priority on a real tracker issue, an underscored `_P2` a PROPOSED one
        on something not yet promoted. Both stay visible, and neither can be
        mistaken for the other."""
        self.assertEqual({"P0", "P1", "P2", "P3",
                          "_P0", "_P1", "_P2", "_P3",
                          "Draft", "Task", "Bug", "Clarification"},
                         set(models.PERMITTED_TAGS))

    def test_a_permitted_tag_comes_back_in_its_canonical_spelling(self):
        self.assertEqual("Draft", models.check_tag("draft"))
        self.assertEqual("P1", models.check_tag("p1"))

    def test_an_underscore_priority_keeps_its_underscore(self):
        self.assertEqual("_P2", models.check_tag("_p2"))

    def test_the_two_priority_namespaces_are_distinct_tags(self):
        """`P2` and `_P2` must never normalise to the same thing -- the whole
        point is that the list can carry both without ambiguity."""
        self.assertNotEqual(models.tag_set(["P2"]), models.tag_set(["_P2"]))

    def test_a_tag_outside_the_vocabulary_raises(self):
        """A typo must fail loudly rather than quietly minting junk in the
        owner's TickTick account -- the API cannot delete a tag afterwards."""
        with self.assertRaises(ValueError) as caught:
            models.check_tag("Drfat")

        self.assertIn("Drfat", str(caught.exception))

    def test_tag_set_lowercases_and_forgets_order(self):
        self.assertEqual(models.tag_set(["Draft", "P1"]), models.tag_set(["p1", "draft"]))

    def test_tag_set_yields_a_frozenset_so_dataclass_equality_just_works(self):
        self.assertIsInstance(models.tag_set(["Draft"]), frozenset)

    def test_display_tags_are_canonical_and_deterministically_ordered(self):
        self.assertEqual(["P1", "Draft"], models.display_tags(models.tag_set(["draft", "p1"])))

    def test_display_tags_pass_an_unknown_tag_through_rather_than_crashing(self):
        """Tags read BACK from TickTick are whatever the account holds; a hand-
        added one must not halt an unattended run."""
        self.assertEqual(["whatever"], models.display_tags(frozenset({"whatever"})))

    def test_ticktick_priorities_are_gone_for_good(self):
        self.assertFalse(hasattr(models, "priority_of"))
        self.assertFalse(hasattr(models, "PRIORITIES"))


class SanitiseTest(unittest.TestCase):
    """The single chokepoint for the one character that must never get out.

    TickTick makes a TAG out of any `#token` in a task's text, and its API
    cannot delete a tag again -- so a `#` reaching the account leaves litter
    only the owner can clear by hand. Issue bodies are full of them (markdown
    headings, cross-references) and now feed task descriptions, so the fix
    belongs in ONE place rather than sprinkled over the mappers.
    """

    def test_a_cross_reference_becomes_readable_prose(self):
        self.assertEqual("See issue 12 for context.", models.sanitise("See #12 for context."))

    def test_a_reference_attached_to_the_preceding_word_does_not_collide(self):
        """The COMMON case, not an edge one.

        `owner/repo#10` is the repo-qualified reference style these issue
        bodies actually use, and the first version of this sanitiser -- which
        substituted `issue \\1` with no separator -- turned it into
        `acme/widgetsissue 10` in the live desired set.
        """
        self.assertEqual("globex/toolkit issue 10",
                         models.sanitise("acme/widgets#10"))

    def test_several_attached_references_in_one_line_each_separate(self):
        self.assertEqual("a issue 1 b issue 2", models.sanitise("a#1 b#2"))

    def test_a_markdown_heading_loses_its_hashes(self):
        self.assertEqual("Problem", models.sanitise("## Problem"))

    def test_a_trailing_hash_is_dropped_without_leaving_a_gap(self):
        self.assertEqual("done", models.sanitise("done #"))

    def test_a_lone_hash_between_words_collapses_the_whitespace_it_leaves(self):
        self.assertEqual("before after", models.sanitise("before # after"))

    def test_line_structure_survives(self):
        """Bodies are built line by line; the sanitiser must not flatten them
        into one paragraph."""
        self.assertEqual("Source: x\n[sync:oi-a]",
                         models.sanitise("Source: x\n[sync:oi-a]"))

    def test_text_without_a_hash_is_returned_unchanged(self):
        self.assertEqual("Pruefung der importierten Datensaetze",
                         models.sanitise("Pruefung der importierten Datensaetze"))

    def test_an_item_sanitises_itself_so_no_source_can_forget_to(self):
        """A chokepoint that has to be remembered is not a chokepoint."""
        item = models.Item(key="oi-a", title="moot via #12", body="see #7")

        self.assertEqual("moot via issue 12", item.title)
        self.assertEqual("see issue 7", item.body)


class MarkerTest(unittest.TestCase):
    def test_a_body_carrying_a_marker_yields_its_key(self):
        body = models.marker("gh-12") + "\nhttps://example.invalid/12"

        self.assertEqual("gh-12", models.key_from_body(body))

    def test_a_marker_at_the_very_end_of_a_body_is_still_found(self):
        """The description now comes FIRST and the marker last, so that the
        task reads well in the app. The whole recovery path depends on the
        marker still being found there."""
        body = "A sentence about the work.\n\nSource: ISSUE-1\n[sync:oi-a]"

        self.assertEqual("oi-a", models.key_from_body(body))

    def test_a_related_title_suffix_is_not_mistaken_for_a_marker(self):
        """Titles now end in ` [Issue Related -> 12]`, which is square-bracketed
        like the sync marker itself. Written down as a test so nobody has to
        re-reason about the collision later: the marker regex demands the
        literal `sync:` prefix and a key charset with no spaces in it, so the
        suffix cannot satisfy it -- and the marker lives in the body anyway,
        never in the title.
        """
        for suffix in ("Some item [Issue -> 12]",
                       "Some item [Issue Related -> 12]",
                       "Some item [Draft Related -> Ein langer deutscher Titel]"):
            self.assertIsNone(models.key_from_body(suffix), suffix)

    def test_a_suffix_shaped_line_beside_a_real_marker_does_not_win(self):
        """Belt and braces: both present, the real key comes back."""
        body = "Some item [Draft Related -> Ein Titel]\n\nSource: x\n[sync:oi-a]"

        self.assertEqual("oi-a", models.key_from_body(body))

    def test_a_marker_is_found_after_a_leading_title_translation_line(self):
        """The body may now open with an English title-translation line
        before the description (see the title_en / title_sha256 mechanism in
        ticktick_sync.github) -- key_from_body must still recover the key
        regardless, since it is the only thing preventing duplicate tasks."""
        body = "An English title.\n\nAn English description.\n\nSource: x\n[sync:oi-a]"

        self.assertEqual("oi-a", models.key_from_body(body))

    def test_a_body_without_a_marker_yields_none(self):
        self.assertIsNone(models.key_from_body("made by hand"))

    def test_an_empty_body_yields_none(self):
        self.assertIsNone(models.key_from_body(""))


if __name__ == "__main__":
    unittest.main()

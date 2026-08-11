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

    def test_the_permitted_vocabulary_is_exactly_the_agreed_eight(self):
        self.assertEqual({"P0", "P1", "P2", "P3", "Draft", "Task", "Bug", "Clarification"},
                         set(models.PERMITTED_TAGS))

    def test_a_permitted_tag_comes_back_in_its_canonical_spelling(self):
        self.assertEqual("Draft", models.check_tag("draft"))
        self.assertEqual("P1", models.check_tag("p1"))

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


class MarkerTest(unittest.TestCase):
    def test_a_body_carrying_a_marker_yields_its_key(self):
        body = models.marker("gh-12") + "\nhttps://example.invalid/12"

        self.assertEqual("gh-12", models.key_from_body(body))

    def test_a_body_without_a_marker_yields_none(self):
        self.assertIsNone(models.key_from_body("made by hand"))

    def test_an_empty_body_yields_none(self):
        self.assertIsNone(models.key_from_body(""))


if __name__ == "__main__":
    unittest.main()

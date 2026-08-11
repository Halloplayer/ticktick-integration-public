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


class PriorityTest(unittest.TestCase):
    def test_p0_and_p1_are_high(self):
        self.assertEqual(5, models.priority_of("P0"))
        self.assertEqual(5, models.priority_of("P1"))

    def test_p2_is_medium(self):
        self.assertEqual(3, models.priority_of("P2"))

    def test_an_absent_priority_is_none(self):
        self.assertEqual(0, models.priority_of(None))

    def test_an_unknown_label_is_none_rather_than_a_crash(self):
        """A new label on the tracker must not halt a background run."""
        self.assertEqual(0, models.priority_of("P7"))


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

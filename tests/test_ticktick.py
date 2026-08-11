"""Tests for the TickTick adapter -- against the shapes recorded in Task 1."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ticktick_sync import models, ticktick  # noqa: E402
from ticktick_sync.models import marker  # noqa: E402

PROJECT_DATA = {
    "project": {"id": "p1", "name": "globex-toolkit"},
    "tasks": [
        {"id": "t1", "title": "Retrieval verification",
         "content": marker("gh-12") + "\nhttps://example.invalid/12",
         "tags": ["p1", "draft"], "status": 0},
        {"id": "t2", "title": "Made by hand", "content": "no marker",
         "status": 0},
        {"id": "t3", "title": "Question generation",
         "content": marker("gh-11"), "status": 2},
    ],
}


class ReadTasksTest(unittest.TestCase):
    def test_a_task_with_a_marker_is_keyed_by_it(self):
        self.assertIn("gh-12", ticktick.tasks_from_payload(PROJECT_DATA))

    def test_a_task_without_a_marker_is_ignored(self):
        """Hand-made tasks belong to the user. The mirror does not touch them
        and certainly does not complete them."""
        self.assertEqual({"gh-12", "gh-11"}, set(ticktick.tasks_from_payload(PROJECT_DATA)))

    def test_a_completed_task_is_marked_completed(self):
        """status 2 == done."""
        self.assertTrue(ticktick.tasks_from_payload(PROJECT_DATA)["gh-11"].completed)

    def test_an_open_task_is_not_marked_completed(self):
        self.assertFalse(ticktick.tasks_from_payload(PROJECT_DATA)["gh-12"].completed)

    def test_the_task_id_is_carried_through(self):
        self.assertEqual("t1", ticktick.tasks_from_payload(PROJECT_DATA)["gh-12"].task_id)

    def test_the_tags_are_read_back_normalised(self):
        """The account holds them lowercase; normalising on the way in is what
        lets the comparison stay quiet."""
        self.assertEqual(models.tag_set(["Draft", "P1"]),
                         ticktick.tasks_from_payload(PROJECT_DATA)["gh-12"].tags)

    def test_a_task_without_tags_has_an_empty_set_not_none(self):
        self.assertEqual(frozenset(), ticktick.tasks_from_payload(PROJECT_DATA)["gh-11"].tags)


class WritePayloadTest(unittest.TestCase):
    """What actually goes over the wire.

    TickTick priorities are not used at all any more, and `priority: 0` is not
    the same as saying nothing: it would overwrite a priority the owner set by
    hand on a mirrored task. Section 8 of docs/api-notes.md measured that an
    omitted field is left alone -- so omitting is how we keep our hands off.
    """

    def _client_capturing(self, captured):
        def calls(method, path, payload=None):
            captured.append((method, path, payload))
            return {"id": "new-1"}
        return ticktick.Client("token", calls=calls)

    def _item(self):
        return models.Item(key="oi-x", title="An item", body=marker("oi-x"),
                           tags=models.tag_set(["Draft", "P1"]))

    def test_create_sends_no_priority_field_at_all(self):
        captured = []
        self._client_capturing(captured).create("p1", self._item())

        self.assertNotIn("priority", captured[0][2])

    def test_update_sends_no_priority_field_at_all(self):
        captured = []
        self._client_capturing(captured).update("p1", "t1", self._item())

        self.assertNotIn("priority", captured[0][2])

    def test_create_sends_the_tags_as_a_list_of_plain_strings(self):
        captured = []
        self._client_capturing(captured).create("p1", self._item())

        self.assertEqual(["P1", "Draft"], captured[0][2]["tags"])

    def test_update_sends_the_tags_too(self):
        captured = []
        self._client_capturing(captured).update("p1", "t1", self._item())

        self.assertEqual(["P1", "Draft"], captured[0][2]["tags"])

    def test_nothing_sent_over_the_wire_carries_a_hash(self):
        """The second half of the no-`#` rule: even if an Item slipped through
        carrying one, this is the last place to notice."""
        captured = []
        client = self._client_capturing(captured)
        client.create("p1", self._item())
        client.update("p1", "t1", self._item())

        for _, _, payload in captured:
            for value in payload.values():
                self.assertNotIn("#", str(value))


class ResolveListTest(unittest.TestCase):
    PROJECTS = [{"id": "p1", "name": "🛡Work"}, {"id": "p2", "name": "Private"}]

    def _client(self, projects=None):
        return ticktick.Client("token",
                               calls=lambda *a, **k: self.PROJECTS if projects is None else projects)

    def test_an_id_that_exists_resolves_to_itself(self):
        self.assertEqual("p1", self._client().resolve_list("🛡Work", list_id="p1"))

    def test_an_id_whose_name_does_not_match_raises(self):
        """The name is the guard on the id. Mirroring 18 machine tasks into the
        wrong list of somebody's personal task manager must fail loudly."""
        with self.assertRaises(ticktick.TickTickError) as caught:
            self._client().resolve_list("🛡Work", list_id="p2")

        self.assertIn("p2", str(caught.exception))

    def test_an_unknown_id_raises(self):
        with self.assertRaises(ticktick.TickTickError):
            self._client().resolve_list("🛡Work", list_id="nope")

    def test_without_an_id_it_falls_back_to_the_name(self):
        self.assertEqual("p1", self._client().resolve_list("🛡Work"))

    def test_an_unknown_name_raises_and_says_to_create_it(self):
        """The mirror NEVER creates a list -- otherwise a bug sprays lists into
        the account."""
        client = self._client(projects=[{"id": "p2", "name": "Private"}])

        with self.assertRaises(ticktick.TickTickError) as caught:
            client.resolve_list("🛡Work")

        self.assertIn("Work", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

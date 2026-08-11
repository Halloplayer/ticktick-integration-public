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
         "tags": ["p1", "draft"], "priority": 3, "status": 0},
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

    def test_a_priority_left_over_from_before_is_read_back(self):
        """Not to use it -- to notice it. A priority the mirror never set is
        drift, and it cannot be cleared without first being seen."""
        self.assertEqual(3, ticktick.tasks_from_payload(PROJECT_DATA)["gh-12"].priority)

    def test_a_task_without_a_priority_reads_back_as_zero(self):
        self.assertEqual(0, ticktick.tasks_from_payload(PROJECT_DATA)["gh-11"].priority)


class WritePayloadTest(unittest.TestCase):
    """What actually goes over the wire.

    TickTick priorities are not used at all any more -- and saying that to
    this API means sending `priority: 0`, not omitting the field.

    Section 8 of docs/api-notes.md measured that `POST /task/{id}` MERGES.
    An omitted field therefore keeps whatever was there, which is exactly
    what happened: after the first deploy, nine of the fifteen live tasks
    still flew their old priority flags beside the new P0/P1/P2 tags -- the
    duplicated signal this whole change existed to remove. To a merging API,
    an explicit zero is the only way to assert that there is no priority.
    """

    def _client_capturing(self, captured):
        def calls(method, path, payload=None):
            captured.append((method, path, payload))
            return {"id": "new-1"}
        return ticktick.Client("token", calls=calls)

    def _item(self):
        return models.Item(key="oi-x", title="An item", body=marker("oi-x"),
                           tags=models.tag_set(["Draft", "P1"]))

    def test_create_clears_the_priority_explicitly(self):
        captured = []
        self._client_capturing(captured).create("p1", self._item())

        self.assertEqual(0, captured[0][2]["priority"])

    def test_update_clears_the_priority_explicitly(self):
        """The one that actually matters: a task created before this change
        carries a priority, and only an explicit zero takes it away."""
        captured = []
        self._client_capturing(captured).update("p1", "t1", self._item())

        self.assertEqual(0, captured[0][2]["priority"])

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

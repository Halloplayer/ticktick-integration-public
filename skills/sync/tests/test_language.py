"""Tests for the per-repo `language` setting.

German is the default for any repo that never says otherwise: most of the
issues this mirror reads are written in German, and translating them is
opt-in work a human has to keep up with by hand (see
tests/test_translations.py). `language = "de"` switches the whole
translation subsystem off -- no cache lookup, no `[untranslated]` prefix, no
translated-title line, no `untranslated=N` counter, because none of that
means anything when nothing is being translated. `language = "en"` is
exactly today's behaviour, unchanged.

The one rule that actually matters: an existing English repo
(`globex/toolkit`) must never revert to German by silently picking up
the new default. A config with no `language` key migrates to "en" if its
repo directory holds a non-empty `issue-descriptions.toml`, and to "de"
otherwise -- and the decision is written back into config.toml so it happens
exactly once. See `github._migrate_language`.
"""
import base64
import contextlib
import hashlib
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "lib"))

import github, models  # noqa: E402


def _issue(number, body, title="T"):
    return {"number": number, "title": title, "url": "https://example.invalid/%d" % number,
            "labels": [], "body": body}


class DeDescriptionTest(unittest.TestCase):
    def test_the_description_is_the_bare_excerpt_with_no_untranslated_prefix(self):
        """No translations argument at all -- as if issue-descriptions.toml
        never existed for this repo -- must not produce the `[untranslated]`
        fallback in "de": there is nothing to be untranslated FROM."""
        body = "Ein deutscher Absatz, der niemals uebersetzt werden soll."

        items = github.issues_to_items([_issue(9, body)], language="de")

        self.assertEqual(github.excerpt(body), items["gh-9"].body.splitlines()[0])
        self.assertNotIn("[untranslated]", items["gh-9"].body)
        self.assertFalse(items["gh-9"].untranslated)

    def test_a_cached_translation_is_ignored_too(self):
        """Even when a translations cache IS supplied (a caller could pass
        one by mistake), "de" must not consult it -- German means nothing is
        translated, not "translate unless told not to"."""
        body = "Ein deutscher Absatz."
        digest = hashlib.sha256(github.excerpt(body).encode("utf-8")).hexdigest()
        translations = {9: (digest, "An English paragraph.")}

        items = github.issues_to_items([_issue(9, body)], translations, language="de")

        self.assertNotIn("An English paragraph.", items["gh-9"].body)
        self.assertIn(github.excerpt(body), items["gh-9"].body)
        self.assertFalse(items["gh-9"].untranslated)


class DeTitleTest(unittest.TestCase):
    def test_no_translated_title_line_is_prepended_even_with_a_cached_title_en(self):
        """The fixture "has a title_en" -- a cache entry that would, in "en",
        supply the body's opening line -- and "de" must still show none."""
        title = "Ein deutscher Titel, der uebersetzt werden muss."
        body = "Ein deutscher Absatz."
        title_digest = hashlib.sha256(models.sanitise(title).encode("utf-8")).hexdigest()
        desc_digest = hashlib.sha256(github.excerpt(body).encode("utf-8")).hexdigest()
        translations = {9: (desc_digest, "An English paragraph.",
                            title_digest, "An English title.")}

        items = github.issues_to_items([_issue(9, body, title=title)], translations, language="de")

        self.assertFalse(items["gh-9"].body.startswith("An English title."))
        self.assertNotIn("An English title.", items["gh-9"].body)
        self.assertFalse(items["gh-9"].untranslated)


TITLE_EN_ITEM_TOML = """
version = 1

[[items]]
id = "abgleich-modus-c"
title = "Ein deutscher Entwurfstitel"
title_en = "An English title"
status = "open"
tags = ["Draft"]
source = "ISSUE-20240115090000"
description = "Die deutsche Beschreibung."
"""


class DeTomlTitleEnTest(unittest.TestCase):
    """`open-items.toml`'s own `title_en` (an issue draft's hand-written
    title translation, no hash, sitting right beside the German title in the
    same file) must be gated by `language` exactly like the issue-side
    translations -- not rendered just because the field happens to be
    present. A repo whose file was copied from an English one, or switched
    from "en" to "de" later, would otherwise silently keep showing an
    English first line ahead of an all-German body -- precisely the
    translation artifact "de" promises to remove, and a mixed-language body
    besides."""

    def test_de_renders_no_title_en_line_the_body_opens_with_the_description(self):
        items = github.toml_to_items(TITLE_EN_ITEM_TOML, language="de")

        body = items["oi-abgleich-modus-c"].body
        self.assertTrue(body.startswith("Die deutsche Beschreibung."),
                        "body starts: %r" % body[:60])
        self.assertNotIn("An English title", body)

    def test_en_still_renders_it_guard_against_over_correcting(self):
        items = github.toml_to_items(TITLE_EN_ITEM_TOML, language="en")

        body = items["oi-abgleich-modus-c"].body
        self.assertTrue(body.startswith("An English title\n\n"),
                        "body starts: %r" % body[:60])

    def test_the_default_language_still_renders_it(self):
        """No `language` argument at all -- every pre-existing direct call to
        toml_to_items() in test_github.py -- must keep behaving as it always
        did."""
        items = github.toml_to_items(TITLE_EN_ITEM_TOML)

        self.assertTrue(items["oi-abgleich-modus-c"].body.startswith("An English title\n\n"))

    def test_switching_a_config_from_en_to_de_changes_the_rendered_body_title_en_kept_intact(self):
        """The file itself is untouched by the switch -- only the rendering
        changes. Proves the gate lives in the reader, not in the data."""
        en_body = github.toml_to_items(TITLE_EN_ITEM_TOML, language="en")["oi-abgleich-modus-c"].body
        de_body = github.toml_to_items(TITLE_EN_ITEM_TOML, language="de")["oi-abgleich-modus-c"].body

        self.assertNotEqual(en_body, de_body)
        self.assertIn("An English title", en_body)
        self.assertNotIn("An English title", de_body)
        # The source text itself carries title_en regardless of which way it
        # was just rendered -- switching back to "en" loses nothing.
        self.assertIn('title_en = "An English title"', TITLE_EN_ITEM_TOML)

    def test_read_desired_in_de_does_not_render_a_draft_title_en_either(self):
        """End to end through read_desired(): a "de" config must gate the
        item-file title too, not just the issue-side one."""
        def fake_run(args, **kwargs):
            class Result:
                returncode = 0
                stderr = ""
                if "issue" in args:
                    stdout = json.dumps([])
                else:
                    stdout = json.dumps(
                        {"content": base64.b64encode(TITLE_EN_ITEM_TOML.encode("utf-8")).decode()})
            return Result()

        desired = github.read_desired(
            {"repo": "acme/widgets", "items_path": "open-items.toml", "language": "de"},
            run=fake_run)

        self.assertNotIn("An English title", desired["oi-abgleich-modus-c"].body)


class DeUntranslatedCounterTest(unittest.TestCase):
    def test_read_desired_never_marks_a_de_item_untranslated(self):
        """Through the real read_desired() path, with a `run` fake standing in
        for `gh` -- an issue with no matching cache entry at all must still
        come back untranslated=False in "de"."""
        def fake_run(args, **kwargs):
            class Result:
                returncode = 0
                stderr = ""
                if "issue" in args:
                    stdout = json.dumps([_issue(9, "Ein deutscher Satz ohne Cache-Eintrag.")])
                else:
                    stdout = json.dumps(
                        {"content": base64.b64encode(b"version = 1\nitems = []").decode("ascii")})
            return Result()

        desired = github.read_desired(
            {"repo": "acme/widgets", "items_path": "open-items.toml", "language": "de"},
            run=fake_run, translations_path="/does/not/exist/issue-descriptions.toml")

        self.assertFalse(desired["gh-9"].untranslated)
        self.assertNotIn("[untranslated]", desired["gh-9"].body)

    def test_issue_descriptions_toml_is_not_read_at_all(self):
        """Its absence must not even be attempted -- load_translations() is
        never called, so a translations_path pointing nowhere is not an
        error and is never opened."""
        opened = []
        real_open = open

        def spying_open(path, *args, **kwargs):
            opened.append(str(path))
            return real_open(path, *args, **kwargs)

        def fake_run(args, **kwargs):
            class Result:
                returncode = 0
                stderr = ""
                if "issue" in args:
                    stdout = json.dumps([_issue(9, "Ein deutscher Satz.")])
                else:
                    stdout = json.dumps(
                        {"content": base64.b64encode(b"version = 1\nitems = []").decode("ascii")})
            return Result()

        marker_path = "issue-descriptions-should-not-be-opened.toml"
        with mock.patch("builtins.open", side_effect=spying_open):
            github.read_desired(
                {"repo": "acme/widgets", "items_path": "open-items.toml", "language": "de"},
                run=fake_run, translations_path=marker_path)

        self.assertFalse(any(marker_path in path for path in opened),
                         "issue-descriptions.toml was opened even though language is 'de'")


class EnUnchangedTest(unittest.TestCase):
    """"en" must behave exactly as it always did -- pinned explicitly here,
    on top of the untouched pre-existing assertions in test_translations.py
    and test_github.py, which still pass unmodified."""

    def test_explicit_en_matches_the_pre_existing_default_behaviour(self):
        body = "Ein deutscher Absatz ohne Cache-Eintrag."
        issue = _issue(9, body)

        default_items = github.issues_to_items([issue])
        explicit_items = github.issues_to_items([issue], language="en")

        self.assertEqual(default_items["gh-9"].body, explicit_items["gh-9"].body)
        self.assertEqual(default_items["gh-9"].untranslated, explicit_items["gh-9"].untranslated)
        self.assertIn("[untranslated]", explicit_items["gh-9"].body)

    def test_read_desired_with_an_explicit_en_config_still_reads_the_translations_file(self):
        digest = hashlib.sha256(github.excerpt("Ein deutscher Absatz.").encode("utf-8")).hexdigest()

        with tempfile.TemporaryDirectory() as tmp:
            translations_path = os.path.join(tmp, "issue-descriptions.toml")
            with open(translations_path, "w", encoding="utf-8") as handle:
                handle.write('[[issues]]\nnumber = 9\nsource_sha256 = "%s"\n'
                             'description = "An English paragraph."\n' % digest)

            def fake_run(args, **kwargs):
                class Result:
                    returncode = 0
                    stderr = ""
                    if "issue" in args:
                        stdout = json.dumps([_issue(9, "Ein deutscher Absatz.")])
                    else:
                        stdout = json.dumps(
                            {"content": base64.b64encode(b"version = 1\nitems = []").decode("ascii")})
                return Result()

            desired = github.read_desired(
                {"repo": "acme/widgets", "items_path": "open-items.toml", "language": "en"},
                run=fake_run, translations_path=translations_path)

        self.assertIn("An English paragraph.", desired["gh-9"].body)
        self.assertFalse(desired["gh-9"].untranslated)


class LoadConfigMigrationTest(unittest.TestCase):
    """`load_config` is where the migration actually runs -- every repo's
    config passes through it (sync.py's sync_one calls it directly). Each
    test here uses its own temp directory, never the committed `legacy/`
    seed, so a test run can never mutate a file this repo tracks in git.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config_path = os.path.join(self.tmp, "config.toml")

    def write_config(self, extra=""):
        with open(self.config_path, "w", encoding="utf-8") as handle:
            handle.write('repo = "globex/toolkit"\nitems_path = "open-items.toml"\n'
                         'list_id = "p1"\nlist_name = "L"\n' + extra)

    def write_translations(self, entries):
        path = os.path.join(self.tmp, "issue-descriptions.toml")
        with open(path, "w", encoding="utf-8") as handle:
            for number in entries:
                handle.write('[[issues]]\nnumber = %d\nsource_sha256 = "%s"\n'
                             'description = "x"\n\n' % (number, "a" * 64))

    def test_a_config_with_a_populated_translations_file_migrates_to_english(self):
        """Pins the highest-value case: the live globex-toolkit repo, English
        today, with hand-written translations already in the cache. Silently
        defaulting this to German would revert real, hand-written work with
        no error at all -- the worst outcome available here."""
        self.write_config()
        self.write_translations([11, 12, 14])

        config = github.load_config(self.config_path)

        self.assertEqual("en", config["language"])
        with open(self.config_path, encoding="utf-8") as handle:
            self.assertIn('language = "en"', handle.read())

    def test_a_config_with_no_translations_file_migrates_to_german(self):
        self.write_config()
        # No issue-descriptions.toml at all in self.tmp.

        config = github.load_config(self.config_path)

        self.assertEqual("de", config["language"])
        with open(self.config_path, encoding="utf-8") as handle:
            self.assertIn('language = "de"', handle.read())

    def test_a_config_with_an_empty_translations_file_also_migrates_to_german(self):
        """An empty `[[issues]]`-less file is the same as no file at all --
        there is nothing hand-written to lose."""
        self.write_config()
        path = os.path.join(self.tmp, "issue-descriptions.toml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")

        config = github.load_config(self.config_path)

        self.assertEqual("de", config["language"])

    def test_migration_is_idempotent(self):
        self.write_config()
        self.write_translations([11])

        first = github.load_config(self.config_path)
        with open(self.config_path, encoding="utf-8") as handle:
            after_first = handle.read()
        second = github.load_config(self.config_path)
        with open(self.config_path, encoding="utf-8") as handle:
            after_second = handle.read()

        self.assertEqual("en", first["language"])
        self.assertEqual("en", second["language"])
        self.assertEqual(after_first, after_second,
                         "a second load rewrote the file instead of finding the key "
                         "already there")
        self.assertEqual(1, after_second.count("language ="),
                         "the language key was written more than once")

    def test_a_config_that_already_names_a_language_is_never_touched(self):
        """The already-explicit case -- proves the migration path is not
        taken at all once a repo has an opinion of its own, even one that
        disagrees with what the heuristic would have picked."""
        self.write_config(extra='language = "en"\n')
        # No translations file -- the heuristic alone would have said "de".

        with open(self.config_path, encoding="utf-8") as handle:
            before = handle.read()

        config = github.load_config(self.config_path)

        with open(self.config_path, encoding="utf-8") as handle:
            after = handle.read()
        self.assertEqual("en", config["language"])
        self.assertEqual(before, after)


class BrandNewConfigTest(unittest.TestCase):
    """The setup path: a config freshly written by `write_repo_config` for a
    repository nobody has mirrored before. Distinct from migration above --
    this config already carries an explicit `language` key from the moment
    it is created, written by setup itself rather than inferred later.
    """

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)

    def test_a_brand_new_config_defaults_to_german(self):
        import repo_setup

        path = repo_setup.write_repo_config(
            self.data, "acme__widgets", repo="acme/widgets", list_id="p1", list_name="Widgets")

        config = github.load_config(path)

        self.assertEqual("de", config["language"])

    def test_the_language_can_be_chosen_explicitly_at_setup_time(self):
        import repo_setup

        path = repo_setup.write_repo_config(
            self.data, "acme__widgets", repo="acme/widgets", list_id="p1", list_name="Widgets",
            language="en")

        config = github.load_config(path)

        self.assertEqual("en", config["language"])


class InvalidLanguageTest(unittest.TestCase):
    def test_an_invalid_language_value_raises_naming_the_repo_and_the_value(self):
        """Same style as the existing tag/status validation in github.py --
        e.g. `"Item '%s' has invalid status '%s' (must be 'open' or 'done')"`
        -- name what is wrong AND on what, so the log line is diagnosable on
        its own."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('repo = "acme/widgets"\nitems_path = "open-items.toml"\n'
                             'list_id = "p1"\nlist_name = "L"\nlanguage = "fr"\n')

            with self.assertRaises(github.GitHubReadFailed) as caught:
                github.load_config(path)

        message = str(caught.exception)
        self.assertIn("acme/widgets", message, "the error must name the repo")
        self.assertIn("fr", message, "the error must name the bad value")


class SyncSummaryLineTest(unittest.TestCase):
    """End to end through sync.main(): a "de" repo's summary line in
    sync.log/stdout must never carry `untranslated=`, even for an issue whose
    body has no cached translation at all -- because in "de" there is no
    such thing as an untranslated issue.
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
        import sync
        self.sync = sync
        self.data_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data_dir, True)
        self._old_env = os.environ.get("TICKTICK_INTEGRATION_DATA")
        os.environ["TICKTICK_INTEGRATION_DATA"] = self.data_dir
        importlib.reload(sync)
        with open(os.path.join(self.data_dir, ".env"), "w", encoding="utf-8") as handle:
            handle.write("TICKTICK_TOKEN=fake-token-for-tests\n")
        self.repo_dir = os.path.join(self.data_dir, "repos", "acme__widgets")
        os.makedirs(self.repo_dir)
        with open(os.path.join(self.repo_dir, "config.toml"), "w", encoding="utf-8") as handle:
            handle.write('repo = "acme/widgets"\nitems_path = "open-items.toml"\n'
                         'list_name = "Widgets"\nlanguage = "de"\n')

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("TICKTICK_INTEGRATION_DATA", None)
        else:
            os.environ["TICKTICK_INTEGRATION_DATA"] = self._old_env
        importlib.reload(self.sync)

    class FakeClient:
        def __init__(self):
            self.tasks = {}

        def resolve_list(self, name, list_id=None):
            return "p1"

        def read_tasks(self, project_id):
            return dict(self.tasks)

        def create(self, project_id, item):
            task_id = "new-" + item.key
            self.tasks[item.key] = models.Task(
                key=item.key, task_id=task_id, title=item.title, body=item.body, tags=item.tags)
            return task_id

        def update(self, project_id, task_id, item):
            pass

        def complete(self, project_id, task_id):
            pass

    def _fake_gh(self, args, run):
        if "issue" in args:
            return json.dumps([_issue(9, "Ein deutscher Satz ohne Cache-Eintrag.")])
        return json.dumps({"content": base64.b64encode(b"version = 1\nitems = []").decode("ascii")})

    def test_the_summary_line_never_carries_untranslated_for_a_de_repo(self):
        out = io.StringIO()
        with mock.patch.object(self.sync.github, "_gh", side_effect=self._fake_gh), \
             mock.patch.object(self.sync.ticktick, "Client", lambda *a, **kw: self.FakeClient()), \
             contextlib.redirect_stdout(out):
            exit_code = self.sync.main(["--repo", "acme__widgets"])

        printed = out.getvalue()
        self.assertEqual(0, exit_code)
        self.assertIn("acme__widgets ok desired=", printed)
        self.assertNotIn("untranslated", printed)


if __name__ == "__main__":
    unittest.main()

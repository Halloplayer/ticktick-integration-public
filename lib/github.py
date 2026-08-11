"""Read the desired state through `gh` -- with the login that is already there.

Both sources come from GitHub: the open issues, and the neutral item list in
the same repo. Going through `gh` rather than a local clone is deliberate: a
run then also sees what somebody else just pushed, without anyone calling
`git fetch` here.
"""
import base64
import hashlib
import json
import pathlib
import re
import subprocess
import tomllib

from models import (CLARIFICATION_TAG, DRAFT_TAG, NON_ISSUE_TAGS, PLAIN_PRIORITY_TAGS,
                     PRIORITY_TAGS, PROPOSED_PRIORITY_TAGS, Item, check_tag, issue_key,
                     item_key, marker, sanitise, tag_set)


class GitHubReadFailed(Exception):
    """The desired state could not be read -- the run must abort."""


# Only these labels say anything the mirror mirrors. Any other label on the
# tracker is somebody else's bookkeeping and would mint a junk tag.
PRIORITY_LABELS = ("P0", "P1", "P2", "P3")

# Three prefixes, all at the very START of a title -- an explicit owner
# decision (2026-08-11), even though the `Draft Related` form can run past 100
# characters and will dominate the visible line on a phone: what a task IS,
# what it POINTS AT and which KIND of thing it points at is meant to be the
# first thing read, ahead of the name itself. Never `#12`: a `#` would create
# a tag in the owner's account.
ISSUE_PREFIX = "[Issue -> %d] "            # a promoted tracker issue
ISSUE_RELATED_PREFIX = "[Issue Related -> %d] "    # an item about an issue
DRAFT_RELATED_PREFIX = "[Draft Related -> %s] "    # a clarification about a draft

# Nothing in this module removes `#` itself. Every string reaching TickTick is
# cleaned once, in models.sanitise(), which Item applies to its own title and
# body -- see there for why a `#` must never get out.

# A task description is read on a phone, at a glance. Broad enough that someone
# who sees ONLY the task understands what to do, why it matters and what is at
# stake -- one sentence names the work but leaves all three unanswered -- and
# still short of a wall of text.
EXCERPT_LIMIT = 560

# Lines that carry no information once torn out of their markdown context.
_FURNITURE = re.compile(r"^(#{1,6}\s|#{1,6}$|<!--|-->|[-*_]{3,}$|\|)")


def _is_furniture(line):
    return bool(_FURNITURE.match(line))


def _trim(text, limit):
    """Cut at a sentence boundary if there is a sensible one, else at a word.

    Never mid-word: a truncated word reads like a bug rather than an excerpt.
    """
    if len(text) <= limit:
        return text
    window = text[:limit]
    sentence = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence > limit // 2:
        return window[:sentence + 1]
    space = window.rfind(" ")
    return (window[:space] if space > 0 else window) + "..."


def excerpt(text, limit=EXCERPT_LIMIT):
    """The first meaningful paragraph of an issue body, as running text.

    An excerpt, never a summary: a paraphrase produced by a script claims an
    understanding it does not have, and the owner cannot tell the two apart
    from their phone. Headings, comment markers and rules are skipped because
    `## Problem` on its own says nothing worth reading.
    """
    if not text:
        return ""
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        meaningful = [line for line in lines if not _is_furniture(line)]
        if meaningful:
            return _trim(" ".join(meaningful), limit)
    return ""


# Marks a description that could not be translated -- either no cached entry
# exists for the issue, or the cached one no longer matches (the issue
# changed upstream since somebody translated it by hand). Visible on purpose:
# a silently stale translation would state something the source no longer
# says, confidently, in the owner's own task list.
UNTRANSLATED_PREFIX = "[untranslated] "

# issue-descriptions.toml is PER REPOSITORY, and lives in that repository's own
# data directory (`repos/<slug>/issue-descriptions.toml`). It used to sit at
# the plugin root, which was always wrong: the plugin root is a version-scoped
# cache directory that a plugin update replaces WHOLESALE, so a user's own
# hand-written translations were one update away from deletion. It does not
# belong in the mirrored repo either -- it is tooling for the mirror, not that
# repo's content. Hence no default path here: the caller says which repo's
# cache it means, and "this repo has none" is a legitimate answer.


def load_translations(path=None):
    """number -> (source_sha256, description, title_sha256, title_en), read
    from one repository's issue-descriptions.toml.

    The sync has no LLM and no translation API -- either would break its
    determinism and its zero-dependency rule -- so translation happens out of
    band, by a human, and this file is the cache of that work. A missing file
    -- or `path=None`, the normal state of a newly set-up repository whose
    issues nobody has translated -- is not a read failure: it behaves exactly
    like a present-but-empty cache, and every issue falls back to its own
    excerpt (see _translated_description) rather than aborting the run over a
    file whose only job is a cosmetic one.

    `title_sha256`/`title_en` are optional per entry -- unlike `source_sha256`
    /`description`, which every entry has always carried. An issue not yet
    given a title translation simply gets none (see _translated_title):
    `entry.get(...)` rather than `entry[...]` so an older or partial entry
    does not become a read failure over a cosmetic field.
    """
    if path is None:
        return {}
    try:
        with open(path, "rb") as handle:
            payload = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    return {entry["number"]: (entry["source_sha256"], entry["description"],
                              entry.get("title_sha256"), entry.get("title_en"))
            for entry in payload.get("issues", [])}


def _translated_description(number, excerpt_text, translations):
    """(description, is_untranslated) for one issue's excerpt.

    Hashed AFTER sanitising -- the exact string that would otherwise have
    reached TickTick -- so the fingerprint matches what a reader actually
    sees, and a change to markup a reader never sees (rather than to the
    words themselves) cannot falsely invalidate a good translation.

    An issue with no excerpt at all (an empty body) has nothing to translate:
    it is left as an empty description, exactly as before this cache
    existed, rather than counted as "untranslated" for text that was never
    there to translate.
    """
    sanitised = sanitise(excerpt_text) if excerpt_text else ""
    if not sanitised:
        return "", False
    digest = hashlib.sha256(sanitised.encode("utf-8")).hexdigest()
    cached = translations.get(number)
    if cached is not None and cached[0] == digest:
        return cached[1], False
    return UNTRANSLATED_PREFIX + sanitised, True


def _translated_title(number, title, translations):
    """(title_line, is_untranslated) for one issue's title, or (None, False)
    if no title translation was ever attempted for this issue.

    Unlike the description, `title_sha256` is OPTIONAL per cache entry: it is
    a newer field, being added incrementally, and an issue nobody has
    translated the title of yet must not suddenly grow an "[untranslated]"
    line it never had before -- that would fire on every entry (and every
    test fixture) still on the old two-field shape. Once an entry DOES carry
    `title_sha256`, though, the same discipline as the description applies: a
    matching hash uses the cached English title, anything else (a stale hash
    or -- once present -- a missing one) falls back to the German title
    itself, prefixed and counted, exactly like _translated_description.
    """
    cached = translations.get(number)
    title_sha256 = cached[2] if cached is not None and len(cached) > 2 else None
    if title_sha256 is None:
        return None, False
    sanitised = sanitise(title) if title else ""
    if not sanitised:
        return None, False
    digest = hashlib.sha256(sanitised.encode("utf-8")).hexdigest()
    if digest == title_sha256:
        return cached[3], False
    return UNTRANSLATED_PREFIX + sanitised, True


# Generous for a slow network, far below the 10-minute stale-lock threshold,
# so a hang always resolves into a logged error before anything else reacts
# to it. Without this, a hung `gh` under pythonw.exe is an invisible
# zombie -- it never completes, never logs, and the stale-lock logic lets
# another run start every 10 minutes, which can hang the same way.
GH_TIMEOUT_SECONDS = 60


# The two rendering languages. German is the DEFAULT for any repository that
# never says otherwise: most issues in the repos this mirrors are written in
# German, and translating is opt-in work somebody has to keep up with by
# hand (see load_translations). "en" is the historical behaviour -- the
# whole translation subsystem below this point -- kept exactly as it was for
# any repo that already relies on it.
SUPPORTED_LANGUAGES = ("de", "en")
DEFAULT_LANGUAGE = "de"


def _check_language(value, repo):
    """Same discipline as the item file's tag/status checks: name the value
    AND the thing it is wrong on, so a typo in config.toml is diagnosable
    from the log line alone."""
    if value not in SUPPORTED_LANGUAGES:
        raise GitHubReadFailed(
            "config for '%s' has invalid language '%s' (must be 'de' or 'en')"
            % (repo, value))


def _migrate_language(config, path):
    """Decide `language` for a config that does not name one yet, and WRITE
    the decision back into `path` so the inference happens exactly once.

    The rule that matters: an already-live English repo must never revert to
    German by accident. `globex/toolkit` is configured in English
    today and has a populated `issue-descriptions.toml` holding hand-written
    translations -- if it silently picked up the new German default, every
    one of those would go dark on the next run with no error at all, because
    German is a perfectly legitimate configuration. So: a config with no
    `language` key whose repo directory holds a non-empty
    `issue-descriptions.toml` migrates to "en"; one with no translations file
    (or none at all -- the normal state of a brand-new repo) migrates to the
    DEFAULT_LANGUAGE, "de". Either way the key is written into the file
    itself, explicitly, so a second load sees it already set and does
    nothing -- see load_config.
    """
    sibling = pathlib.Path(path).parent / "issue-descriptions.toml"
    language = "en" if load_translations(str(sibling)) else DEFAULT_LANGUAGE
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(
            "\n# Rendering language for GitHub-issue titles/descriptions: \"de\" "
            "(source language,\n# nothing translated -- the default) or \"en\" "
            "(uses issue-descriptions.toml).\n# Set once, automatically, on first "
            "load of a config with no language key; edit\n# by hand to change it.\n"
            "language = \"%s\"\n" % language)
    config["language"] = language
    return config


def load_config(path):
    with open(path, "rb") as handle:
        config = tomllib.load(handle)
    language = config.get("language")
    if language is None:
        config = _migrate_language(config, path)
    else:
        _check_language(language, config.get("repo", "?"))
    return config


def issues_to_items(payload, translations=None, language="en"):
    """The issue's own name, its own priority label, nothing added.

    The title is passed through exactly as GitHub returns it -- the issues are
    German and stay German. It carries no `#<number> ` prefix of the mirror's
    own old invention (that one was creating tags in the owner's account, see
    models.sanitise). The number returns as the `[Issue -> N] ` PREFIX
    instead, ahead of the name -- an explicit owner decision, not a `#`.

    `language` gates the entire translation subsystem below, one repo at a
    time (config.toml's `language`, resolved by load_config/read_desired --
    see DEFAULT_LANGUAGE). Two branches, deliberately kept apart rather than
    threaded through the "en" machinery with an early-exit: "de" means NOTHING
    is translated, so there is no cache to consult, no hash to compare and
    nothing that can go stale -- the description is simply the excerpt, as
    written, and `untranslated` is always False, because there is nothing
    that could be untranslated. This is the default for any repo that has
    never said otherwise.

    In "en" (kept exactly as it always behaved, for any repo relying on it):
    the description is an excerpt of the issue body, but a task's description
    must always be English (see UNTRANSLATED_PREFIX / _translated_description),
    while an issue body is German. `translations` is the cache read by
    load_translations(); read_desired() always supplies it, so a description
    reaching TickTick is either a hand-translated cache hit or a visibly
    marked, counted fallback -- never a silent German excerpt. The marker
    comes last, because the first line is what the app shows.

    The TITLE itself stays German (see above) -- but in "en", when a cached
    English translation exists for it (_translated_title), that translation
    opens the BODY as its own first line, ahead of the description, so a
    reader sees what the task is in English before anything else. The title
    used for this is the issue's own, via `issue.get("title")` -- NOT the
    mirrored Item's title built below, which by then carries the
    ISSUE_PREFIX. The prefix annotates the mirrored task; it is not part of
    what GitHub called the issue and must not be translated (see also
    test_the_title_prefix_does_not_leak_into_the_bodys_translated_first_line
    in test_github.py, which guards this seam).
    """
    translations = translations if translations is not None else {}
    items = {}
    for issue in payload:
        key = issue_key(issue["number"])
        labels = [label["name"] for label in issue.get("labels", [])]
        tags = tag_set(label for label in labels if label in PRIORITY_LABELS)
        parts = []
        if language == "de":
            title_line, title_untranslated = None, False
            description, desc_untranslated = excerpt(issue.get("body")), False
        else:
            title_line, title_untranslated = _translated_title(
                issue["number"], issue.get("title"), translations)
            description, desc_untranslated = _translated_description(
                issue["number"], excerpt(issue.get("body")), translations)
        if title_line:
            parts += [title_line, ""]
        if description:
            parts += [description, ""]
        if issue.get("url"):
            parts.append("Source: %s" % issue["url"])
        parts.append(marker(key))
        title = "%s%s" % (ISSUE_PREFIX % issue["number"], issue["title"])
        items[key] = Item(key=key, title=title, body="\n".join(parts), tags=tags,
                          untranslated=desc_untranslated or title_untranslated)
    return items


SUPPORTED_ITEMS_VERSION = 1


def _check_shape(payload):
    """Refuse a file that does not LOOK like an item list.

    Most of the mirrored work comes from this one file, and anything missing
    from the desired set gets ticked off in the user's real list. The collapse
    guard cannot help here: it only refuses a fall to zero, and a file that
    yields nothing still leaves the GitHub issues standing, so the set merely
    shrinks -- 15 to 3 -- and the guard waves it through.

    Hence the distinction this function draws. "The file does not have the
    shape we expect" -- no `items` key at all, no `version`, a `version` from
    some other layout -- is a read failure and aborts the run. "The file says
    there is nothing open" -- an `items` list that is present and genuinely
    empty -- is a legitimate answer and passes straight through.
    """
    version = payload.get("version")
    if version is None:
        raise GitHubReadFailed(
            "open-items.toml has no `version` key -- refusing to read it as an "
            "item list. A truncated or half-written file looks exactly like "
            "this, and believing it would complete every item it fails to "
            "mention.")
    if isinstance(version, bool) or version != SUPPORTED_ITEMS_VERSION:
        raise GitHubReadFailed(
            "open-items.toml says version %r, but this mirror only understands "
            "version %d. A layout it does not know may mean anything at all, so "
            "it stops rather than guess." % (version, SUPPORTED_ITEMS_VERSION))
    if "items" not in payload:
        raise GitHubReadFailed(
            "open-items.toml has no `items` table -- a `[[item]]` typo or a "
            "truncated file parses cleanly and yields nothing, which would tick "
            "off every item it should have listed. Write `items = []` to say "
            "that nothing is open.")
    if not isinstance(payload["items"], list):
        raise GitHubReadFailed(
            "open-items.toml has an `items` key of type %s; it must be a list "
            "of [[items]] tables." % type(payload["items"]).__name__)


def _check_tag_scope(item_id, tags, is_draft):
    """Three disjoint cases; this enforces the two that live in the file.

    An item is an unpromoted issue draft exactly when it names a `source`. It
    then carries `Draft`, optionally beside ONE proposed priority (`_P0`-`_P3`)
    taken from its own frontmatter. An item without a `source` carries exactly
    one of Task, Bug, Clarification, and no priority of either kind.

    A PLAIN priority never appears here: it states an AGREED priority on a
    promoted tracker issue, and this file holds only things that are not that.
    The underscore form exists so a draft's proposal can still be shown
    without being read as the agreement.

    A real check rather than a convention: the file is hand-edited in a
    shared repo, and a tag in the wrong case would not break anything
    visibly -- it would quietly produce a wrong list, which is the kind of
    error nobody goes looking for.
    """
    priorities = tags & PRIORITY_TAGS
    if len(priorities) > 1:
        raise GitHubReadFailed(
            "Item '%s' carries %d priority tags (%s); an item has at most one."
            % (item_id, len(priorities),
               ", ".join(sorted(check_tag(tag) for tag in priorities))))

    for tag in sorted(tags):
        if tag in PLAIN_PRIORITY_TAGS:
            raise GitHubReadFailed(
                "Item '%s' is tagged '%s'. A plain priority states an AGREED priority "
                "on a promoted tracker issue, and this file holds only unpromoted "
                "drafts and work that is not an issue at all. For a draft's proposed "
                "priority write '_%s' instead."
                % (item_id, check_tag(tag), check_tag(tag)))
        if tag in PROPOSED_PRIORITY_TAGS:
            if not is_draft:
                raise GitHubReadFailed(
                    "Item '%s' is tagged '%s', but it has no `source`, so it is not a "
                    "draft and has no proposed priority. Work that is not an issue "
                    "takes Task, Bug or Clarification alone."
                    % (item_id, check_tag(tag)))
            if DRAFT_TAG not in tags:
                raise GitHubReadFailed(
                    "Item '%s' is tagged '%s' without `Draft`. A proposed priority "
                    "qualifies a draft; on its own it says nothing."
                    % (item_id, check_tag(tag)))
        if tag == DRAFT_TAG and not is_draft:
            raise GitHubReadFailed(
                "Item '%s' is tagged '%s', but it has no `source`, so it is not an "
                "issue draft. Work that is not an issue takes Task, Bug or "
                "Clarification." % (item_id, check_tag(tag)))
        if tag in NON_ISSUE_TAGS and is_draft:
            raise GitHubReadFailed(
                "Item '%s' is tagged '%s', but it names a `source`, which makes it an "
                "issue draft. Task, Bug and Clarification describe work that is NOT an "
                "issue, so they cannot sit beside `Draft`. Put the substance in the "
                "description instead." % (item_id, check_tag(tag)))
    if DRAFT_TAG in tags:
        company = tags - {DRAFT_TAG} - PROPOSED_PRIORITY_TAGS
        if company:
            raise GitHubReadFailed(
                "Item '%s' is tagged 'Draft' together with %s. `Draft` takes no "
                "company except one proposed priority (_P0-_P3)."
                % (item_id, ", ".join(sorted(check_tag(tag) for tag in company))))
    elif tags & NON_ISSUE_TAGS and len(tags) > 1:
        raise GitHubReadFailed(
            "Item '%s' carries %s; work that is not an issue takes exactly one of "
            "Task, Bug or Clarification and nothing else."
            % (item_id, ", ".join(sorted(check_tag(tag) for tag in tags))))


def _link_prefix(item_id, raw, tags, is_draft, known):
    """Which of the three prefixes this item earns, and whether it may.

    A clarification about a draft names that draft by ID and the title is
    looked up here. The alternative -- storing the title in both places --
    would duplicate a long German string that drifts the moment the draft is
    renamed, and a link showing a title the draft no longer has is worse than
    no link at all, because it looks right.
    """
    related = raw.get("related")
    related_draft = raw.get("related_draft")

    if related is not None and related_draft is not None:
        raise GitHubReadFailed(
            "Item '%s' names both `related` and `related_draft`. They render two "
            "different suffixes and an item has one name -- pick the one that says "
            "what this actually hangs off." % item_id)

    if is_draft and (related is not None or related_draft is not None):
        raise GitHubReadFailed(
            "Item '%s' is an issue draft (it names a `source`) and cannot point at "
            "anything: a draft is the thing that gets pointed AT. Put the link on "
            "the clarification instead." % item_id)

    if related is not None:
        if isinstance(related, bool) or not isinstance(related, int):
            raise GitHubReadFailed(
                "Item '%s' has `related = %r`; it must be an issue NUMBER."
                % (item_id, related))
        return ISSUE_RELATED_PREFIX % related

    if related_draft is not None:
        if CLARIFICATION_TAG not in tags:
            raise GitHubReadFailed(
                "Item '%s' names `related_draft` but is not tagged Clarification. "
                "Pointing at a draft is what a clarification does; anything else "
                "belongs to itself." % item_id)
        target = known.get(related_draft)
        if target is None:
            raise GitHubReadFailed(
                "Item '%s' has `related_draft = '%s'`, but no item with that id "
                "exists in this file. The link is by id precisely so a rename "
                "cannot go unnoticed -- this is that check firing."
                % (item_id, related_draft))
        target_title, target_is_draft = target
        if not target_is_draft:
            raise GitHubReadFailed(
                "Item '%s' has `related_draft = '%s'`, but that item is not an issue "
                "draft (it names no `source`). A draft link must point at a draft."
                % (item_id, related_draft))
        return DRAFT_RELATED_PREFIX % target_title

    return ""


def _known_items(payload):
    """id -> (title, is_draft) for EVERY item in the file, whatever its status.

    Deliberately including `done` ones: a clarification may outlive the draft
    it hangs off, and resolving its link must not start aborting the whole run
    the moment that draft is ticked off.
    """
    known = {}
    for raw in payload["items"]:
        if isinstance(raw, dict) and "id" in raw and "title" in raw:
            known[raw["id"]] = (raw["title"], bool(raw.get("source")))
    return known


def toml_to_items(text):
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise GitHubReadFailed("open-items.toml is broken: %s" % error)

    _check_shape(payload)

    known = _known_items(payload)
    items = {}
    for raw in payload["items"]:
        status = raw.get("status", "open")
        if status not in {"open", "done"}:
            raise GitHubReadFailed("Item '%s' has invalid status '%s' (must be 'open' or 'done')" %
                                 (raw.get("id", "?"), status))
        if status != "open":
            continue
        item_id = raw.get("id", "?")
        try:
            key = item_key(raw["id"])
        except ValueError as error:
            raise GitHubReadFailed(str(error)) from error

        try:
            tags = tag_set(check_tag(tag) for tag in raw.get("tags", []))
        except ValueError as error:
            raise GitHubReadFailed("Item '%s': %s" % (item_id, error)) from error

        is_draft = bool(raw.get("source"))
        _check_tag_scope(item_id, tags, is_draft=is_draft)

        # A draft's own title is German (see 'Naming' in README.md); its
        # translation sits right beside it as `title_en`, with no hash --
        # the two are hand-edited together in the same file, so an edit to
        # one is visible next to the other and drift cannot hide. Meaningless
        # on anything else: an item without a `source` is already titled in
        # English, so a translation of it would say nothing, and gets caught
        # here rather than silently ignored -- same discipline as the tag
        # and status checks above.
        title_en = raw.get("title_en")
        if title_en is not None and not is_draft:
            raise GitHubReadFailed(
                "Item '%s' has `title_en`, but it has no `source`, so it is not an "
                "issue draft. Only a draft keeps its original (German) title -- an "
                "item without one is already titled in English, and a translation "
                "of it would say nothing." % item_id)

        # The prefix goes first -- an explicit owner decision (2026-08-11),
        # even for the `Draft Related` form, which can run past 100 characters
        # with a ~130-character German draft title behind it. Square brackets
        # cannot be confused with the sync marker -- that one requires a
        # literal `sync:` and a key charset without spaces, and lives in the
        # body, never the title (see models.key_from_body and its tests).
        title = _link_prefix(item_id, raw, tags, is_draft, known) + raw["title"]

        # The translation opens the body, ahead of the description, so a
        # reader sees the English title before anything else -- then a blank
        # line, exactly like the description/Source/marker layout below.
        lead = [title_en, ""] if title_en else []

        # Description first, marker last: the app shows the opening lines, so
        # that is where the explanation belongs. `note` stays supported for
        # anything a contributor adds beside the description.
        prose = [text for text in (raw.get("description"), raw.get("note")) if text]
        trailer = []
        # The id is the human-readable provenance, the URL the tap-through --
        # an id alone cannot be opened from a phone. One line carries both.
        provenance = [text for text in (raw.get("source"), raw.get("source_url")) if text]
        if provenance:
            trailer.append("Source: %s" % " - ".join(provenance))
        if raw.get("owner"):
            trailer.append("With: %s" % raw["owner"])
        trailer.append(marker(key))
        parts = lead + prose + ([""] if prose else []) + trailer

        items[key] = Item(key=key, title=title, body="\n".join(parts), tags=tags)
    return items


def _gh(args, run):
    try:
        done = run(["gh"] + args, capture_output=True, text=True, encoding="utf-8",
                   timeout=GH_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise GitHubReadFailed("gh %s did not finish within %d seconds -- treating it as "
                             "hung and aborting the run" % (" ".join(args), GH_TIMEOUT_SECONDS))
    except OSError as error:
        raise GitHubReadFailed("could not start gh: %s" % error)
    if done.returncode != 0:
        raise GitHubReadFailed("gh %s failed: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout


def read_desired(config, run=subprocess.run, translations_path=None):
    """Both sources together. Any failure aborts -- never "nothing is open".

    `translations_path` points at THIS repository's translation cache (see
    load_translations); each mirrored repo has its own, or none.

    `config["language"]` (see DEFAULT_LANGUAGE, issues_to_items) decides
    whether that cache is consulted at all. In "de" it is not read AT ALL --
    not even as an empty-cache fallback -- because there is nothing for it to
    do: nothing is translated, so a missing file is not a gap to report on.
    load_config() is the normal way a config gets its `language`, migrating
    or defaulting one in if the file does not name it; a config assembled by
    hand (as plenty of tests here do) that also omits `language` gets the
    same DEFAULT_LANGUAGE, "de".
    """
    ISSUE_LIMIT = 200
    raw_issues = _gh(["issue", "list", "--repo", config["repo"], "--state", "open",
                      "--limit", str(ISSUE_LIMIT), "--json",
                      "number,title,url,labels,body"], run)
    try:
        issues = json.loads(raw_issues)
    except json.JSONDecodeError as error:
        raise GitHubReadFailed("gh returned no JSON: %s" % error)

    if len(issues) == ISSUE_LIMIT:
        raise GitHubReadFailed("Issue list hit the limit of %d; result cannot be trusted "
                             "to be complete and is discarded" % ISSUE_LIMIT)

    raw_file = _gh(["api", "repos/%s/contents/%s" % (config["repo"], config["items_path"])], run)
    try:
        text = base64.b64decode(json.loads(raw_file)["content"]).decode("utf-8")
    except (json.JSONDecodeError, KeyError, ValueError) as error:
        raise GitHubReadFailed("item list not readable: %s" % error)

    language = config.get("language", DEFAULT_LANGUAGE)
    _check_language(language, config.get("repo", "?"))
    translations = load_translations(translations_path) if language != "de" else {}
    desired = issues_to_items(issues, translations, language=language)
    desired.update(toml_to_items(text))
    return desired

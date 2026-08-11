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

from .models import (CLARIFICATION_TAG, DRAFT_TAG, NON_ISSUE_TAGS, PLAIN_PRIORITY_TAGS,
                     PRIORITY_TAGS, PROPOSED_PRIORITY_TAGS, Item, check_tag, issue_key,
                     item_key, marker, sanitise, tag_set)


class GitHubReadFailed(Exception):
    """The desired state could not be read -- the run must abort."""


# Only these labels say anything the mirror mirrors. Any other label on the
# tracker is somebody else's bookkeeping and would mint a junk tag.
PRIORITY_LABELS = ("P0", "P1", "P2", "P3")

# Three suffixes, all at the very END of a title so they annotate the name
# instead of displacing it -- a German draft title runs to ~130 characters and
# must stay readable. They are deliberately distinguishable at a glance:
# what a task IS, what it POINTS AT, and which KIND of thing it points at.
# Never `#12`: a `#` would create a tag in the owner's account.
ISSUE_SUFFIX = " [Issue -> %d]"            # a promoted tracker issue
ISSUE_RELATED_SUFFIX = " [Issue Related -> %d]"    # an item about an issue
DRAFT_RELATED_SUFFIX = " [Draft Related -> %s]"    # a clarification about a draft

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

# issue-descriptions.toml lives beside sync.py, at the root of THIS repo --
# it is tooling for the mirror, not wiki content, so it does not belong in
# the wiki repo being mirrored. github.py sits one package down, hence the
# double .parent.
TRANSLATIONS_PATH = pathlib.Path(__file__).resolve().parent.parent / "issue-descriptions.toml"


def load_translations(path=TRANSLATIONS_PATH):
    """number -> (source_sha256, description), read from issue-descriptions.toml.

    The sync has no LLM and no translation API -- either would break its
    determinism and its zero-dependency rule -- so translation happens out of
    band, by a human, and this file is the cache of that work. A missing file
    is not a read failure: it behaves exactly like a present-but-empty cache,
    and every issue falls back to its German excerpt (see
    _translated_description) rather than aborting the run over a file whose
    only job is a cosmetic one.
    """
    try:
        with open(path, "rb") as handle:
            payload = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    return {entry["number"]: (entry["source_sha256"], entry["description"])
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


# Generous for a slow network, far below the 10-minute stale-lock threshold,
# so a hang always resolves into a logged error before anything else reacts
# to it. Without this, a hung `gh` under pythonw.exe is an invisible
# zombie -- it never completes, never logs, and the stale-lock logic lets
# another run start every 10 minutes, which can hang the same way.
GH_TIMEOUT_SECONDS = 60


def load_config(path):
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def issues_to_items(payload, translations=None):
    """The issue's own name, its own priority label, nothing added.

    The title is passed through exactly as GitHub returns it -- the issues are
    German and stay German. It carries no `#<number> ` prefix either: that was
    this mirror's own invention and it was creating tags in the owner's
    account (see models.sanitise). The number returns as a SUFFIX instead, so
    it annotates the name rather than displacing it.

    The description is an excerpt of the issue body, so the task says what it
    is about without anything being opened -- but a task's description must
    always be English (see UNTRANSLATED_PREFIX / _translated_description),
    while an issue body is German. `translations` is the cache read by
    load_translations(); read_desired() always supplies it, so a description
    reaching TickTick is either a hand-translated cache hit or a visibly
    marked, counted fallback -- never a silent German excerpt. The marker
    comes last, because the first line is what the app shows.
    """
    translations = translations if translations is not None else {}
    items = {}
    for issue in payload:
        key = issue_key(issue["number"])
        labels = [label["name"] for label in issue.get("labels", [])]
        tags = tag_set(label for label in labels if label in PRIORITY_LABELS)
        parts = []
        description, is_untranslated = _translated_description(
            issue["number"], excerpt(issue.get("body")), translations)
        if description:
            parts += [description, ""]
        if issue.get("url"):
            parts.append("Source: %s" % issue["url"])
        parts.append(marker(key))
        title = "%s%s" % (issue["title"], ISSUE_SUFFIX % issue["number"])
        items[key] = Item(key=key, title=title, body="\n".join(parts), tags=tags,
                          untranslated=is_untranslated)
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


def _link_suffix(item_id, raw, tags, is_draft, known):
    """Which of the three suffixes this item earns, and whether it may.

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
        return ISSUE_RELATED_SUFFIX % related

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
        return DRAFT_RELATED_SUFFIX % target_title

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

        # The suffix goes last: an item's own name comes first, and a draft
        # title runs to ~130 characters, so the annotation must not push the
        # name off the visible line. Square brackets cannot be confused with
        # the sync marker -- that one requires a literal `sync:` and a key
        # charset without spaces, and lives in the body (see
        # models.key_from_body and its tests).
        title = raw["title"] + _link_suffix(item_id, raw, tags, is_draft, known)

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
        parts = prose + ([""] if prose else []) + trailer

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


def read_desired(config, run=subprocess.run):
    """Both sources together. Any failure aborts -- never "nothing is open"."""
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

    desired = issues_to_items(issues, load_translations())
    desired.update(toml_to_items(text))
    return desired

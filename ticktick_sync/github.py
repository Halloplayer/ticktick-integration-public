"""Read the desired state through `gh` -- with the login that is already there.

Both sources come from GitHub: the open issues, and the neutral item list in
the same repo. Going through `gh` rather than a local clone is deliberate: a
run then also sees what somebody else just pushed, without anyone calling
`git fetch` here.
"""
import base64
import json
import re
import subprocess
import tomllib

from .models import (ISSUE_ONLY_TAGS, NON_ISSUE_TAGS, Item, check_tag, issue_key,
                     item_key, marker, tag_set)


class GitHubReadFailed(Exception):
    """The desired state could not be read -- the run must abort."""


# Only these labels say anything the mirror mirrors. Any other label on the
# tracker is somebody else's bookkeeping and would mint a junk tag.
PRIORITY_LABELS = ("P0", "P1", "P2", "P3")

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


# Generous for a slow network, far below the 10-minute stale-lock threshold,
# so a hang always resolves into a logged error before anything else reacts
# to it. Without this, a hung `gh` under pythonw.exe is an invisible
# zombie -- it never completes, never logs, and the stale-lock logic lets
# another run start every 10 minutes, which can hang the same way.
GH_TIMEOUT_SECONDS = 60


def load_config(path):
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def issues_to_items(payload):
    """The issue's own name, its own priority label, nothing added.

    The title is passed through exactly as GitHub returns it -- the issues are
    German and stay German. It carries no `#<number> ` prefix either: that was
    this mirror's own invention and it was creating tags in the owner's
    account (see models.sanitise). The number lives in the sync marker and the
    URL in the body, which is where it was always actually needed.

    The description is an excerpt of the issue body, so the task says what it
    is about without anything being opened. The marker comes last, because the
    first line is what the app shows.
    """
    items = {}
    for issue in payload:
        key = issue_key(issue["number"])
        labels = [label["name"] for label in issue.get("labels", [])]
        tags = tag_set(label for label in labels if label in PRIORITY_LABELS)
        parts = []
        description = excerpt(issue.get("body"))
        if description:
            parts += [description, ""]
        if issue.get("url"):
            parts.append("Source: %s" % issue["url"])
        parts.append(marker(key))
        items[key] = Item(key=key, title=issue["title"], body="\n".join(parts), tags=tags)
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
    """`Draft` and the priorities are ISSUE properties; the rest are not.

    An item is an issue draft exactly when it names a `source`. Both
    directions are enforced, because the halves are disjoint: an item without
    a source cannot be a `Draft` or carry a priority, and an item with one
    cannot be a `Task`, `Bug` or `Clarification`.

    A real check rather than a convention: the file is hand-edited in a shared
    repo, and a tag in the wrong half would not break anything visibly -- it
    would just quietly produce a wrong list, which is the kind of error nobody
    goes looking for.
    """
    for tag in sorted(tags):
        if tag in ISSUE_ONLY_TAGS and not is_draft:
            raise GitHubReadFailed(
                "Item '%s' is tagged '%s', but it has no `source`, so it is not an "
                "issue draft. `Draft` and the priorities P0-P3 say something about an "
                "ISSUE; work that is not an issue takes Task, Bug or Clarification."
                % (item_id, check_tag(tag)))
        if tag in NON_ISSUE_TAGS and is_draft:
            raise GitHubReadFailed(
                "Item '%s' is tagged '%s', but it names a `source`, which makes it an "
                "issue draft. Task, Bug and Clarification describe work that is NOT an "
                "issue, so they cannot sit beside `Draft` or a priority. Put the "
                "substance in the description instead."
                % (item_id, check_tag(tag)))


def toml_to_items(text):
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise GitHubReadFailed("open-items.toml is broken: %s" % error)

    _check_shape(payload)

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

        _check_tag_scope(item_id, tags, is_draft=bool(raw.get("source")))

        title = raw["title"]
        related = raw.get("related")
        if related is not None:
            if isinstance(related, bool) or not isinstance(related, int):
                raise GitHubReadFailed(
                    "Item '%s' has `related = %r`; it must be an issue NUMBER."
                    % (item_id, related))
            # Last, and square-bracketed: an item's own name comes first, and
            # a draft title can run to ~130 characters, so our annotation must
            # not push it off the visible line. Never `#12` -- a `#` here
            # would create a tag named `12` in the owner's account. Square
            # brackets cannot be confused with the sync marker: that one
            # requires a literal `sync:` and a key charset without spaces, and
            # it lives in the body (see models.key_from_body and its tests).
            title = "%s [Issue %d Related]" % (title, related)

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

    desired = issues_to_items(issues)
    desired.update(toml_to_items(text))
    return desired

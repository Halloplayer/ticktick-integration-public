"""Read the desired state through `gh` -- with the login that is already there.

Both sources come from GitHub: the open issues, and the neutral item list in
the same repo. Going through `gh` rather than a local clone is deliberate: a
run then also sees what somebody else just pushed, without anyone calling
`git fetch` here.
"""
import base64
import json
import subprocess
import tomllib

from .models import Item, check_tag, issue_key, item_key, marker, tag_set


class GitHubReadFailed(Exception):
    """The desired state could not be read -- the run must abort."""


# Only these labels say anything the mirror mirrors. Any other label on the
# tracker is somebody else's bookkeeping and would mint a junk tag.
PRIORITY_LABELS = ("P0", "P1", "P2", "P3")

# TickTick makes a TAG out of any `#token` it finds in a task's text. The
# mirror's old `#<number> ` title prefix was therefore quietly creating tags
# named `12`, `11`, `14` in the owner's personal account -- and `POST /tag`
# answers 500, so nothing here can delete them again; only the owner can, by
# hand, in the app. The one legitimate way to express a tag is the structured
# `tags` field. So: no `#` in anything the mirror sends.
FORBIDDEN_IN_TEXT = "#"


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
    account (see FORBIDDEN_IN_TEXT). The number lives in the sync marker and
    the URL in the body, which is where it was always actually needed.
    """
    items = {}
    for issue in payload:
        key = issue_key(issue["number"])
        labels = [label["name"] for label in issue.get("labels", [])]
        tags = tag_set(label for label in labels if label in PRIORITY_LABELS)
        body = "%s\n%s" % (marker(key), issue.get("url", ""))
        items[key] = Item(key=key, title=issue["title"], body=body.strip(), tags=tags)
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

        title = raw["title"]
        related = raw.get("related")
        if related is not None:
            if isinstance(related, bool) or not isinstance(related, int):
                raise GitHubReadFailed(
                    "Item '%s' has `related = %r`; it must be an issue NUMBER."
                    % (item_id, related))
            # `(issue 12 related)`, never `(#12 related)` -- a `#` here would
            # create a tag named `12` in the owner's account.
            title = "%s (issue %d related)" % (title, related)

        parts = [marker(key)]
        if raw.get("note"):
            parts.append(raw["note"])
        if raw.get("source"):
            parts.append("Source: %s" % raw["source"])
        if raw.get("owner"):
            parts.append("With: %s" % raw["owner"])
        body = "\n".join(parts)

        for what, text in (("title", title), ("body", body)):
            if FORBIDDEN_IN_TEXT in text:
                raise GitHubReadFailed(
                    "Item '%s' has a '%s' in its %s. TickTick turns any such "
                    "token into a TAG in the owner's account, and its API "
                    "cannot delete one again -- write 'issue 12' instead of "
                    "'%s12'. Tags belong in the `tags` field."
                    % (item_id, FORBIDDEN_IN_TEXT, what, FORBIDDEN_IN_TEXT))

        items[key] = Item(key=key, title=title, body=body, tags=tags)
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
                      "--limit", str(ISSUE_LIMIT), "--json", "number,title,url,labels"], run)
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

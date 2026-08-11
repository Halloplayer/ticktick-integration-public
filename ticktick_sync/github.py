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

from .models import Item, issue_key, item_key, marker, priority_of


class GitHubReadFailed(Exception):
    """The desired state could not be read -- the run must abort."""


def load_config(path):
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def issues_to_items(payload):
    items = {}
    for issue in payload:
        key = issue_key(issue["number"])
        labels = [label["name"] for label in issue.get("labels", [])]
        priority = max([priority_of(label) for label in labels] or [0])
        body = "%s\n%s" % (marker(key), issue.get("url", ""))
        items[key] = Item(key=key, title="#%d %s" % (issue["number"], issue["title"]),
                          body=body.strip(), priority=priority)
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
        try:
            key = item_key(raw["id"])
        except ValueError as error:
            raise GitHubReadFailed(str(error)) from error
        parts = [marker(key)]
        if raw.get("note"):
            parts.append(raw["note"])
        if raw.get("source"):
            parts.append("Source: %s" % raw["source"])
        if raw.get("owner"):
            parts.append("With: %s" % raw["owner"])
        items[key] = Item(key=key, title=raw["title"], body="\n".join(parts),
                          priority=priority_of(raw.get("priority")))
    return items


def _gh(args, run):
    try:
        done = run(["gh"] + args, capture_output=True, text=True, encoding="utf-8")
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

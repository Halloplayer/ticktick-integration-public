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


def toml_to_items(text):
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise GitHubReadFailed("open-items.toml is broken: %s" % error)

    items = {}
    for raw in payload.get("items", []):
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

"""Setting a repository up -- the one path that may create a TickTick list.

Everything here runs once per repository, driven conversationally by the skill
(`skills/ticktick-sync/SKILL.md`). It is kept apart from the sync engine on
purpose: the sync must NEVER create a list. A mirror that quietly creates its
own list turns "there is no list named X" -- a configuration mistake, loudly
recoverable -- into a second, silently empty list in somebody's personal task
manager, with the real one still sitting untouched beside it. `resolve_list`
therefore keeps refusing, unchanged, and nothing in `sync_core.py` or `sync.py`
so much as names `create_list`.

Creating a list through the Open API is UNVERIFIED. `POST /open/v1/tag` answers
500 on this API, and the project endpoint may well behave the same way; it is
deliberately never probed speculatively, because a probe that half-succeeded
would leave a stray list in a real account which the API cannot delete again.
So `ensure_list` attempts it for real, when a human has asked for it, and any
failure becomes an instruction the user can carry out by hand.
"""
import pathlib

import repos
from ticktick import TickTickError


class SetupFailed(Exception):
    """Setup could not finish -- always with a way forward in the message."""


def existing_lists(client):
    """[(id, name)] of the account's lists, for the user to pick from."""
    return client.list_projects()


def ensure_list(client, name):
    """(list_id, created) for `name`, creating the list only if it is absent.

    Call this ONLY after the user has explicitly confirmed the creation: it is
    a setup-only capability, and the account it writes into is a real person's.
    """
    for list_id, list_name in client.list_projects():
        if list_name == name:
            return list_id, False

    try:
        list_id = client.create_list(name)
    except TickTickError as error:
        raise SetupFailed(_by_hand(name, error))
    if not list_id:
        # This API is known to answer 200 with a plausible object while storing
        # nothing (a deleted task id does exactly that). A reply without an id
        # is not evidence of a list, so it is not treated as one.
        raise SetupFailed(_by_hand(name, "the API answered without a list id"))
    return list_id, True


def _by_hand(name, reason):
    return ("could not create the TickTick list %r through the API (%s). Create it "
            "by hand in the TickTick app -- named exactly %r -- and run setup "
            "again; it resolves an existing list by name." % (name, reason, name))


def write_repo_config(data_dir, slug, repo, list_id, list_name,
                      items_path="open-items.toml"):
    """Write `repos/<slug>/config.toml` and return its path.

    Keyed on the id with the name as a guard on it, exactly as the single-repo
    config was: mirroring machine tasks into the wrong list of somebody's
    personal task manager must fail loudly, so a mismatch between the two is
    an error rather than a fallback (see `ticktick.resolve_list`).
    """
    directory = repos.repo_dir(data_dir, slug)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.toml"
    path.write_text(
        "# What gets mirrored. Nothing here is secret.\n"
        "repo = %s\n"
        "items_path = %s\n"
        "\n"
        "# Keyed on the id, not the name: a list name may carry an emoji, and\n"
        "# exact-string matching on that across Windows encodings is a needless\n"
        "# way to fail. The name is only a label checked against the id, so a\n"
        "# wrong id fails loudly instead of silently mirroring into some other\n"
        "# list.\n"
        "list_id = %s\n"
        "list_name = %s\n" % (_toml(repo), _toml(items_path), _toml(list_id),
                              _toml(list_name)),
        encoding="utf-8")
    return str(path)


def _toml(value):
    """A TOML basic string. Names arrive from a person and an API, so the
    quoting is done properly rather than by concatenation."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % escaped


# The ONLY file this project writes into somebody else's repository, and it is
# neutral by construction: a fixed constraint of this project is that a
# mirrored repo must not learn the mirror exists. No "TickTick", no "sync", no
# "mirror" -- it reads as what it is, a list of that repo's own open work that
# has no other machine-readable home.
OPEN_ITEMS_TEMPLATE = """\
# Open work in this repository that is not a tracker issue.
#
# A plain, diffable list of what is on the table: items still to do, things
# that are broken, drafts awaiting a decision. Each item has a stable `id`, a
# `title`, and an English `description` written to be understood cold.
#
# version = 1 is the shape readers expect. `items = []` means nothing is open
# -- say it explicitly rather than deleting the table.

version = 1

items = []
"""


def open_items_template():
    return OPEN_ITEMS_TEMPLATE


def write_open_items(repo_path, items_path="open-items.toml"):
    """Create the item list in the target repo if it is not already there.

    Returns (path, created). Never overwrites: the file is the user's, and
    everything in it was written by hand.
    """
    path = pathlib.Path(repo_path) / items_path
    if path.exists():
        return str(path), False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(OPEN_ITEMS_TEMPLATE, encoding="utf-8")
    return str(path), True

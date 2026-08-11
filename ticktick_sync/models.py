"""The mirror's data shapes -- no I/O of any kind.

The key is the backbone: it identifies an entry across runs and is stored in
the TickTick task's own description. That is what makes the mapping
recoverable when the local cache is gone.
"""
import re
from dataclasses import dataclass

# Permitted characters in a key: alphanumeric, hyphen, dot, underscore.
# This is the authoritative source; MARKER_RE is derived from it to ensure
# they never drift apart. The round-trip property marker() -> key_from_body()
# depends on every key being extractable by MARKER_RE.
KEY_CHARSET = r"A-Za-z0-9._\-"
MARKER_RE = re.compile(r"\[sync:([" + KEY_CHARSET + r"]+)\]")

# TickTick priorities: 0 none, 1 low, 3 medium, 5 high.
PRIORITIES = {"P0": 5, "P1": 5, "P2": 3, "P3": 1}


@dataclass(frozen=True)
class Item:
    """A desired entry, derived from either source."""
    key: str
    title: str
    body: str
    priority: int = 0


@dataclass(frozen=True)
class Task:
    """A task as it currently stands in TickTick."""
    key: str
    task_id: str
    title: str
    body: str
    priority: int = 0
    completed: bool = False


@dataclass(frozen=True)
class Create:
    item: Item


@dataclass(frozen=True)
class Update:
    task_id: str
    item: Item


@dataclass(frozen=True)
class Reopen:
    """Bring back a task we completed earlier, whose source went open again.

    Measured in Task 1: completed tasks are INVISIBLE to
    `GET /project/{id}/data`. So a task ticked off by hand simply vanishes from
    the current state, and without this action the mirror would create a second
    task instead of restoring the one that is already there.
    """
    task_id: str
    item: Item


@dataclass(frozen=True)
class Complete:
    task_id: str
    key: str


def issue_key(number):
    return "gh-%d" % number


def item_key(item_id):
    """Create a TickTick item key from its id, validating the character set.

    Raises ValueError if the id contains any character not in KEY_CHARSET.
    A bad character would break the marker round-trip, making recovered keys
    unrecoverable on the next sync run. Raise rather than sanitize: two
    different ids could slug to the same key and silently overwrite each
    other's tasks, which is worse than the bug being fixed.
    """
    # Check that all characters in item_id are in the permitted set.
    # Use fullmatch to avoid Python's $ anchor exception for trailing newline.
    if not re.fullmatch("[" + KEY_CHARSET + "]+", item_id):
        raise ValueError(
            f"Item id '{item_id}' contains characters not in permitted set "
            f"(allowed: alphanumeric, hyphen, dot, underscore)"
        )
    return "oi-%s" % item_id


def priority_of(label):
    """An unknown label is 0, not an error. A new label on the tracker must not
    halt a background run."""
    return PRIORITIES.get(label or "", 0)


def marker(key):
    return "[sync:%s]" % key


def key_from_body(body):
    """Recover the key from a task description.

    This is how a deleted state.json is rebuilt: the truth about the mapping
    lives in TickTick itself, the cache is merely faster.
    """
    found = MARKER_RE.search(body or "")
    return found.group(1) if found else None

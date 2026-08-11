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

# The closed vocabulary. TickTick priorities are not used at all; a tag says
# everything the mirror needs to say, and the owner colours these eight by hand
# in the app. The order here is the display order.
#
# Closed on purpose: `POST /tag` answers 500, so the Open API can neither
# create, rename nor delete a tag. A typo would therefore leave permanent
# litter in the owner's personal account that only they can clear. Better to
# fail the run.
PERMITTED_TAGS = ("P0", "P1", "P2", "P3", "Draft", "Task", "Bug", "Clarification")

_CANONICAL = {tag.lower(): tag for tag in PERMITTED_TAGS}
_ORDER = {tag.lower(): index for index, tag in enumerate(PERMITTED_TAGS)}


def check_tag(tag):
    """Return the canonical spelling of a permitted tag, or raise.

    Loud on the way IN (reading the source file), never on the way OUT --
    see display_tags().
    """
    canonical = _CANONICAL.get((tag or "").strip().lower())
    if canonical is None:
        raise ValueError(
            "Tag '%s' is not one of the permitted tags (%s). The TickTick Open "
            "API cannot delete a tag it creates, so a typo would leave litter "
            "in the account that only a human can clear."
            % (tag, ", ".join(PERMITTED_TAGS)))
    return canonical


def tag_set(tags):
    """Normalise tags to a frozenset of lowercased names.

    This is THE anti-churn measure. TickTick stores a task's tags as their
    lowercase names -- send `["P1"]` on create and the account holds `["p1"]`
    -- while an update echoes back whatever case it was sent, in whatever
    order. Comparing the raw lists would therefore find a difference on every
    run and rewrite every task every five minutes, forever. A frozenset of
    lowercased names is equal exactly when the tags are the same tags, so the
    ordinary dataclass comparison in reconcile() stays quiet.
    """
    return frozenset(part for part in ((tag or "").strip().lower() for tag in tags or ()) if part)


def display_tags(tags):
    """Canonical spellings in the permitted order, for sending.

    Deliberately forgiving: these values come back from the account, where a
    human may have added a tag of their own, and an unattended run must not die
    of it. Unknown tags keep their normalised form and sort last.
    """
    return [_CANONICAL.get(tag, tag)
            for tag in sorted(tags, key=lambda tag: (_ORDER.get(tag, len(_ORDER)), tag))]


@dataclass(frozen=True)
class Item:
    """A desired entry, derived from either source."""
    key: str
    title: str
    body: str
    tags: frozenset = frozenset()


@dataclass(frozen=True)
class Task:
    """A task as it currently stands in TickTick."""
    key: str
    task_id: str
    title: str
    body: str
    tags: frozenset = frozenset()
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


def marker(key):
    return "[sync:%s]" % key


def key_from_body(body):
    """Recover the key from a task description.

    This is how a deleted state.json is rebuilt: the truth about the mapping
    lives in TickTick itself, the cache is merely faster.
    """
    found = MARKER_RE.search(body or "")
    return found.group(1) if found else None

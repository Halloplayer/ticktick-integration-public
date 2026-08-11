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
# everything the mirror needs to say, and the owner colours these twelve by
# hand in the app. The order here is the display order.
#
# TWO priority namespaces, deliberately. A plain `P2` is an AGREED priority on
# a promoted tracker issue. An underscored `_P2` is a PROPOSED one, taken from
# the frontmatter of a draft that has not been promoted yet. Both are worth
# seeing -- hiding the proposal throws away real information -- but showing a
# proposal as plain `P2` would claim an agreement nobody has made. The
# underscore keeps them apart, so a plain priority always means "promoted".
#
# Closed on purpose: `POST /tag` answers 500, so the Open API can neither
# create, rename nor delete a tag. A typo would therefore leave permanent
# litter in the owner's personal account that only they can clear. Better to
# fail the run.
PERMITTED_TAGS = ("P0", "P1", "P2", "P3",
                  "_P0", "_P1", "_P2", "_P3",
                  "Draft", "Task", "Bug", "Clarification")

_CANONICAL = {tag.lower(): tag for tag in PERMITTED_TAGS}
_ORDER = {tag.lower(): index for index, tag in enumerate(PERMITTED_TAGS)}

# Three disjoint cases, decided by where an entry came from:
#
#   1. a GitHub issue          -- a plain priority from its tracker label
#   2. an item WITH a `source` -- unpromoted draft: `Draft` (+ one `_P?`)
#   3. an item without one     -- exactly one of Task, Bug, Clarification
#
# So a PLAIN priority never appears in the item file at all: that file holds
# only non-issues and unpromoted drafts, and neither has an agreed priority.
# github.py enforces all of this when reading the item file.
PLAIN_PRIORITY_TAGS = frozenset({"p0", "p1", "p2", "p3"})
PROPOSED_PRIORITY_TAGS = frozenset({"_p0", "_p1", "_p2", "_p3"})
PRIORITY_TAGS = PLAIN_PRIORITY_TAGS | PROPOSED_PRIORITY_TAGS
DRAFT_TAG = "draft"
CLARIFICATION_TAG = "clarification"
NON_ISSUE_TAGS = frozenset({"task", "bug", CLARIFICATION_TAG})


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


_ISSUE_REF = re.compile(r"#(\d+)")


def sanitise(text):
    """Strip the one character that must never reach TickTick: `#`.

    TickTick makes a TAG out of any `#token` it finds in a task's text, and
    `POST /tag` answers 500 -- so nothing here can delete what that creates.
    The mirror's old `#12 ` title prefix had been quietly minting tags named
    `12`, `11` and `14` in the owner's personal account, which only they could
    clear, by hand, in the app.

    A cross-reference is rewritten (`#12` -> `issue 12`) because it carries
    meaning worth keeping; anything else is dropped, and the whitespace the
    removal leaves behind is collapsed so a markdown heading does not arrive
    indented. Line structure survives -- bodies are built line by line.

    The replacement inserts a LEADING space. Without one, a reference attached
    to the word before it collided with that word: `acme/widgets#10`
    came out as `acme/widgetsissue 10`. That repo-qualified form is the style
    these issue bodies actually use, so it was the common case, not an edge
    one. The added space costs nothing where a space was already there -- the
    collapse below removes the double again.

    This is deliberately ONE function, called from Item.__post_init__ rather
    than from each mapper: a chokepoint that has to be remembered is not a
    chokepoint, and it must also protect sources nobody has written yet.
    """
    if not text:
        return text
    cleaned = _ISSUE_REF.sub(r" issue \1", text).replace("#", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.split("\n")]
    return "\n".join(lines).strip()


@dataclass(frozen=True)
class Item:
    """A desired entry, derived from either source.

    Every string that leaves for TickTick passes through sanitise() here, on
    the way in -- see that function for why.
    """
    key: str
    title: str
    body: str
    tags: frozenset = frozenset()
    # True when this Item's body fell back to an untranslated German excerpt
    # -- see ticktick_sync.github._translated_description(). Never set by
    # anything other than the GitHub-issue mapper: open-items.toml entries
    # are already hand-written in English. Carried on the Item itself (rather
    # than as a side channel) so sync.py's summary line can count it straight
    # off `desired`, without github.py having to thread a count back out
    # through a second return value.
    untranslated: bool = False

    def __post_init__(self):
        object.__setattr__(self, "title", sanitise(self.title))
        object.__setattr__(self, "body", sanitise(self.body))


@dataclass(frozen=True)
class Task:
    """A task as it currently stands in TickTick.

    `priority` is carried here even though the mirror uses TickTick's own
    priorities for nothing: an Item has no such field, so this one exists
    solely to NOTICE a flag that is still set. Tasks made before tags existed
    kept theirs, and a value that cannot be seen cannot be cleared.
    """
    key: str
    task_id: str
    title: str
    body: str
    tags: frozenset = frozenset()
    completed: bool = False
    priority: int = 0


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

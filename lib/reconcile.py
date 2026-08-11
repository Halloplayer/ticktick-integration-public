"""Turn desired plus current into the steps between them -- pure, no network.

One rule: the list shows what the repo says. Tick a task off by hand while the
source is still open and you get it back.
"""
from models import Complete, Create, Reopen, Update


def reconcile(desired, current, known_ids=None):
    """The steps that take `current` to `desired`.

    `current` holds OPEN tasks only -- Task 1 measured that TickTick's
    project-data endpoint hides completed ones. So a task the user ticked off
    is not "present and completed", it is simply absent. `known_ids` (the
    key->id map from state.json) is how we tell "never existed" from "existed
    and was completed", and it is the difference between restoring a task and
    silently making a second one.
    """
    known_ids = known_ids or {}
    creates, updates, reopens, completes = [], [], [], []

    for key, item in sorted(desired.items()):
        task = current.get(key)
        if task is None:
            if key in known_ids:
                reopens.append(Reopen(known_ids[key], item))
            else:
                creates.append(Create(item))
        elif _differs(task, item):
            updates.append(Update(task.task_id, item))

    for key, task in sorted(current.items()):
        if key not in desired and not task.completed:
            completes.append(Complete(task.task_id, key))

    return creates + updates + reopens + completes


def _differs(task, item):
    """`completed` counts as a difference -- that IS the re-opening.

    The tag comparison is case- and order-insensitive because both sides are
    already normalised to a frozenset of lowercased names (models.tag_set).
    Anything less would differ on every run -- TickTick stores tags lowercase
    on create but echoes the sent case on update -- and rewrite all fifteen
    tasks every five minutes, forever.

    A leftover TickTick priority counts as a difference too. The mirror
    asserts that a mirrored task has none, so a flag still set is drift from
    what the repo says. Without this the repair could not fire at all: those
    tasks match on every other field, so no action would be produced, no
    payload would be sent, and the explicit `priority: 0` would never reach
    them. Clearing one settles it -- the next read sees zero and the
    comparison goes quiet again, so this heals once rather than churning.
    """
    return (task.title != item.title
            or task.body != item.body
            or task.tags != item.tags
            or task.priority != 0
            or task.completed)


class CollapseRefused(Exception):
    """Desired fell from non-empty to empty -- most likely a read failure."""


def guard_collapse(desired, last_count):
    """Empty is allowed. Collapsed is not.

    Everything really can be closed at once, and then the empty set is right.
    But a fall from non-empty to empty looks exactly like a failed read, and
    the consequences are not equivalent: one costs a run, the other clears the
    list. So when in doubt, do nothing.
    """
    if not desired and last_count > 0:
        raise CollapseRefused(
            "desired fell from %d to 0 -- that looks like a read failure, not "
            "finished work. NOTHING was completed. If everything really is "
            "closed, delete state.json and run again." % last_count)

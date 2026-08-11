"""Turn desired plus current into the steps between them -- pure, no network.

One rule: the list shows what the repo says. Tick a task off by hand while the
source is still open and you get it back.
"""
from .models import Complete, Create, Reopen, Update


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
    """`completed` counts as a difference -- that IS the re-opening."""
    return (task.title != item.title
            or task.body != item.body
            or task.priority != item.priority
            or task.completed)

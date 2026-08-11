"""The wiring: guard, resolve, reconcile, apply, remember."""
from .models import Complete, Create, Reopen, Update
from .reconcile import guard_collapse, reconcile
from .state import load_state, save_state
from .ticktick import TickTickError


def run_sync(config, client, desired, state_path):
    state = load_state(state_path)
    guard_collapse(desired, state.get("last_count", 0))
    ids = dict(state.get("ids", {}))
    # Safe to record from here on: guard_collapse already vouched for this
    # count, and every write below is persisted immediately (see the calls
    # to save_state after each create), so a crash mid-run never leaves a
    # last_count that outruns what has actually been saved.
    last_count = len(desired)

    project_id = client.resolve_list(config["list_name"], config.get("list_id"))
    current = client.read_tasks(project_id)
    # Anything visible right now re-confirms its id, so the map self-heals.
    ids.update({key: task.task_id for key, task in current.items()})
    actions = reconcile(desired, current, known_ids=ids)

    counts = {"created": 0, "updated": 0, "reopened": 0, "completed": 0}
    for action in actions:
        if isinstance(action, Create):
            new_id = client.create(project_id, action.item)
            if new_id:
                # create() returns the only route back to this task once it is
                # completed (completed tasks are invisible to the read
                # endpoint), and nothing here retries -- so the id is written
                # to disk right away, not batched up for the end of the run.
                ids[action.item.key] = new_id
                save_state(state_path, {"last_count": last_count, "ids": ids})
            counts["created"] += 1
        elif isinstance(action, Update):
            client.update(project_id, action.task_id, action.item)
            counts["updated"] += 1
        elif isinstance(action, Reopen):
            # A 200 here proves nothing. Measured 2026-08-11 against the live
            # API (docs/api-notes.md section 7): POST /task/{id} on a DELETED id
            # answers 200 with a complete, plausible-looking task object and
            # stores none of it. The status code therefore cannot tell a real
            # re-open from a write into the void, and catching TickTickError
            # alone -- as this branch originally did -- would report reopened=1
            # on every run forever while the item never came back and the dead
            # id was never evicted. Ask the list instead of believing the reply.
            try:
                client.update(project_id, action.task_id, action.item)
            except TickTickError:
                pass  # conclusive by itself, but the check below decides anyway
            back = client.read_tasks(project_id).get(action.item.key)
            if back is not None:
                # It really is there. Point the cache at whatever id the list
                # actually shows, so a stale entry heals instead of lingering.
                ids[action.item.key] = back.task_id
                counts["reopened"] += 1
            else:
                # The remembered task is gone for good (deleted, not merely
                # completed). Falling back to a fresh one keeps the promise that
                # the list shows what the repo says, and writing the new id over
                # the old one is what finally evicts the dead one.
                new_id = client.create(project_id, action.item)
                if new_id:
                    ids[action.item.key] = new_id
                    save_state(state_path, {"last_count": last_count, "ids": ids})
                counts["created"] += 1
        elif isinstance(action, Complete):
            client.complete(project_id, action.task_id)
            counts["completed"] += 1

    state["last_count"] = last_count
    state["ids"] = ids
    save_state(state_path, state)
    return counts

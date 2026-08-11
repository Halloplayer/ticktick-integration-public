"""The local cache: key -> task id, and the previous item count.

It is fast, not true. The truth about the mapping lives in TickTick itself (in
the marker); this cache only saves recomputing it, and it is written whole or
not at all.

But it is not merely a cache. `last_count` ARMS the collapse guard, the one
thing standing between a failed read and the user's entire list being ticked
off -- and `guard_collapse` refuses only a fall from non-zero. Reporting a
comfortable zero when the file could not be read is therefore not shrugging off
a broken cache; it switches the safeguard off, in precisely the situation that
suggests something is already wrong. Hence the distinction below: no file is a
fresh start, an unreadable file is a refusal.
"""
import json
import os

EMPTY = {"last_count": 0, "ids": {}}


class StateUnreadable(Exception):
    """state.json is there but could not be read or parsed.

    Distinct from "no state.json at all", which is a legitimate first run.
    """


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        # Nothing has ever run here. The only honest zero.
        return dict(EMPTY)
    except OSError as error:
        # It exists and would not open: a sharing violation against the
        # os.replace below, a permission problem, a failing disk.
        raise StateUnreadable(
            "%s exists but could not be read (%s). Refusing to run -- "
            "pretending the count is zero would disarm the collapse guard and "
            "could complete the whole list." % (path, error)) from error
    except ValueError as error:
        raise StateUnreadable(
            "%s is not valid JSON (%s). Refusing to run rather than proceed "
            "with the collapse guard disarmed. If the cache is genuinely lost, "
            "delete the file -- a missing one is a legitimate fresh start."
            % (path, error)) from error

    if not isinstance(payload, dict):
        raise StateUnreadable(
            "%s holds a %s, not an object. Refusing to run rather than proceed "
            "with the collapse guard disarmed." % (path, type(payload).__name__))

    merged = dict(EMPTY)
    merged.update(payload)
    return merged


def save_state(path, payload):
    temp = path + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.remove(temp)
        raise

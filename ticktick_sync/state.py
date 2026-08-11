"""The local cache: key -> task id, and the previous item count.

It is fast, not true. The truth about the mapping lives in TickTick itself
(in the marker); this cache only saves recomputing it. So a broken cache must
never halt a run -- but, like every file here, it is written whole or not at
all.
"""
import json
import os

EMPTY = {"last_count": 0, "ids": {}}


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return dict(EMPTY)
    merged = dict(EMPTY)
    merged.update(payload if isinstance(payload, dict) else {})
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

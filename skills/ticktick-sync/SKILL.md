---
name: ticktick-sync
description: Mirrors the open work of globex/toolkit (open GitHub issues plus the neutral item list open-items.toml) into the TickTick list "globex-toolkit". One-way, strict mirror -- the repo always wins. Use this skill when the user says "ticktick sync", "update my list", "sync my ticktick", "open items to ticktick", or when issues or the item list changed during a session and the state on their phone should be current.
---

# TickTick mirror

One call, one reconcile. This skill runs nothing the background job would not
also run -- that is exactly the point.

## Run

The path comes from `${CLAUDE_PLUGIN_ROOT}`, not from a working directory: the
skill runs from the plugin cache, so no clone needs to exist anywhere.

```bash
PYTHONIOENCODING=utf-8 python "${CLAUDE_PLUGIN_ROOT}/sync.py"
```

## Report the result

The output is one line: `ok desired=N created=A updated=U completed=C`.
Report it in plain language -- what is new, what changed, what disappeared.

## When it fails

- **`desired fell from N to 0`** -- the read-failure guard fired. Nothing was
  completed. Check first whether everything really is closed; only then delete
  `state.json` and run again.
- **`there is no TickTick list named ...`** -- the list must be created once by
  hand in TickTick. The mirror never creates one.
- **`gh ... failed`** -- check the GitHub login with `gh auth status`.
- **`-> 401`** -- the TickTick token expired; regenerate it under Settings →
  Account → API Token and put it in `%LOCALAPPDATA%\ticktick-sync\.env`.
- **`no .env in ...`** -- the data directory is missing. It deliberately does
  NOT live in the plugin folder, because a plugin update replaces that.

Never work around an error by switching off the guard.

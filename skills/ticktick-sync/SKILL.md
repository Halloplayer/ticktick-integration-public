---
name: ticktick-sync
description: Mirrors the open work of globex/toolkit (open GitHub issues plus the neutral item list open-items.toml) into the TickTick list "🛡Work" (list id 6f1e2d3c4b5a69788796a5b4), using tags rather than TickTick priorities. One-way, strict mirror -- the repo always wins. Use this skill when the user says "ticktick sync", "update my list", "sync my ticktick", "open items to ticktick", or when issues or the item list changed during a session and the state on their phone should be current.
---

# TickTick mirror

One call, one reconcile. This skill runs nothing the background job would not
also run -- that is exactly the point.

## Run

Do NOT run `sync.py` from `${CLAUDE_PLUGIN_ROOT}` directly. That path is bound
once, when this session loaded the plugin -- after an in-session
`claude plugin update` it still points at the OLD version, silently. Run the
stable launcher instead: it resolves the newest cached plugin version at run
time, every time, so it cannot go stale mid-session. It is the same launcher
the 5-minute background task uses (see `tools/install_task.ps1`).

```bash
PYTHONIOENCODING=utf-8 powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$LOCALAPPDATA/ticktick-sync/run.ps1"
```

Called with no arguments (unlike the background task, which passes
`--quiet`), the launcher runs `python.exe` rather than `pythonw.exe`, so its
output is visible here.

## Report the result

The output is one line: `ok desired=N created=A updated=U reopened=R completed=C`.
Report it in plain language -- what is new, what changed, what disappeared.

## When it fails

- **`desired fell from N to 0`** -- the read-failure guard fired. Nothing was
  completed. Check first whether everything really is closed; only then delete
  `%LOCALAPPDATA%\ticktick-sync\state.json` and run again.
- **`there is no TickTick list named ...`** -- the list must be created once by
  hand in TickTick. The mirror never creates one.
- **`gh ... failed`** -- check the GitHub login with `gh auth status`.
- **`-> 401`** -- the TickTick token expired; regenerate it under Settings →
  Account → API Token and put it in `%LOCALAPPDATA%\ticktick-sync\.env` as
  `TICKTICK_API_KEY=<token>` (also accepts `TICKTICK_TOKEN=`).
- **`no .env in ...`** -- the data directory is missing. Create
  `%LOCALAPPDATA%\ticktick-sync` and populate `.env` with `TICKTICK_API_KEY=<token>`
  (also accepts `TICKTICK_TOKEN=`). It deliberately does NOT live in the plugin
  folder, because a plugin update replaces that.
- **Transient errors** (timeout, connection failure, 403) -- the mirror is
  idempotent; one failure is safe to ignore and the next run reconciles from
  scratch. A repeating error means the credential or connectivity needs attention.

Never work around an error by switching off the guard.

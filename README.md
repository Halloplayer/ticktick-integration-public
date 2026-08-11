# ticktick-sync

Mirrors the open work of a GitHub repo (open issues plus a neutral item list,
`open-items.toml`) into a TickTick list. One-way and strict: the repo is
always right, and TickTick is brought to match it, never the other way round.

## One-time setup

1. Put your TickTick API token in `%LOCALAPPDATA%\ticktick-sync\.env` as:
   ```
   TICKTICK_API_KEY=<token>
   ```
   (`TICKTICK_TOKEN=` also works, if that name is already in use elsewhere.)
2. The target TickTick list must already exist -- create it by hand once in
   TickTick. The mirror never creates a list itself, only tasks inside one.
3. Install the background job:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Users\you\workspace\ticktick-sync\tools\install_task.ps1
   ```
   This registers a Windows Scheduled Task named `TickTickSync` that runs
   `sync.py` every 5 minutes via `pythonw.exe` -- no console window, on
   battery too, and it catches up a run that was missed while the machine was
   asleep.

## Running it by hand

```powershell
PYTHONIOENCODING=utf-8 python sync.py
```

The output is one line: `ok desired=N created=A updated=U reopened=R completed=C`.

## Reading sync.log

Every run -- scheduled or by hand -- appends one line to
`%LOCALAPPDATA%\ticktick-sync\sync.log`, timestamped. A healthy line starts
with `ok`; a failed run starts with `ERROR` and names the exception. Tail it
to see the most recent runs:

```powershell
Get-Content "$env:LOCALAPPDATA\ticktick-sync\sync.log" -Tail 10
```

Under `pythonw.exe` there is no console at all, so this log is the only place
a problem becomes visible -- check it if TickTick ever looks stale.

## When the collapse guard fires

If `sync.log` shows an error like:

```
ERROR CollapseRefused: desired fell from N to 0 -- that looks like a read
failure, not finished work. NOTHING was completed. If everything really is
closed, delete state.json and run again.
```

nothing was changed in TickTick -- the guard refuses to empty a non-empty
list on what looks like a read failure rather than real completions. Follow
the message's own instruction: if everything really is closed, delete
`%LOCALAPPDATA%\ticktick-sync\state.json` and run again.

The guard only catches a fall to **zero**, which is why two other refusals
exist upstream of it. Between them they cover the partial collapse it cannot
see:

- **`GitHubReadFailed: open-items.toml has no ...`** -- the item list parsed
  but is not shaped like an item list (a `[[item]]` typo, a truncated file, an
  unknown `version`). Most of the mirrored work comes from that one file, so a
  file that yields nothing would tick off everything it failed to mention while
  the guard waved it through. To say that nothing is open, write `items = []`.
- **`StateUnreadable: ... exists but could not be read`** -- `state.json` is
  there but unreadable. Reporting the usual zero would disarm the collapse
  guard for that run. A **missing** `state.json` remains a legitimate fresh
  start; only an unreadable one refuses.

## Only one run at a time

The scheduled task cannot overlap itself, but running the skill by hand starts
an independent process that can land mid-tick -- and two runs that both see an
item as missing both create it. Because tasks are matched by the marker in
their description, only one of the twins is ever seen again; the other stays in
the list forever, never updated and never completed.

A run therefore takes `%LOCALAPPDATA%\ticktick-sync\sync.lock` first. A run
that finds it held logs

```
skipped: another run holds the lock (...). The next tick will reconcile.
```

and exits successfully. Nothing is lost: the next tick, five minutes later,
reconciles everything. A lock left behind by a killed process is treated as
abandoned after ten minutes and taken over, which is also logged (`stale`).

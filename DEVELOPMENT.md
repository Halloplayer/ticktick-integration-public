# Developing the ticktick-sync plugin

There are two ways to relate to this plugin — **do not confuse them**:

- **Consume** it (run the sync): you do nothing special. Claude Code fetches the
  newest pushed version into `~/.claude/plugins/cache/` and the skill and the
  background job both run from there.
- **Develop** it (change it): follow this file. You work in a **workspace
  checkout**, so your edits are live and committable.

> **Never edit `~/.claude/plugins/cache/ticktick-sync/`.** The cache is
> version-scoped and gets **clobbered** on the next auto-update or re-install.
> It is a consumer artifact, not a workspace.

## The layout

```
.claude-plugin/       plugin.json (the manifest) + marketplace.json
lib/                  the engine — shared modules, flat, no package
skills/ticktick-sync/
  SKILL.md            the manual trigger
  scripts/            sync.py (entry point), install_task.ps1, probe.py
  tests/              the suite + recorded API fixtures
docs/knowledge/       findings worth keeping (KB-*)
config.toml           which repo, which list
issue-descriptions.toml  hand-written English for German issue text
```

`lib/` is on `sys.path` at run time rather than pip-installed — the plugin runs
straight out of the cache, where nothing is ever installed. `scripts/sync.py`
does that insert itself; the tests do the same from `tests/`.

## Running it

```powershell
$env:PYTHONIOENCODING="utf-8"; python skills\ticktick-sync\scripts\sync.py
```

Against the working copy this runs the code you just edited. Note that the
**skill** deliberately does *not* do this — it goes through the stable launcher
so that a plugin update mid-session cannot leave it on a stale version. See
`SKILL.md`.

## Tests

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s skills/ticktick-sync/tests -p "test_*.py"
```

Standard library only -- `unittest`, never `pytest`. Fully offline, well under a
second. Both external edges (GitHub via `gh`, TickTick via HTTP) run against
recorded fixtures in `skills/ticktick-sync/tests/fixtures/`.

## The background job

`skills/ticktick-sync/scripts/install_task.ps1` registers the `TickTickSync`
scheduled task and writes `%LOCALAPPDATA%\ticktick-sync\launcher.pyw`.

Two things about that launcher are load-bearing:

- **It lives in the data directory, not the plugin.** It resolves the newest
  cached plugin version at *run* time. Pointing the task straight at a cached
  version folder would break on the next update, and the mirror would go quietly
  stale while the list kept looking plausible.
- **`pythonw.exe`, never a `powershell.exe` wrapper.** `powershell.exe`
  allocates its console *before* `-WindowStyle Hidden` takes effect, so a
  wrapper flashes a black window every five minutes. `pythonw.exe` allocates no
  console at all.

The launcher targets `skills/ticktick-sync/scripts/sync.py` under the resolved
version directory and raises `SystemExit`, naming the path, if it is not there --
loudly, on purpose: this runs under `pythonw.exe` with no console and before
`sync.py` has set up its own logging, so a silent failure on a path that moved
would kill the 5-minute job with nothing in `sync.log` to show why. If the entry
point ever moves again, update this generated path (and its regression test in
`test_install_task.py`) together with the move -- do not add a fallback that
probes multiple locations; that hides exactly the kind of break this guards
against.

After changing `install_task.ps1`, re-run it to re-deploy the launcher:

```powershell
powershell -ExecutionPolicy Bypass -File .\skills\ticktick-sync\scripts\install_task.ps1
```

## Data lives apart from code

Everything mutable is under `%LOCALAPPDATA%\ticktick-sync\`: `.env` (the token),
`state.json` (the task-id map), `sync.log`, `sync.lock`. A plugin update
replaces the plugin folder wholesale, so nothing mutable may live inside it.
Override the location with `TICKTICK_SYNC_DATA` when testing.

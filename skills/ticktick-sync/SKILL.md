---
name: ticktick-sync
description: Mirrors a repository's open work -- its open GitHub issues plus the neutral item list open-items.toml -- into a TickTick list, one-way and strict, the repo always wins. Works for ANY repository: invoked inside one that is not set up yet, it asks what it needs, resolves or creates the TickTick list, drops an open-items.toml into the repo and mirrors it from then on alongside every other configured repo. Use this skill when the user says "ticktick sync", "update my list", "sync my ticktick", "open items to ticktick", "mirror this repo to ticktick", "set up ticktick for this repo", or when issues or the item list changed during a session and the state on their phone should be current.
---

# TickTick mirror

One call, one reconcile, per repository. This skill runs nothing the background
job would not also run -- that is exactly the point.

Each mirrored repository has its own directory in the data directory:

```
%LOCALAPPDATA%\ticktick-sync\
  .env                     shared credential -- one TickTick account
  launcher.pyw             shared
  sync.log                 shared; every line is prefixed with the repo slug
  repos\<owner>__<repo>\   config.toml, state.json, issue-descriptions.toml
```

Nothing about the mirror is ever written into the mirrored repository. The one
file this skill puts there, `open-items.toml`, is deliberately neutral and must
never mention TickTick or syncing.

## 1. Work out which repository this is

```bash
git remote get-url origin
PYTHONIOENCODING=utf-8 python "${CLAUDE_PLUGIN_ROOT}/skills/ticktick-sync/scripts/setup.py" slug --remote "<the url>"
```

It prints `slug=`, `repo=` and `configured=`. **Confirm the repo with the user
before doing anything with it** -- a fork, a personal mirror or a wrong `origin`
would otherwise silently become the thing that gets mirrored.

- `configured=yes` -- it is already set up. Say so, skip to **Run**, and sync
  just this one with `--repo <slug>`.
- `configured=no` -- continue with setup.

## 2. Ask which TickTick list to mirror into

Show the user what already exists rather than making them recall a name:

```bash
PYTHONIOENCODING=utf-8 python "${CLAUDE_PLUGIN_ROOT}/skills/ticktick-sync/scripts/setup.py" lists
```

Ask which one to mirror into, or what a new one should be called. Then resolve
it:

```bash
PYTHONIOENCODING=utf-8 python "${CLAUDE_PLUGIN_ROOT}/skills/ticktick-sync/scripts/setup.py" ensure-list --name "<list name>"
```

- Exit 0 -- it prints `list_id=`; keep it for step 4.
- Exit 2 (`missing=<name>`) -- the list does not exist. **Ask first.** Only if
  the user explicitly says yes, re-run the same command with `--create`.

Creating a list is a **setup-only** capability. The sync engine never creates
one and that rule is not up for negotiation: a mirror that invents its own list
turns a loud, recoverable "there is no list named X" into a second, silently
empty list sitting beside the real one.

Creating a list through this API is **unverified** -- `POST /open/v1/tag`
answers 500 here, so the project endpoint may too. Never probe it to find out:
a half-successful probe strands a list in a real account that the API cannot
delete again. If `--create` fails (exit 3), relay its message: create the list
by hand in the TickTick app under exactly that name, then re-run this step,
which resolves an existing list by name.

## 3. Put the item list in the repository

```bash
PYTHONIOENCODING=utf-8 python "${CLAUDE_PLUGIN_ROOT}/skills/ticktick-sync/scripts/setup.py" open-items --path .
```

Creates `open-items.toml` if it is absent (`version = 1`, `items = []`), never
overwrites one that exists. Tell the user it was created and that it is theirs
to fill -- the mirror reads it, nothing writes it. The file's own comments
explain its shape; `README.md` documents the fields and the twelve permitted
tags.

## 4. Write the configuration and sync

```bash
PYTHONIOENCODING=utf-8 python "${CLAUDE_PLUGIN_ROOT}/skills/ticktick-sync/scripts/setup.py" init \
  --repo "<owner/repo>" --list-id "<list id>" --list-name "<list name>"
```

That writes `repos/<slug>/config.toml` in the data directory -- **never** in the
repository being mirrored. Then run the first sync (next section) and report
what it did.

## Run

Do NOT run `sync.py` from `${CLAUDE_PLUGIN_ROOT}` directly. That path is bound
once, when this session loaded the plugin -- after an in-session
`claude plugin update` it still points at the OLD version, silently. Run the
stable launcher instead: it resolves the newest cached plugin version at run
time, every time, so it cannot go stale mid-session. It is the same launcher
the 5-minute background task uses (see `scripts/install_task.ps1`).

```bash
PYTHONIOENCODING=utf-8 python "$LOCALAPPDATA/ticktick-sync/launcher.pyw" --repo <slug>
```

Leave `--repo` off to sync every configured repository, which is what the
background task does. Use `python.exe` here, not `pythonw.exe` -- this runs in
a terminal, where seeing the output is the point. (The scheduled task calls the
same launcher with `pythonw.exe --quiet`, precisely so nothing shows on screen
every five minutes.)

The setup commands above are the one exception to the launcher rule: they are a
one-time action, so a slightly stale plugin path costs nothing.

## Report the result

One line per repository:
`<slug> ok desired=N created=A updated=U reopened=R completed=C`.
Report it in plain language -- what is new, what changed, what disappeared. If
several repositories ran, say which line belongs to which.

The exit code is non-zero if ANY repository failed, even when the others
succeeded -- read the log lines, not just the code.

## When it fails

A failing repository is logged against its own slug and does not stop the
others.

- **`desired fell from N to 0`** -- the read-failure guard fired. Nothing was
  completed. Check first whether everything really is closed; only then delete
  that repo's `repos\<slug>\state.json` and run again.
- **`there is no TickTick list named ...`** -- the list was renamed or deleted
  in TickTick. Fix the name in `repos\<slug>\config.toml`, or re-run setup. The
  sync never creates one.
- **`no repository <slug> is configured`** -- the message lists what IS
  configured; most likely a typo in `--repo`.
- **`gh ... failed`** -- check the GitHub login with `gh auth status`.
- **`-> 401`** -- the TickTick token expired; regenerate it under Settings →
  Account → API Token and put it in `%LOCALAPPDATA%\ticktick-sync\.env` as
  `TICKTICK_API_KEY=<token>` (also accepts `TICKTICK_TOKEN=`). One credential
  serves every repository.
- **`no .env in ...`** -- the data directory is missing. Create
  `%LOCALAPPDATA%\ticktick-sync` and populate `.env` with `TICKTICK_API_KEY=<token>`.
  It deliberately does NOT live in the plugin folder, because a plugin update
  replaces that wholesale -- which is exactly why no configuration lives there
  either.
- **Transient errors** (timeout, connection failure, 403) -- the mirror is
  idempotent; one failure is safe to ignore and the next run reconciles from
  scratch. A repeating error means the credential or connectivity needs attention.

Never work around an error by switching off the guard.

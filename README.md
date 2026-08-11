# ticktick-sync

Mirrors the open work of a GitHub repo (open issues plus a neutral item list,
`open-items.toml`) into a TickTick list. One-way and strict: the repo is
always right, and TickTick is brought to match it, never the other way round.

## Install

This is a **private** plugin in a private repository -- it is not listed on any
public marketplace, and `"license": "UNLICENSED"` in `.claude-plugin/plugin.json`
grants no rights to anyone. Registering it needs a `gh` login that already has
access to the repo:

```powershell
claude plugin marketplace add Halloplayer/ticktick-sync
claude plugin install ticktick-sync@ticktick-sync
```

Skill and engine then come from the plugin cache, and this repo does not need to
stay cloned -- except to run the one-time setup below, which uses
`skills/ticktick-sync/scripts/`.

Changing the plugin rather than using it: see [`DEVELOPMENT.md`](DEVELOPMENT.md)
and [`CONTRIBUTING.md`](CONTRIBUTING.md).

## One-time setup

1. Put your TickTick API token in `%LOCALAPPDATA%\ticktick-sync\.env` as:
   ```
   TICKTICK_API_KEY=<token>
   ```
   (`TICKTICK_TOKEN=` also works, if that name is already in use elsewhere.)
2. The target TickTick list must already exist -- create it by hand once in
   TickTick. The mirror never creates a list itself, only tasks inside one.
3. Install the background job -- from the root of this repo:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\skills\ticktick-sync\scripts\install_task.ps1
   ```
   This registers a Windows Scheduled Task named `TickTickSync` that runs
   every 5 minutes, on battery too, and catches up a run that was missed
   while the machine was asleep. The task's Execute is `pythonw.exe` running
   a small Python launcher (`%LOCALAPPDATA%\ticktick-sync\launcher.pyw`)
   that resolves the newest cached plugin version at run time and hands off
   to its `sync.py`.

   It is `pythonw.exe` running that launcher directly -- deliberately not a
   `powershell.exe` wrapper around it. `powershell.exe` allocates its
   console window BEFORE any `-WindowStyle Hidden` flag takes effect, so a
   PowerShell wrapper flashes a black window on screen for an instant on
   every single run; at 5-minute intervals that is twelve flashes an hour,
   hours on end. `pythonw.exe` never allocates a console at all, so there is
   no window to flash regardless of any hiding flag. Do not "simplify" this
   back to a PowerShell wrapper -- it would reintroduce exactly that.

## Tags, and the one rule about `#`

The mirror uses **tags**, never TickTick priorities. The vocabulary is closed to
twelve:

| Tag | Means |
|---|---|
| `P0` `P1` `P2` `P3` | an AGREED priority on a promoted tracker issue -- taken from the issue's own priority label |
| `_P0` `_P1` `_P2` `_P3` | a PROPOSED priority on an issue draft that has not been promoted yet -- taken from the draft's own frontmatter |
| `Draft` | an issue draft -- an item that names a `source` |
| `Task` | open work that is on the table but is not an issue |
| `Bug` | something not on the table that is broken and needs fixing |
| `Clarification` | the owner needs to answer something, or something awaits their approval |

Two disjoint priority namespaces, deliberately. A plain priority (`P0`-`P3`)
states an AGREED priority and belongs only to a promoted tracker issue. The
underscored form (`_P0`-`_P3`) states a PROPOSED one, carried by an unpromoted
draft's own frontmatter -- worth showing, but not worth showing as an
agreement nobody has made. `open-items.toml` holds only non-issues and
unpromoted drafts, so a plain priority never belongs there at all; a draft's
proposal always goes in with `Draft`, never alone.

In `open-items.toml` an item sets them itself -- a draft with a proposed
priority, for example:

```toml
tags = ["Draft", "_P1"]
```

**`tags = ["Draft", "P1"]` raises.** A plain priority states an agreed
priority on a promoted issue, and a draft is by definition not one:

```
GitHubReadFailed - Item 'x' is tagged 'P1'. A plain priority states an AGREED
priority on a promoted tracker issue, and this file holds only unpromoted
drafts and work that is not an issue at all. For a draft's proposed priority
write '_P1' instead.
```

The rule in one line: plain priorities belong only to real, promoted issues;
drafts use the underscore form. Anything outside the twelve permitted tags
aborts the read and names the offender -- deliberately, because TickTick's API
cannot delete a tag it creates, so a typo would leave litter only a human can
clear from the app.

**No `#` reaches TickTick.** TickTick turns any `#token` in a task's text into
a tag, and its API cannot delete a tag again -- the mirror's old `#12` title
prefix had been quietly minting junk tags (`12`, `11`, `14`, ...) in the
owner's own account, which only a human could clear, by hand, in the app. So
every title and body passes through one sanitiser (`models.sanitise`) before
anything is sent: `#12` becomes ` issue 12`, any other `#` is dropped. Write
`moot via #12` in the file anyway -- what you write is what you read, the
sanitiser does the rewriting for you. A crossreference (`#12`) inside the text
is rewritten in place, not moved to either end -- see Title prefixes, next,
for the mirror's own `[Issue -> N]`-style markers, which are a different
thing.

## Title prefixes

A task's title starts with one of three prefixes -- what a task IS, what it
POINTS AT, and which KIND of thing it points at, all visible at a glance on a
phone, without opening it. Always prepended: an explicit owner decision, even
for the `Draft Related` form, whose full German draft title can push the
combined line past 100 characters.

| Prefix | Appears on | Set by | Means |
|---|---|---|---|
| `[Issue -> 12] ` | every mirrored GitHub issue | (automatic) | this task mirrors GitHub issue #12 |
| `[Issue Related -> 12] ` | any item in `open-items.toml` | `related = 12` | this item is related to GitHub issue #12 |
| `[Draft Related -> <full draft title>] ` | an item tagged `Clarification` | `related_draft = "<draft item id>"` | this item is a clarification about the named draft |

`related_draft` is looked up by the draft's **item id**, not its title -- the
title shown in the prefix is resolved from that id at render time, so a
renamed draft cannot leave a stale title sitting in a clarification's task.

## What a task says

Each task opens with a short description, so it can be understood from a phone
without opening anything:

```
<description>

Source: <ISSUE-... id, or the issue URL>
[sync:<key>]
```

For issues that text is an excerpt of the issue body, never a generated
summary. For items it is the item's own `description` field -- every item
should carry one: three to four English sentences, written to be read cold,
regardless of what language the item's own title is in. `description` is not
enforced by the reader (an item without one simply opens with no text at
all), but it is the whole reason a task can be understood without opening
anything, so treat it as required in practice.

A task's **title** stays in whatever language it was written -- German for a
mirrored GitHub issue or an issue draft, see "Naming" below -- but when an
English translation of that title exists, it opens the body as its own first
line, ahead of the description:

```
<English translation of the title>

<description>

Source: <ISSUE-... id, or the issue URL>
[sync:<key>]
```

An English-titled item (`Task`, `Bug`, `Clarification`) gets no such line --
it is already English, so a translation of it would say nothing. See "Issue
descriptions AND titles are translated by hand" below for where the
translation itself comes from.

## Item fields

Beyond `id`, `title`, `status`, `owner`, `tags`, `source` and `note` (see the
tag table and the `open-items.toml` example above), an item may also carry:

| Field | Meaning |
|---|---|
| `description` | see "What a task says" above -- the task's opening text |
| `title_en` | an English translation of a draft's (German) `title`, shown as the body's opening line -- see "Issue descriptions AND titles are translated by hand" below. Valid only on an item that names a `source` (an issue draft); on anything else it raises, since that item is already titled in English |
| `source_url` | a tap-through link, appended to the `Source:` line alongside `source` (`Source: <source> - <source_url>` when both are set) |
| `related` | a GitHub issue **number** this item relates to; renders as the `[Issue Related -> N] ` prefix |
| `related_draft` | the **item id** (not the title) of a draft this item -- always tagged `Clarification` -- is a clarification about; renders as the `[Draft Related -> ...] ` prefix, with the title resolved live |

An item may set `related` or `related_draft`, never both, and neither on a
draft itself -- a draft is the thing that gets pointed *at*, not the thing
that points.

## Naming

Issues and issue drafts keep their **original** name, German included -- an
issue's title is mirrored exactly as GitHub returns it, and a draft's title in
`open-items.toml` is whatever the draft itself is called. Everything else
(`Task`, `Bug`, `Clarification` items) is named in English. `description` is
always English, regardless of which of these an item is -- it is read cold
from a phone and needs no context to make sense. Since a task's title itself
stays German for the ten items that need it, an English translation of that
title opens the body as its own first line instead -- see "What a task says"
above and "Issue descriptions AND titles are translated by hand" below for where that
translation comes from.

## Running it by hand

```powershell
$env:PYTHONIOENCODING="utf-8"; python skills\ticktick-sync\scripts\sync.py
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

## Issue descriptions AND titles are translated by hand

Task descriptions must always be English, but a GitHub issue's own body is
German, and the sync has no LLM and no translation API -- either would break
its determinism and its zero-dependency rule. So each issue's English
description is translated by hand into `issue-descriptions.toml`, keyed by a
hash of the exact German excerpt it was translated from. Every run
recomputes that hash and compares it: a match uses the cached English text; a
mismatch, or no cached entry at all, falls back to the German excerpt itself,
prefixed `[untranslated] ` and counted into the summary line's
`untranslated=N`. Seeing `[untranslated]` on a task means the issue changed
upstream since somebody translated it -- update the entry in
`issue-descriptions.toml` (new excerpt, new hash, new translation) to clear
it.

An issue's **title** stays German too (see "Naming" above), and its
translation lives in the same `issue-descriptions.toml` entry, alongside the
description: `title_sha256` (a hash of the sanitised title, WITHOUT the
generated `[Issue -> N] ` prefix -- that prefix is never translated) and
`title_en`. A matching hash opens the task's body with that translation, as
its own first line ahead of the description; a mismatch gets the same
`[untranslated] ` treatment as a stale description and counts toward the same
`untranslated=N`. Unlike the description fields, `title_sha256`/`title_en`
are optional per entry: an issue nobody has translated the title of yet
simply shows no title line at all, rather than a spurious `[untranslated]`.

An **issue draft** in `open-items.toml` (see "Item fields" above) keeps its
own title German too, but its translation needs no hash: the German title and
the English `title_en` sit side by side in the same hand-edited file, so an
edit to one is visible right next to the other and drift cannot hide the way
it can across two separate files. `title_en` is valid only on a draft (an
item naming a `source`); on anything else it raises `GitHubReadFailed`, since
that item is already titled in English.

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

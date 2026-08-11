# Contributing to ticktick-sync

This repo is **a published Claude Code plugin**. Consumers pull the default
branch's HEAD into `~/.claude/plugins/cache/`, so:

> **`master` = production.** What lands here is what the 5-minute background job
> on somebody's machine runs next tick.

> **Note:** server-side branch protection is **not available** on this **private**
> repo under the GitHub **free** plan (HTTP 403, "Upgrade to GitHub Pro or make
> this repository public"). Enforcement is therefore **soft**: this convention
> plus the local `pre-push` hook.

## One-time setup after cloning

Activate the shipped git hooks:

```bash
python .githooks/setup.py
```

That writes the repo-local `core.hooksPath = .githooks`. It is needed once per
clone -- git does not version `.git/hooks/`, which is why the hooks live tracked
under `.githooks/`.

## The one rule that is not style

**The mirror must never silently shrink the desired set.** Everything else here
is negotiable; this is not. A read that returns fewer items than reality does
not look like a failure -- it looks like finished work, and the sync will tick
off real, open tasks in the owner's own list. Three refusals exist for it
(`CollapseRefused`, `GitHubReadFailed`, `StateUnreadable`) and they are covered
by tests. Do not work around a firing guard by disabling it.

## Tests

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s skills/ticktick-sync/tests -p "test_*.py"
```

Standard library only -- `unittest`, never `pytest`. All of them must pass before a push. They are offline -- the GitHub and TickTick
edges run against recorded shapes, not the network -- so there is no excuse for
skipping them. One class (`LiveItemFileTest`) reads the real `open-items.toml`
from a `globex-toolkit-dev` checkout beside this repo and skips where there is
none; on the machine that actually runs the sync it must not skip.

## Commits

Subject line: `[TAG] scope: what changed`, where TAG is one of `ADD`, `FIX`,
`IMP`, `REF`. The body explains **why**, not what -- the diff already says what.

A user-visible change gets a `CHANGELOG.md` entry under `## [Unreleased]` in the
same commit.

## Releasing

1. Move the `## [Unreleased]` entries under a new `## [X.Y.Z]` heading.
2. Bump `version` in `.claude-plugin/plugin.json` to match.
3. Commit, push. Consumers pick it up on their next plugin update.

The version bump is what actually ships the change -- without it the cache keeps
serving the old copy.

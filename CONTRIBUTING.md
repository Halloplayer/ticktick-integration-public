# Contributing to ticktick-integration

This repo is **a published Claude Code plugin**. Consumers pull the default
branch's HEAD into `~/.claude/plugins/cache/`, so:

> **`master` = production.** What lands here is what the 5-minute background job
> on somebody's machine runs next tick.

> **Note:** `master` is protected server-side. Force-pushes and deletion of the
> branch are refused for everyone, administrators included -- the two ways this
> branch could lose history, and the two the server can refuse without getting
> in anyone's way. Ordinary direct pushes are **not** gated: in a
> one-maintainer repo a pull-request requirement costs more than it returns, so
> the branch-and-PR flow above stays a convention.
>
> **No git hook ships to back that convention up, on purpose.** The one that
> used to be named here never blocked anything -- its only executable line was
> `exit 0` underneath a comment block describing the barrier it was not. A
> barrier you believe in and do not have is worse than one you know is missing:
> the first makes you careless, the second makes you careful. So the guarantees
> that hold are the ones the server enforces, and they are named above; nothing
> else is claimed.

## The one rule that is not style

**The mirror must never silently shrink the desired set.** Everything else here
is negotiable; this is not. A read that returns fewer items than reality does
not look like a failure -- it looks like finished work, and the sync will tick
off real, open tasks in the owner's own list. Three refusals exist for it
(`CollapseRefused`, `GitHubReadFailed`, `StateUnreadable`) and they are covered
by tests. Do not work around a firing guard by disabling it.

## Tests

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s skills/sync/tests -p "test_*.py"
```

Standard library only -- `unittest`, never `pytest`. All of them must pass
before a push. They are offline -- the GitHub and TickTick edges run against
recorded shapes, not the network -- so there is no excuse for skipping them,
and nothing in the suite reaches for a checkout outside this repo.

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

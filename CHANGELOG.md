# Changelog

All notable changes to the `ticktick-sync` plugin are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

Effort markers (`[~Xh]`) are deliberately absent: this repo was built before the
convention existed, and back-filling them would mean inventing numbers.

## [Unreleased]

### Changed
- **The three title markers (`[Issue -> N]`, `[Issue Related -> N]`,
  `[Draft Related -> <title>]`) moved from a suffix to a prefix.** Same text,
  same brackets, same content -- only the position changed, on an explicit
  owner decision, even for the `Draft Related` form, whose full German draft
  title can push the combined line past 100 characters. `lib/github.py`
  (`ISSUE_PREFIX`, `ISSUE_RELATED_PREFIX`, `DRAFT_RELATED_PREFIX`,
  `_link_prefix`) and every position-asserting test in `test_github.py` and
  `test_models.py` were updated in place rather than duplicated, so the suite
  never holds two contradictory assertions about one behaviour. `README.md`
  ("Title prefixes") and the design doc's superseded suffix reasoning were
  updated to match (the design doc keeps the old text visible under a new
  `**Amended**` note rather than rewriting it). 233 tests pass, zero skips.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩
- **Repository restructured to the standard plugin layout.** The engine modules
  moved from the `ticktick_sync/` package to `lib/`, and the entry point, the
  task installer, the probe and the tests moved under
  `skills/ticktick-sync/{scripts,tests}/` -- one skill owning its own code, with
  `lib/` for what it shares, exactly as `globex-toolkit` is laid out. Imports are
  flat `sys.path` inserts rather than an installed package (`lib/` carries no
  `__init__.py` -- nothing imports it as a package, so one would be dead
  weight), because the plugin runs straight out of the cache where nothing is
  ever pip-installed. The generated `launcher.pyw` now targets
  `skills/ticktick-sync/scripts/sync.py` under the resolved version directory
  and raises `SystemExit`, naming the path, if it is not there -- loudly, on
  purpose: it runs under `pythonw.exe` with no console and before `sync.py` has
  set up its own logging, so a silent failure there would kill the 5-minute job
  with nothing in `sync.log` to show why. Behaviour is otherwise unchanged --
  232 tests pass (229 plus three new ones guarding the launcher's new target
  path and its no-silent-fallback regression).
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩
- Root documentation set completed to match the house layout: `CHANGELOG.md`,
  `CONTRIBUTING.md` and `DEVELOPMENT.md` alongside the existing `README.md`,
  plus `.claude/settings.json` and the `.githooks/` bootstrap.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩
- The five live-file guard tests in `test_github.py` (`LiveItemFileTest`) locate
  the `globex-toolkit-dev` working copy by walking up from the test file to this
  repo's root instead of a fixed `"..", "..", "..", ".."` depth -- the fixed
  depth is exactly what silently broke them when the tests moved a directory
  deeper, leaving all five reporting a false "not on this machine" skip instead
  of running. `TICKTICK_SYNC_WIKI_DIR` overrides the search, and the skip
  message now names the exact path it looked for.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [1.2.0]

### Added
- **Translated title as the body's opening line.** A task whose title stays in
  its original language (German, for mirrored issues and drafts) now opens its
  body with the English translation, ahead of the description -- readable cold
  from a phone without opening anything. For issues the translation and its
  `title_sha256` live in `issue-descriptions.toml`; for drafts, `title_en` sits
  beside the German title in `open-items.toml`, where drift cannot hide.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [1.1.0]

### Added
- **Hand-translated cache for issue descriptions.** Task descriptions must be
  English while the issues themselves are German, and the sync has neither an
  LLM nor a translation API -- either would break its determinism and its
  zero-dependency rule. Translations are keyed by a hash of the exact excerpt
  they came from; a mismatch falls back to the German text, prefixed
  `[untranslated] ` and counted in the summary line.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

### Fixed
- **Windowless launcher.** The scheduled task ran through
  `powershell.exe -WindowStyle Hidden`, which allocates its console *before*
  the flag takes effect -- a black window flashed on screen twelve times an
  hour. Replaced with `pythonw.exe` running `launcher.pyw` directly:
  `pythonw.exe` never allocates a console, so there is no window to hide.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [1.0.1]

### Fixed
- Config points at the renamed list (`globex-toolkit`).
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [1.0.0]

### Fixed
- **Stale skill path.** `${CLAUDE_PLUGIN_ROOT}` binds once, when the session
  loads the plugin, so an in-session `claude plugin update` left the skill
  running the OLD version silently. The skill now goes through the same stable
  launcher as the background job, which resolves the newest cached version at
  run time.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

### Added
- Tags, title suffixes and naming rules documented in the README.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [0.6.0]

### Added
- Three suffix forms (`[Issue -> N]`, `[Issue Related -> N]`,
  `[Draft Related -> ...]`), with draft links resolved by item id rather than
  title, so renaming a draft cannot strand a stale title in a clarification.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [0.5.0]

### Fixed
- **A separate namespace for a draft's proposed priority.** Plain `P0`-`P3`
  state an agreed priority on a promoted issue; the underscored `_P0`-`_P3`
  state a proposal on an unpromoted draft. A plain priority in
  `open-items.toml` now raises instead of quietly asserting an agreement
  nobody made.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [0.4.0]

### Fixed
- Original names kept (German included), tappable sources on every item, and
  `Draft` restricted to items that name a `source`.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [0.3.1]

### Fixed
- Clear leftover priority flags instead of preserving them.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [0.3.0]

### Changed
- **Tags instead of priorities, and no `#` reaches TickTick.** TickTick turns
  any `#token` in a task's text into a tag and its API cannot delete one again
  -- the old `#12` title prefix had been quietly minting junk tags in the
  owner's own account. Every title and body now passes through one sanitiser
  before anything is sent.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩
- A description on every task, so it reads cold from a phone.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [0.2.1]

### Fixed
- Bound the `gh` subprocess call with a timeout.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [0.2.0]

### Fixed
- **Closed the five ways the desired set silently shrinks.** A read failure
  that yields fewer items than reality would tick off real, open work. The
  collapse guard refuses a fall to zero; `GitHubReadFailed` and
  `StateUnreadable` cover the partial collapse it cannot see.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

## [0.1.0]

### Added
- Initial mirror: `reconcile` as a pure function, the GitHub reader through the
  machine's existing `gh` login, the TickTick writing edge, the collapse guard,
  the manual skill, the 5-minute background job and the marketplace packaging.
  ⟨by:Halloplayer <halloplayer7@gmail.com>⟩

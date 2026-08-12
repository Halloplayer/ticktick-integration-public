# Changelog

All notable changes to the `ticktick-integration` plugin are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

Effort markers (`[~Xh]`) are deliberately absent: this repo was built before the
convention existed, and back-filling them would mean inventing numbers.

## [Unreleased]

### Added

- A `LICENSE` file, and with it an actual licensing decision: the plugin is now
  MIT. Until now the only statement of rights was a `"license": "UNLICENSED"`
  token inside the plugin manifest -- inherited from when this repository was
  not public, never chosen for the world to read, and invisible at the place a
  reader or GitHub itself looks. The manifest and the README's install section
  now agree with the licence file.

### Fixed

- The documented install no longer points at a repository that does not exist.
  `README.md` and the manifest's `repository` field both named a repository that
  has since been deleted, so `claude plugin marketplace add` failed outright for
  anyone following the instructions. Both now name this repository.
- `README.md` and `CONTRIBUTING.md` described this as a private repository. It is
  public, and one of those claims did real work: the note explaining why branch
  protection is only softly enforced justified it with a limitation that applies
  to private repositories, so the reasoning inverted the moment this repo became
  public. Protection is available here; it is simply not configured yet.
- The `sync` rename below left five commands in `README.md` and `DEVELOPMENT.md`
  calling `skills\ticktick-integration\scripts\`, a path that has not existed
  since that rename. They now call `skills\sync\scripts\`.

## [4.1.0]

### Changed

- The skill is named `sync`, not `ticktick-integration`. Invoking it read
  `ticktick-integration:ticktick-integration` -- the same word twice, telling the
  reader nothing the plugin name had not already said. It is now
  `ticktick-integration:sync`, and its directory moved to `skills/sync/` with the
  launcher's entry point following it. That path is resolved at run time by the
  five-minute background job, so leaving it behind would have stopped the mirror
  with no console to report it.

## [4.0.0]

### Changed
- **Project renamed `ticktick-sync` -> `ticktick-integration`.** Every in-repo path, package
  reference, cache path and generated artifact name follows: `.claude-plugin/plugin.json` and
  `marketplace.json` (`name`, `repository`),
  `skills/ticktick-sync/` -> `skills/ticktick-integration/`
  (via `git mv`, so history follows), the data directory (`%LOCALAPPDATA%\ticktick-sync\` ->
  `%LOCALAPPDATA%\ticktick-integration\`), the plugin cache path the generated launcher resolves
  (`.claude/plugins/cache/ticktick-sync/ticktick-sync` ->
  `.claude/plugins/cache/ticktick-integration/ticktick-integration`), the Scheduled Task name
  (`TickTickSync` -> `TickTickIntegration`), and the dev-only override environment variables
  (`TICKTICK_SYNC_DATA` -> `TICKTICK_INTEGRATION_DATA`, `TICKTICK_SYNC_WIKI_DIR` ->
  `TICKTICK_INTEGRATION_WIKI_DIR`). Historical text is deliberately left alone: commit-message
  quotes, the `docs/superpowers/` plan and spec amendments describing what the project was called
  at the time, and the path/env-var names inside every changelog entry below this one, which
  record what was actually true at each past release. `legacy/issue-descriptions.toml`'s comment
  naming the pre-restructure `ticktick_sync/github.py` package path is left as-is too -- a
  pre-existing stale reference in frozen migration-seed data, unrelated to this rename. The live
  `%LOCALAPPDATA%\ticktick-sync\` installation itself is untouched; migrating it to the new data
  directory is a manual, separate step. 316 tests pass, zero skips (unchanged in count from before
  the rename -- this release adds no behaviour, only names).

### Added
- **A changelog version guard.** One test reads `version` out of `.claude-plugin/plugin.json` and
  asserts `CHANGELOG.md` contains a matching `## [<version>]` heading, so a version bump without a
  changelog entry now fails the suite instead of silently shipping undocumented. `CHANGELOG.md`
  itself is now tracked in git for the first time -- it existed on disk but was never committed, so
  it never actually shipped with the plugin despite being kept up to date by hand.

## [3.1.0]

### Added
- **Per-repository rendering language.** `config.toml` gained `language = "de"` or `"en"`. `"de"`,
  the new default, renders every task title and description exactly as written -- no
  `issue-descriptions.toml` lookup, no translated-title line, no `[untranslated]` prefix and no
  `untranslated=N` in the summary line, because nothing is being translated. `"en"` is the mirror's
  original behaviour, unchanged. A config with no `language` key migrates automatically, once, the
  first time it loads: to `"en"` if its repo's `issue-descriptions.toml` already holds translations
  (so a config that is English today cannot silently revert to German), to
  `"de"` otherwise -- the decision is written back into `config.toml` so it happens exactly once.
  `setup.py init` gained `--language` and the skill now asks which one the user wants.

### Fixed
- **`open-items.toml`'s `title_en` (a draft's hand-written title translation) now honours
  `language` too.** It was left rendering unconditionally when the `language` setting above was
  added, so a `"de"` repo whose file carried a `title_en` still opened that task's body with an
  English first line ahead of an otherwise all-German task -- exactly the artifact `"de"` promises
  to remove, and a mixed-language body besides. `toml_to_items()` gained the same `language`
  parameter `issues_to_items()` already had; `title_en` now renders only in `"en"` and is simply
  left unrendered (not an error, not removed from the file) in `"de"`.

## [3.0.0]

### Fixed
- **Conversational setup for a new repository**, driven by the rewritten
  `SKILL.md` plus `skills/ticktick-sync/scripts/setup.py`. It derives the slug
  from `git remote get-url origin` and has the user confirm it, reports whether
  the repo is already configured, lists the account's existing TickTick lists
  to pick from, writes `repos/<slug>/config.toml`, and creates a neutral
  `open-items.toml` in the target repo if it has none -- never overwriting one,
  and never mentioning TickTick in it, because a mirrored repo must not learn
  the mirror exists.
- **Setup, and only setup, may create a TickTick list** -- after an explicit
  confirmation, through `ticktick.Client.create_list` / `repo_setup.ensure_list`,
  which the sync path never calls (a structural test asserts `sync_core.py`,
  `reconcile.py` and `sync.py` do not so much as name it). `resolve_list` still
  refuses a missing list, unchanged. The API call is UNVERIFIED -- `POST /tag`
  answers 500 on this API -- and is deliberately never probed speculatively,
  because a half-successful probe would strand a list in a real account that
  the API cannot delete again; any failure falls back to "create it by hand in
  the app, then re-run setup", which resolves it by name.

### Changed
- **The mirror serves any number of repositories, not one.** Per-repo data now
  lives in the data directory keyed by the slug `<owner>__<repo>`
  (`repos\<slug>\config.toml`, `state.json`, `issue-descriptions.toml`), with
  `.env`, `launcher.pyw` and `sync.log` shared above it and every log line
  prefixed with the slug it belongs to. `config.toml` and
  `issue-descriptions.toml` are GONE from the plugin root, which closes a
  latent bug quite apart from multi-repo: the plugin is a version-scoped cache
  directory that an update replaces wholesale, so a user's own configuration
  and hand-written translations were one update away from silent deletion. The
  plugin ships code only; `legacy/` holds the frozen single-tenant files purely
  as a one-shot migration seed and can be deleted once every installation has
  migrated. `run_sync` is untouched and still syncs one repo against one
  config; the new layer above it discovers `repos/*/config.toml` and runs each
  in turn. A repo whose sync raises is caught, logged against its own slug and
  does not stop the others -- but the process still exits non-zero if any
  failed, so the Scheduled Task's result code keeps meaning something. One task
  still drives everything: it runs the launcher with no `--repo`. New
  `sync.py --repo <slug>` syncs exactly one, and an unknown slug fails naming
  what is configured. Slugs come from `git remote get-url origin` and are not
  trusted: a separator, a `..` or an absolute path is refused rather than
  joined onto the data directory. Everything else is unchanged per repo -- the
  collapse guard, the marker rule, the twelve-tag vocabulary, the three title
  prefixes, the `#` sanitiser, hash-guarded translations, never touching
  unmarked tasks, and never creating a list. 295 tests pass, zero skips.
## [2.1.0]

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

## [2.0.0]

### Changed
- **Repository restructured to the standard plugin layout.** The engine modules
  moved from the `ticktick_sync/` package to `lib/`, and the entry point, the
  task installer, the probe and the tests moved under
  `skills/ticktick-sync/{scripts,tests}/` -- one skill owning its own code, with
  `lib/` for what it shares. Imports are
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
- The live-file guard tests in `test_github.py` locate the mirrored repository's
  working copy by walking up from the test file to this repo's root instead of a
  fixed `"..", "..", "..", ".."` depth -- the fixed depth is exactly what
  silently broke them when the tests moved a directory deeper, leaving them
  reporting a false "not on this machine" skip instead of running. The skip
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
- Config points at the renamed list.
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

"""One directory per mirrored repository, and the one-shot migration into it.

The mirror was born single-tenant: one `config.toml` at the plugin root, one
`state.json` in the data directory, one repository. The plugin root is the
wrong home for either -- it is a version-scoped cache directory that a plugin
update replaces WHOLESALE, so a user's own configuration was always one update
away from being deleted. That was a latent bug before it was an obstacle.

The layout that replaces it:

    %LOCALAPPDATA%\\ticktick-integration\\
      .env                shared credential -- one TickTick account
      launcher.pyw        shared
      sync.log            shared, every line prefixed with the repo slug
      repos\\
        <owner>__<repo>\\
          config.toml     repo, list_id, list_name, items_path
          state.json      key -> task id, last_count
          issue-descriptions.toml

Nothing configuration-shaped goes into the mirrored repository itself: a fixed
constraint of this project is that a mirrored repo must not learn the mirror
exists, and a config file naming TickTick would break exactly that. The single
exception is `open-items.toml`, which is deliberately neutral.
"""
import os
import pathlib
import re
import shutil

# `<owner>__<repo>`. A double underscore, because GitHub allows a single one in
# both halves but not two in a row, so the pair still splits unambiguously.
SEPARATOR = "__"

# The one installation that predates all of this, migrated automatically.
LEGACY_SLUG = "Work" + SEPARATOR + "globex-toolkit"

# The legacy state.json is COPIED, not moved: it backs seventeen real tasks and
# stays recoverable if anything about the new layout turns out wrong. It is
# renamed afterwards so that no later run can mistake it for live state and
# migrate a second time over a state that has moved on.
BACKUP_SUFFIX = "pre-multi-repo"

# Deliberately narrower than "anything without a slash". A slug becomes a
# directory name under the data directory and comes from a git remote, which
# is not ours to trust: an allowlist of the characters GitHub actually permits
# in an owner or repository name refuses everything else by construction,
# rather than by enumerating the escapes somebody thought of.
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Both dialects of remote, reduced to `owner/repo`:
#   https://github.com/acme/widgets.git   ssh://git@github.com/acme/widgets
#   git@github.com:acme/widgets.git       https://user@github.com/acme/widgets
_REMOTE = re.compile(r"[:/]([^/:]+)/([^/:]+?)(?:\.git)?/*$")


class SlugError(Exception):
    """A repository slug that must not become a path."""


class MigrationFailed(Exception):
    """The legacy installation could not be lifted into the new layout.

    Loud on purpose: the alternative is a repo directory that discovery
    ignores, on a machine whose mirror then reports nothing wrong while
    mirroring nothing at all.
    """


def check_slug(slug):
    """Return the slug, or refuse it.

    The slug is derived from `git remote get-url origin` -- attacker-supplied
    in principle, typo-supplied in practice -- and is then joined onto the data
    directory. Anything that could walk out of that directory is refused here,
    once, so that every caller downstream can treat it as a plain name.
    """
    if not slug:
        raise SlugError("empty repository slug")
    if ".." in slug:
        raise SlugError("repository slug %r contains '..' -- refusing to build a "
                        "path that could escape the data directory" % slug)
    if not _SLUG.match(slug):
        raise SlugError("repository slug %r is not a plain directory name (letters, "
                        "digits, '.', '-', '_' only) -- refusing to use it as a path"
                        % slug)
    return slug


def slug_from_remote(url):
    """`git remote get-url origin` -> `<owner>__<repo>`.

    Every dialect of the same remote must reduce to the same slug. Two slugs
    for one repository would mean two state files, two sets of task ids, and a
    duplicate of every task in the user's own list -- and because tasks are
    keyed by their marker, only one twin would ever be seen again.
    """
    match = _REMOTE.search((url or "").strip())
    if not match:
        raise SlugError("cannot read an owner/repo pair out of the remote %r" % url)
    owner, repo = match.group(1), match.group(2)
    return check_slug(SEPARATOR.join([check_slug(owner), check_slug(repo)]))


def slug_for(repo):
    """`owner/repo` -> slug."""
    parts = (repo or "").strip().strip("/").split("/")
    if len(parts) != 2:
        raise SlugError("expected an 'owner/repo' pair, got %r" % repo)
    return check_slug(SEPARATOR.join([check_slug(parts[0]), check_slug(parts[1])]))


def repo_from_slug(slug):
    """slug -> `owner/repo`, the form `config.toml` and `gh` both speak."""
    check_slug(slug)
    if SEPARATOR not in slug:
        raise SlugError("repository slug %r carries no %r separator" % (slug, SEPARATOR))
    owner, _, repo = slug.partition(SEPARATOR)
    return "%s/%s" % (owner, repo)


def repos_dir(data_dir):
    return pathlib.Path(data_dir) / "repos"


def repo_dir(data_dir, slug):
    return repos_dir(data_dir) / check_slug(slug)


def discover(data_dir):
    """Every configured repository, as (slug, config path), sorted.

    Sorted so the log reads the same way twice, and so a failure is always
    reported in the same order. Anything that is not a directory holding a
    `config.toml` is ignored: the shared `.env`, `sync.log` and `launcher.pyw`
    live one level up on purpose, and a half-finished setup must not abort
    every other repository.
    """
    root = repos_dir(data_dir)
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if not entry.is_dir():
            continue
        config = entry / "config.toml"
        if config.is_file():
            found.append((check_slug(entry.name), str(config)))
    return found


def migrate_legacy(data_dir, seed_dir):
    """Lift the single-repo installation into `repos/<LEGACY_SLUG>/`, once.

    Returns the migrated slug, or None when there was nothing to do.

    The trigger is a `state.json` sitting directly in the data directory --
    the shape only the old layout ever produced. That file is the reason this
    exists at all: it carries `last_count`, which ARMS the collapse guard.
    Regenerating it would report a comfortable zero, and `guard_collapse`
    refuses only a fall from non-zero -- so a lost `last_count` switches the
    one safeguard against completing a live list off for exactly one run. It
    is therefore copied byte for byte, never rebuilt.

    Idempotent twice over: the copy is skipped if the target config already
    exists, and the legacy file is renamed out of the way afterwards so the
    trigger cannot fire again.
    """
    data = pathlib.Path(data_dir)
    legacy_state = data / "state.json"
    if not legacy_state.is_file():
        return None

    target = repo_dir(data, LEGACY_SLUG)
    if (target / "config.toml").is_file():
        # Already migrated (or set up by hand). Whatever is there now is live
        # and newer than this; stamping a stale copy over it would reset the
        # very count this function exists to preserve.
        return None

    seed = pathlib.Path(seed_dir)
    if not (seed / "config.toml").is_file():
        # Checked BEFORE anything is written or renamed. A repo directory
        # holding a state.json but no config.toml is invisible to discover(),
        # so half a migration is worse than none: the run would look healthy
        # while mirroring nothing, with the legacy state already moved aside.
        raise MigrationFailed(
            "cannot migrate the single-repo installation: no config.toml in %s. "
            "The legacy state in %s was left untouched." % (seed, data))

    target.mkdir(parents=True, exist_ok=True)
    for name in ("config.toml", "issue-descriptions.toml"):
        source = seed / name
        if source.is_file():
            shutil.copyfile(str(source), str(target / name))
    shutil.copyfile(str(legacy_state), str(target / "state.json"))

    try:
        os.replace(str(legacy_state), str(data / ("state.json." + BACKUP_SUFFIX)))
    except OSError:
        # The copy is what matters and it already succeeded; the target's
        # config.toml alone keeps this from running twice.
        pass
    return LEGACY_SLUG

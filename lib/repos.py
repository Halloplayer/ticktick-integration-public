"""One directory per mirrored repository.

Nothing configuration-shaped belongs at the plugin root: that is a
version-scoped cache directory which a plugin update replaces WHOLESALE, so a
user's own configuration would always be one update away from being deleted.
Everything mutable therefore lives in the data directory instead.

The layout:

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
import pathlib
import re

# `<owner>__<repo>`. A double underscore, because GitHub allows a single one in
# both halves but not two in a row, so the pair still splits unambiguously.
SEPARATOR = "__"

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

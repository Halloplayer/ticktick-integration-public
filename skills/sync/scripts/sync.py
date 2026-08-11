"""Entry point. Both triggers -- skill and scheduled task -- call this.

One engine, two thin triggers: what comes out by hand is exactly what the
background job does. Since the mirror became multi-repo there is a third
sameness to keep: every configured repository goes through the SAME `run_sync`
with its own config and its own state, one after another. A repository that
fails is one repository that failed -- it is caught, named in the log, and the
rest still run -- but the process still exits non-zero, because the Scheduled
Task's result code is the only signal a background job has and it must not lie.
"""
import argparse
import datetime
import os
import pathlib
import sys
import time

# Code and data live apart on purpose. HERE is this script's folder inside the
# plugin cache and ROOT the plugin root above it -- both version-scoped, and an
# update replaces them wholesale. Everything mutable therefore belongs in DATA,
# which survives updates. That is not a preference: the plugin used to keep
# config.toml and issue-descriptions.toml at ROOT, where the next update would
# have deleted a user's own configuration without a word.
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent

# The engine modules are shared helpers under the plugin root, reached by path
# rather than as an installed package -- the plugin is run straight out of the
# cache, where nothing is ever pip-installed.
sys.path.insert(0, str(ROOT / "lib"))

import github  # noqa: E402
import repos  # noqa: E402
import ticktick  # noqa: E402
from sync_core import run_sync  # noqa: E402


def data_dir():
    """Where the mutable state lives -- resolved without ever raising.

    This runs at import time, where there is no exception handler, no log file
    and, under pythonw.exe, no console. A bare `os.environ["LOCALAPPDATA"]`
    lookup that missed would kill the process before main() so much as exists,
    leaving nothing anywhere to say why the mirror stopped. Any answer that
    lets the run reach its own error handling beats a KeyError here.
    """
    override = os.environ.get("TICKTICK_INTEGRATION_DATA")
    if override:
        return pathlib.Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return pathlib.Path(local) / "ticktick-integration"
    return pathlib.Path.home() / ".ticktick-integration"


DATA = data_dir()
LOG = DATA / "sync.log"
LOG_MAX = 1_000_000

# One run at a time. The Scheduled Task is MultipleInstances=IgnoreNew and so
# cannot overlap itself, but the skill starts a process of its own that can
# land mid-tick. Two runs that both see an item as absent both create it, and
# because tasks are keyed by their marker only one twin is ever seen again --
# the other is stranded in the user's own list forever, never updated, never
# completed. A skipped run costs nothing beside that: the next tick, five
# minutes later, reconciles everything.
LOCK = DATA / "sync.lock"
# Longer than any healthy run, shorter than a person's patience. A killed
# process leaves its lock behind, and with no way out the mirror would stay
# quietly dead until somebody deleted a file they do not know exists.
LOCK_STALE_SECONDS = 600


class ConfigError(Exception):
    """A bad or missing local setup -- distinct from SystemExit, which is a
    BaseException and would silently slip past main()'s `except Exception`.
    Under pythonw.exe there is no console and sync.log is the only channel
    that exists, so a credential problem MUST be catchable and logged rather
    than escaping unnoticed while the mirror quietly goes stale.
    """


def token():
    env = DATA / ".env"
    if not env.is_file():
        raise ConfigError("no .env in %s -- put the token there (TICKTICK_TOKEN=...)" % DATA)
    for line in env.read_text(encoding="utf-8").splitlines():
        # The user's file uses TICKTICK_API_KEY; accept both names rather than
        # making them re-edit a working secret to match our preference.
        if line.split("=")[0].strip() in ("TICKTICK_TOKEN", "TICKTICK_API_KEY"):
            return line.split("=", 1)[1].strip()
    raise ConfigError("no TICKTICK_TOKEN or TICKTICK_API_KEY in %s" % env)


def log(line):
    # Creates DATA if it is not there: the log is the only channel this program
    # has, so it must not be the thing that fails for want of a directory.
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > LOG_MAX:
        LOG.write_text("", encoding="utf-8")
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write("%s %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), line))


def take_lock():
    """Claim the right to run, or return None if somebody else already has it.

    O_CREAT | O_EXCL is the whole mechanism: the file is created only if it
    does not exist, and the check and the creation are one operation, so two
    processes racing for it cannot both win.
    """
    try:
        handle = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - os.path.getmtime(str(LOCK))
        except OSError:
            # It vanished between the two calls -- the holder just finished.
            # Leave it to the next tick rather than race for the gap.
            return None
        if age < LOCK_STALE_SECONDS:
            return None
        log("lock %s is %d s old -- assuming a killed run and taking it over "
            "(stale)" % (LOCK, age))
        try:
            os.unlink(str(LOCK))
            handle = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            # Somebody else got there first in the same instant. Fine: one of
            # us runs, and that is all the lock was ever for.
            return None
    os.write(handle, str(os.getpid()).encode("ascii"))
    return handle


def release_lock(handle):
    """Never raise: this runs in a `finally`, and a failure to tidy up must not
    replace whatever the run was actually reporting."""
    if handle is None:
        return  # we never held it -- above all, do not delete somebody else's
    try:
        os.close(handle)
    except OSError:
        pass
    try:
        os.unlink(str(LOCK))
    except OSError:
        pass


def _cached_token():
    """The credential is SHARED -- one TickTick account, however many repos --
    but it is read lazily, on the first repository that gets that far.

    Lazily, because a broken config must still report itself as a broken
    config: reading the token up front would turn "your config.toml is corrupt"
    into "no .env", which is a different problem in a different file.
    """
    box = {}

    def get():
        if "token" not in box:
            box["token"] = token()
        return box["token"]
    return get


def sync_one(slug, config_path, get_token, quiet):
    """One repository, start to finish. Returns True if it succeeded.

    Everything about a repo lives beside its config: its state, its
    translation cache. Nothing is shared but the credential and the log.
    """
    directory = pathlib.Path(config_path).parent
    try:
        config = github.load_config(config_path)
        desired = github.read_desired(
            config, translations_path=str(directory / "issue-descriptions.toml"))
        client = ticktick.Client(get_token())
        counts = run_sync(config, client, desired, str(directory / "state.json"))
    except Exception as error:
        # Caught per repository, on purpose: one repo whose `gh` read failed,
        # whose list was renamed or whose config is corrupt must not stop every
        # other repo from being mirrored. It is named, not swallowed -- the
        # caller still exits non-zero.
        log("%s ERROR %s: %s" % (slug, type(error).__name__, error))
        if not quiet:
            print("sync: %s: %s" % (slug, error), file=sys.stderr)
        return False

    line = "%s ok desired=%d created=%d updated=%d reopened=%d completed=%d" % (
        slug, len(desired), counts["created"], counts["updated"], counts["reopened"],
        counts["completed"])
    # `translations` cannot itself translate -- see lib/github.py --
    # so an issue whose cached English went stale (or was never cached) shows
    # up as German in the owner's own list. That must not be a silent
    # approximation: the count surfaces it here, in the one line sync.log
    # (and pythonw.exe's non-existent console) actually shows.
    untranslated = sum(1 for entry in desired.values() if entry.untranslated)
    if untranslated:
        line += " untranslated=%d" % untranslated
    log(line)
    if not quiet:
        print("sync: " + line)
    return True


def select(jobs, wanted):
    """The `--repo` filter, which fails loudly rather than doing nothing.

    A typo in a slug is the likeliest way to use the flag wrong, and "unknown
    repository" on its own leaves the user guessing at a directory name -- so
    the refusal lists what IS configured.
    """
    repos.check_slug(wanted)  # a slug from the command line is no more trusted
    chosen = [job for job in jobs if job[0] == wanted]
    if not chosen:
        raise ConfigError(
            "no repository %r is configured. Configured: %s. Run the "
            "ticktick-integration skill inside a repository to set it up."
            % (wanted, ", ".join(slug for slug, _ in jobs) or "(none)"))
    return chosen


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mirrors open work into TickTick.")
    parser.add_argument("--repo", help="sync only this repository slug (default: all)")
    parser.add_argument("--config", help="sync exactly this config file, skipping "
                                         "discovery and migration (state.json is read "
                                         "and written beside it)")
    parser.add_argument("--quiet", action="store_true", help="log only, no stdout")
    args = parser.parse_args(argv)

    # Everything that can fail sits inside the handler. Reading a config and
    # creating the data directory used to happen above it, which under
    # pythonw.exe -- no console, no stderr -- meant a corrupt config stopped the
    # mirror without leaving a single line anywhere. That is the same silence
    # the ConfigError fix closed one step further down.
    handle = None
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        handle = take_lock()
        if handle is None:
            log("skipped: another run holds the lock (%s). The next tick will "
                "reconcile." % LOCK)
            if not args.quiet:
                print("sync: skipped, another run is in progress")
            return 0

        if args.config:
            # The escape hatch: one named config, no discovery. Labelled by its
            # own directory, so the log still says which mirror a line is about.
            jobs = [(pathlib.Path(args.config).parent.name, args.config)]
        else:
            jobs = repos.discover(DATA)
            if args.repo:
                jobs = select(jobs, args.repo)

        if not jobs:
            log("no repositories configured under %s -- run the ticktick-integration "
                "skill inside a repository to set one up" % repos.repos_dir(DATA))
            if not args.quiet:
                print("sync: no repositories configured")
            return 0

        get_token = _cached_token()
        failed = [slug for slug, config_path in jobs
                  if not sync_one(slug, config_path, get_token, args.quiet)]
    except Exception as error:
        # Reached only by a failure ABOVE the per-repo loop -- the lock, the
        # data directory, an unknown --repo. A single repo's failure never
        # lands here; sync_one has already logged and counted it.
        log("ERROR %s: %s" % (type(error).__name__, error))
        if not args.quiet:
            print("sync: %s" % error, file=sys.stderr)
        return 1
    finally:
        release_lock(handle)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

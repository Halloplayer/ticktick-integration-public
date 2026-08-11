"""Entry point. Both triggers -- skill and scheduled task -- call this.

One engine, two thin triggers: what comes out by hand is exactly what the
background job does.
"""
import argparse
import datetime
import os
import pathlib
import sys
import time

from ticktick_sync import github, ticktick
from ticktick_sync.sync_core import run_sync

# Code and data live apart on purpose. HERE is the plugin folder in the cache
# -- version-scoped, and an update replaces it wholesale. Everything mutable
# therefore belongs in DATA, which survives updates.
HERE = pathlib.Path(__file__).resolve().parent


def data_dir():
    """Where the mutable state lives -- resolved without ever raising.

    This runs at import time, where there is no exception handler, no log file
    and, under pythonw.exe, no console. A bare `os.environ["LOCALAPPDATA"]`
    lookup that missed would kill the process before main() so much as exists,
    leaving nothing anywhere to say why the mirror stopped. Any answer that
    lets the run reach its own error handling beats a KeyError here.
    """
    override = os.environ.get("TICKTICK_SYNC_DATA")
    if override:
        return pathlib.Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return pathlib.Path(local) / "ticktick-sync"
    return pathlib.Path.home() / ".ticktick-sync"


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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mirrors open work into TickTick.")
    parser.add_argument("--config", default=str(HERE / "config.toml"))
    parser.add_argument("--quiet", action="store_true", help="log only, no stdout")
    args = parser.parse_args(argv)

    # Everything that can fail now sits inside the handler. Reading config.toml
    # and creating the data directory used to happen above it, which under
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

        config = github.load_config(args.config)
        desired = github.read_desired(config)
        client = ticktick.Client(token())
        counts = run_sync(config, client, desired, str(DATA / "state.json"))
    except Exception as error:
        log("ERROR %s: %s" % (type(error).__name__, error))
        if not args.quiet:
            print("sync: %s" % error, file=sys.stderr)
        return 1
    finally:
        release_lock(handle)

    line = "ok desired=%d created=%d updated=%d reopened=%d completed=%d" % (
        len(desired), counts["created"], counts["updated"], counts["reopened"], counts["completed"])
    log(line)
    if not args.quiet:
        print("sync: " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

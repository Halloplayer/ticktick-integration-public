"""Entry point. Both triggers -- skill and scheduled task -- call this.

One engine, two thin triggers: what comes out by hand is exactly what the
background job does.
"""
import argparse
import datetime
import os
import pathlib
import sys

from ticktick_sync import github, ticktick
from ticktick_sync.sync_core import run_sync

# Code and data live apart on purpose. HERE is the plugin folder in the cache
# -- version-scoped, and an update replaces it wholesale. Everything mutable
# therefore belongs in DATA, which survives updates.
HERE = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path(os.environ.get("TICKTICK_SYNC_DATA")
                    or (pathlib.Path(os.environ["LOCALAPPDATA"]) / "ticktick-sync"))
LOG = DATA / "sync.log"
LOG_MAX = 1_000_000


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
    if LOG.exists() and LOG.stat().st_size > LOG_MAX:
        LOG.write_text("", encoding="utf-8")
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write("%s %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), line))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Mirrors open work into TickTick.")
    parser.add_argument("--config", default=str(HERE / "config.toml"))
    parser.add_argument("--quiet", action="store_true", help="log only, no stdout")
    args = parser.parse_args(argv)

    DATA.mkdir(parents=True, exist_ok=True)
    config = github.load_config(args.config)
    try:
        desired = github.read_desired(config)
        client = ticktick.Client(token())
        counts = run_sync(config, client, desired, str(DATA / "state.json"))
    except Exception as error:
        log("ERROR %s: %s" % (type(error).__name__, error))
        if not args.quiet:
            print("sync: %s" % error, file=sys.stderr)
        return 1

    line = "ok desired=%d created=%d updated=%d completed=%d" % (
        len(desired), counts["created"], counts["updated"], counts["completed"])
    log(line)
    if not args.quiet:
        print("sync: " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

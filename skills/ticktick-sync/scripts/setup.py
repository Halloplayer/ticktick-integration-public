"""Setup CLI -- the deterministic half of what the skill does conversationally.

The skill (`skills/ticktick-sync/SKILL.md`) asks the questions; this does the
parts that must not be improvised: parsing a git remote into a slug, listing
the account's TickTick lists, creating one ONLY when told to in so many words,
writing `repos/<slug>/config.toml`, and dropping a neutral `open-items.toml`
into the target repository.

Every subcommand is idempotent and prints one machine-readable line per fact,
so an agent can read the result without interpreting prose.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(HERE))

import repos  # noqa: E402
import repo_setup as setup_lib  # noqa: E402
import ticktick  # noqa: E402
import sync  # noqa: E402


def _client():
    return ticktick.Client(sync.token())


def cmd_slug(args):
    slug = repos.slug_from_remote(args.remote)
    print("slug=%s" % slug)
    print("repo=%s" % repos.repo_from_slug(slug))
    configured = (repos.repo_dir(sync.DATA, slug) / "config.toml").is_file()
    print("configured=%s" % ("yes" if configured else "no"))
    return 0


def cmd_lists(args):
    for list_id, name in setup_lib.existing_lists(_client()):
        print("list\t%s\t%s" % (list_id, name))
    return 0


def cmd_ensure_list(args):
    """Resolve a list by name; create it only with an explicit --create.

    Without --create a missing list is reported, not invented: creating a list
    in somebody's personal task manager is a decision for the person, and this
    API cannot delete one again.
    """
    client = _client()
    for list_id, name in setup_lib.existing_lists(client):
        if name == args.name:
            print("list_id=%s" % list_id)
            print("created=no")
            return 0
    if not args.create:
        print("missing=%s" % args.name)
        print("Re-run with --create once the user has confirmed creating it, or "
              "create it by hand in the TickTick app.", file=sys.stderr)
        return 2
    try:
        list_id, created = setup_lib.ensure_list(client, args.name)
    except setup_lib.SetupFailed as error:
        print("setup: %s" % error, file=sys.stderr)
        return 3
    print("list_id=%s" % list_id)
    print("created=%s" % ("yes" if created else "no"))
    return 0


def cmd_init(args):
    slug = repos.slug_for(args.repo)
    path = setup_lib.write_repo_config(sync.DATA, slug, repo=args.repo,
                                       list_id=args.list_id, list_name=args.list_name,
                                       items_path=args.items_path)
    print("slug=%s" % slug)
    print("config=%s" % path)
    return 0


def cmd_open_items(args):
    path, created = setup_lib.write_open_items(args.path, args.items_path)
    print("open_items=%s" % path)
    print("created=%s" % ("yes" if created else "no"))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set one repository up for mirroring.")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("slug", help="derive the repo slug from a git remote URL")
    one.add_argument("--remote", required=True)
    one.set_defaults(run=cmd_slug)

    two = sub.add_parser("lists", help="the TickTick lists this account already has")
    two.set_defaults(run=cmd_lists)

    three = sub.add_parser("ensure-list", help="resolve a list by name, or create it")
    three.add_argument("--name", required=True)
    three.add_argument("--create", action="store_true",
                       help="create the list if it is missing -- only after the user "
                            "has explicitly confirmed it")
    three.set_defaults(run=cmd_ensure_list)

    four = sub.add_parser("init", help="write repos/<slug>/config.toml")
    four.add_argument("--repo", required=True, help="owner/repo")
    four.add_argument("--list-id", required=True)
    four.add_argument("--list-name", required=True)
    four.add_argument("--items-path", default="open-items.toml")
    four.set_defaults(run=cmd_init)

    five = sub.add_parser("open-items", help="create the neutral item list in the repo")
    five.add_argument("--path", required=True, help="the target repository's working copy")
    five.add_argument("--items-path", default="open-items.toml")
    five.set_defaults(run=cmd_open_items)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (repos.SlugError, setup_lib.SetupFailed, sync.ConfigError,
            ticktick.TickTickError) as error:
        print("setup: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

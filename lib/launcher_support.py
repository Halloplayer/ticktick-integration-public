"""Version resolution for the scheduled-task launcher.

Extracted out of the generated launcher.pyw so the numeric-vs-lexical
version comparison is testable by import instead of only living inside a
generated file: "0.10.0" must beat "0.9.0" numerically, but the old
PowerShell launcher picked the newest version with
`Sort-Object Name -Descending`, a lexical (string) sort that gets this
backwards -- "0.9.0" sorts after "0.10.0" as text.
"""
import pathlib


def newest_version_dir(root):
    """Return the numerically-newest version directory under `root`.

    `root` holds one subdirectory per cached plugin version (e.g. "0.9.0",
    "0.10.0", ...). Each directory name is parsed into a tuple of ints and
    compared numerically, never as a string.
    """
    root = pathlib.Path(root)
    versions = [p for p in root.iterdir() if p.is_dir()]
    if not versions:
        raise SystemExit("no cached ticktick-integration version under %s" % root)
    return max(versions, key=lambda p: tuple(int(n) for n in p.name.split(".") if n.isdigit()))

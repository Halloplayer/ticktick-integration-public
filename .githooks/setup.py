#!/usr/bin/env python3
"""One-time hook bootstrap -- run once per clone:  python .githooks/setup.py

git does not version `core.hooksPath`, so a fresh clone must point git at the
committed `.githooks/` dir. This sets that (repo-local) config and makes the
hooks executable. Idempotent -- safe to re-run.
"""
from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

# The check marks below must never be what makes this fail. By the time the
# final line prints, core.hooksPath is already written -- a crash here reports
# failure for work that succeeded, and the developer concludes the hooks are
# not installed. Only the error handler changes, not the encoding: forcing
# UTF-8 onto a cp1252 console swaps a crash for mojibake.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="backslashreplace")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    if not top:
        sys.exit("x not inside a git repository")
    root = Path(top)

    _git(root, "config", "core.hooksPath", ".githooks")
    for f in (root / ".githooks").iterdir():
        if f.is_file():
            f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"ok core.hooksPath = {_git(root, 'config', 'core.hooksPath')} "
          "-- hooks in .githooks/ are active")


if __name__ == "__main__":
    main()

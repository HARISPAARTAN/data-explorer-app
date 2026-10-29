"""Copy src/data_explorer/ to web/py/data_explorer/ for the stlite page; --check compares them.

The browser fetches the files that web/index.html lists from web/py/. The command line (cli.py,
__main__.py) is not mounted there, so it is not copied; neither are __pycache__ folders.

Usage:
    uv run python tools/sync_web.py            copy
    uv run python tools/sync_web.py --check    exit 1 when web/py differs from src
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "data_explorer"
TARGET = ROOT / "web" / "py" / "data_explorer"
NOT_MOUNTED = frozenset({"cli.py", "__main__.py"})
CACHE_PARTS = frozenset({"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})


def _files(folder: Path) -> dict[str, bytes]:
    if not folder.is_dir():
        return {}
    found: dict[str, bytes] = {}
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if not path.is_file() or CACHE_PARTS.intersection(relative.parts) or path.suffix == ".pyc":
            continue
        found[relative.as_posix()] = path.read_bytes()
    return found


def wanted(source: Path) -> dict[str, bytes]:
    """The files the browser needs: the package without the command line and without caches."""
    return {name: data for name, data in _files(source).items() if name not in NOT_MOUNTED}


def present(target: Path) -> dict[str, bytes]:
    return _files(target)


def differences(source: Path, target: Path) -> list[str]:
    expected, actual = wanted(source), present(target)
    problems = [f"missing in web/py: {name}" for name in sorted(expected.keys() - actual.keys())]
    problems += [f"not in src: {name}" for name in sorted(actual.keys() - expected.keys())]
    problems += [
        f"differs: {name}"
        for name in sorted(expected.keys() & actual.keys())
        if expected[name] != actual[name]
    ]
    return problems


def sync(source: Path, target: Path) -> int:
    files = wanted(source)
    if target.exists():
        shutil.rmtree(target)
    for name, data in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return len(files)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy the package into web/py for the stlite page.")
    parser.add_argument("--check", action="store_true", help="compare only; exit 1 on any difference")
    args = parser.parse_args(argv)
    source, target = SOURCE, TARGET
    if args.check:
        problems = differences(source, target)
        for problem in problems:
            print(f"sync_web: {problem}")
        if problems:
            print("sync_web: run `uv run python tools/sync_web.py` and commit web/py")
            return 1
        print(f"sync_web: web/py matches src ({len(wanted(source))} files)")
        return 0
    count = sync(source, target)
    print(f"sync_web: copied {count} files into web/py/data_explorer")
    return 0


if __name__ == "__main__":
    sys.exit(main())

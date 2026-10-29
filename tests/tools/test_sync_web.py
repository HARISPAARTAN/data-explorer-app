"""tools/sync_web.py copies the package for the browser and reports every difference."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture(scope="module")
def sync_web(tool: Callable[[str], ModuleType]) -> ModuleType:
    return tool("tools/sync_web.py")


def make_source(root: Path) -> Path:
    source = root / "src" / "data_explorer"
    files = {
        "__init__.py": "x = 1\n",
        "cli.py": "cli\n",
        "__main__.py": "main\n",
        "core/x.py": "y = 2\n",
        "core/__pycache__/x.cpython-312.pyc": "cache",
        "samples/a.csv": "a;b\n1;2\n",
    }
    for name, text in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return source


def test_wanted_leaves_out_the_cli_and_caches(sync_web: ModuleType, tmp_path: Path) -> None:
    assert sorted(sync_web.wanted(make_source(tmp_path))) == ["__init__.py", "core/x.py", "samples/a.csv"]


def test_sync_then_every_kind_of_difference(sync_web: ModuleType, tmp_path: Path) -> None:
    source, target = make_source(tmp_path), tmp_path / "web" / "py" / "data_explorer"
    assert sync_web.sync(source, target) == 3
    assert sync_web.differences(source, target) == []
    (target / "core" / "x.py").write_bytes(b"y = 3\n")
    (target / "extra.py").write_bytes(b"")
    (target / "samples" / "a.csv").unlink()
    assert sync_web.differences(source, target) == [
        "missing in web/py: samples/a.csv",
        "not in src: extra.py",
        "differs: core/x.py",
    ]


def test_sync_removes_stale_files(sync_web: ModuleType, tmp_path: Path) -> None:
    source, target = make_source(tmp_path), tmp_path / "target"
    (target / "old").mkdir(parents=True)
    (target / "old" / "gone.py").write_bytes(b"")
    sync_web.sync(source, target)
    assert sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()) == [
        "__init__.py",
        "core/x.py",
        "samples/a.csv",
    ]


def test_main_exit_codes(
    sync_web: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source, target = make_source(tmp_path), tmp_path / "copy"
    monkeypatch.setattr(sync_web, "SOURCE", source)
    monkeypatch.setattr(sync_web, "TARGET", target)
    assert sync_web.main(["--check"]) == 1
    assert "missing in web/py: __init__.py" in capsys.readouterr().out
    assert sync_web.main([]) == 0
    assert sync_web.main(["--check"]) == 0
    assert "matches" in capsys.readouterr().out


def test_repository_copy_is_current(sync_web: ModuleType) -> None:
    assert sync_web.differences(sync_web.SOURCE, sync_web.TARGET) == []

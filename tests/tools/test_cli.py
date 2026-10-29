"""Command line: version, the Streamlit command, exit codes and the samples copy."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from data_explorer import cli
from data_explorer.core.io import SAMPLES


def test_version() -> None:
    result = CliRunner().invoke(cli.main, ["--version"])
    assert result.exit_code == 0 and result.output == "data-explorer-app 0.1.0\n"


def test_module_entry_point() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "data_explorer", "--version"], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0 and done.stdout == "data-explorer-app 0.1.0\n"


def test_run_dry_run_prints_the_command() -> None:
    result = CliRunner().invoke(cli.main, ["run", "--host", "0.0.0.0", "--port", "8600", "--dry-run"])
    assert result.exit_code == 0
    command = shlex.split(result.output)
    assert command[:5] == [sys.executable, "-m", "streamlit", "run", str(cli.APP)]
    assert command[5:8] == ["--server.address=0.0.0.0", "--server.port=8600", "--server.headless=true"]
    assert tuple(command[8:]) == cli.CONFIG_FLAGS
    assert cli.APP.is_file() and cli.APP.name == "streamlit_app.py"


def test_run_defaults() -> None:
    assert cli.streamlit_command("127.0.0.1", 8501)[5:7] == [
        "--server.address=127.0.0.1",
        "--server.port=8501",
    ]


@pytest.mark.parametrize("code", [0, 3])
def test_run_passes_the_streamlit_exit_code(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    calls: list[list[str]] = []

    class FakeProcess:
        def __init__(self, command: list[str]) -> None:
            calls.append(command)

        def wait(self) -> int:
            return code

    monkeypatch.setattr(cli.subprocess, "Popen", FakeProcess)
    result = CliRunner().invoke(cli.main, ["run"])
    assert result.exit_code == code
    assert calls == [cli.streamlit_command("127.0.0.1", 8501)]


def test_run_reports_a_missing_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(command: list[str]) -> None:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(cli.subprocess, "Popen", fail)
    result = CliRunner().invoke(cli.main, ["run"])
    assert result.exit_code == 1 and "Could not start Streamlit" in result.output


@pytest.mark.parametrize("args", [["run", "--port", "0"], ["run", "--port", "x"], ["samples"], ["nope"]])
def test_usage_errors(args: list[str]) -> None:
    assert CliRunner().invoke(cli.main, args).exit_code == 2


def test_sample_files_match_core() -> None:
    assert list(cli.SAMPLE_FILES) == [info.file_name for info in SAMPLES.values()]


def test_samples_into_a_new_folder(tmp_path: Path) -> None:
    out = tmp_path / "new" / "samples"
    result = CliRunner().invoke(cli.main, ["samples", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in out.iterdir()) == sorted(cli.SAMPLE_FILES)
    for name in cli.SAMPLE_FILES:
        assert (out / name).read_bytes() == (cli.SAMPLES_DIR / name).read_bytes()


def test_samples_into_an_empty_folder(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli.main, ["samples", "--out", str(tmp_path)])
    assert result.exit_code == 0 and len(list(tmp_path.iterdir())) == 3


def test_samples_refuse_a_folder_with_files(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")
    result = CliRunner().invoke(cli.main, ["samples", "--out", str(tmp_path)])
    assert result.exit_code == 1 and "is not an empty folder" in result.output
    assert [path.name for path in tmp_path.iterdir()] == ["keep.txt"]


def test_samples_refuse_a_file(tmp_path: Path) -> None:
    target = tmp_path / "file.csv"
    target.write_text("x", encoding="utf-8")
    result = CliRunner().invoke(cli.main, ["samples", "--out", str(target)])
    assert result.exit_code == 1 and "is not an empty folder" in result.output


def test_samples_report_a_folder_that_cannot_be_created(tmp_path: Path) -> None:
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    result = CliRunner().invoke(cli.main, ["samples", "--out", str(blocker / "sub")])
    assert result.exit_code == 1
    assert "Error: Could not write the samples: " in result.output
    assert "Traceback" not in result.output and result.exception is not None
    assert isinstance(result.exception, SystemExit)
    assert blocker.read_text(encoding="utf-8") == "x"


def test_samples_report_an_unreadable_existing_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path) -> None:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "iterdir", refuse)
    result = CliRunner().invoke(cli.main, ["samples", "--out", str(tmp_path)])
    assert result.exit_code == 1
    assert "Error: Could not write the samples: " in result.output and "Permission denied" in result.output
    assert "Traceback" not in result.output and isinstance(result.exception, SystemExit)

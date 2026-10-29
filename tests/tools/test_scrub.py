"""tools/checks/scrub.py finds hashed terms, local patterns and commit messages, and passes here."""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

LOCAL_PATTERNS = "\n".join(
    [
        "# a comment line",
        r"\bsecretcorp\b",
        r"[a-z0-9._%+-]+@(?!example\.(?:org|com)\b)[a-z0-9.-]+\.[a-z]{2,}",
    ]
)


@pytest.fixture(scope="module")
def scrub(tool: Callable[[str], ModuleType]) -> ModuleType:
    return tool("tools/checks/scrub.py")


@pytest.fixture
def harmless(scrub: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    terms = {
        scrub.digest("zebra"): "test name",
        scrub.digest("blue-green"): "test compound",
        scrub.digest("paper boat"): "test pair",
    }
    monkeypatch.setattr(scrub, "HASHED_TERMS", terms)


def git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_digest_is_case_folded(scrub: ModuleType) -> None:
    assert scrub.digest("Zebra") == scrub.digest("zebra") == hashlib.sha256(b"zebra").hexdigest()
    assert len(scrub.HASHED_TERMS) == 10


@pytest.mark.usefixtures("harmless")
@pytest.mark.parametrize(
    "line",
    [
        "A Zebra here.",
        "the ZEBRA-crossing",
        "myZebraHelper",
        "blue-green tones",
        "a Paper boat",
        "paper" + chr(0xA0) + "boat",
        "Zebra&#39;s",
    ],
)
def test_terms_are_found(scrub: ModuleType, line: str) -> None:
    hits = scrub.scan_text(line, "x.md", [])
    assert len(hits) == 1
    assert (hits[0].where, hits[0].line) == ("x.md", 1)
    assert "zebra" not in str(hits[0]).lower() and hits[0].text.endswith("****")


@pytest.mark.usefixtures("harmless")
def test_innocent_words_pass(scrub: ModuleType) -> None:
    assert scrub.scan_text("zebras and paperboats, blue or green", "x.md", []) == []


def test_local_patterns_and_the_allowlist(scrub: ModuleType, tmp_path: Path) -> None:
    banned = tmp_path / "banned.txt"
    banned.write_text(LOCAL_PATTERNS + "\n", encoding="utf-8")
    patterns = scrub.load_patterns(banned)
    assert len(patterns) == 2
    (allowed,) = scrub.ALLOWED
    address = "someone" + "@mail.test"  # split so that this file itself holds no address
    text = f"Write to {allowed} or {address}.\nSecretCorp Ltd.\nci@example.org\n"
    hits = scrub.scan_text(text, "x.md", patterns)
    assert [(hit.line, hit.text) for hit in hits] == [(1, address), (2, "SecretCorp")]


def test_the_system_font_stack_is_masked(scrub: ModuleType) -> None:
    patterns = [("system", re.compile(r"\bsystem\b", re.IGNORECASE))]
    assert scrub.scan_text("font-family: Inter, -apple-system, sans-serif;", "x.css", patterns) == []
    assert len(scrub.scan_text("a system font", "x.md", patterns)) == 1


def test_binary_files_are_skipped_and_commit_messages_scanned(
    scrub: ModuleType, harmless: None, tmp_path: Path
) -> None:
    git("init", "-q", "-b", "main", cwd=tmp_path)
    (tmp_path / "notes.md").write_text("all clear\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00zebra")
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("zebra\n", encoding="utf-8")
    git("add", "notes.md", "image.png", ".gitignore", cwd=tmp_path)
    git("commit", "-q", "-m", "docs: add a zebra", cwd=tmp_path)
    (tmp_path / "draft.txt").write_text("a zebra\n", encoding="utf-8")
    hits, files, messages = scrub.scan(tmp_path, [])
    assert (files, messages) == (3, 1)
    assert [hit.where for hit in hits if not hit.where.startswith("commit ")] == ["draft.txt"]
    assert len([hit for hit in hits if hit.where.startswith("commit ")]) == 1


def test_main_exit_codes(
    scrub: ModuleType, harmless: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git("init", "-q", "-b", "main", cwd=tmp_path)
    (tmp_path / "fine.md").write_text("fine\n", encoding="utf-8")
    git("add", "fine.md", cwd=tmp_path)
    git("commit", "-q", "-m", "chore: start", cwd=tmp_path)
    assert scrub.main(["--root", str(tmp_path)]) == 0
    assert "CLEAN" in capsys.readouterr().out
    (tmp_path / "x.md").write_text("zebra\n", encoding="utf-8")
    assert scrub.main(["--root", str(tmp_path)]) == 1
    assert scrub.main(["--root", str(tmp_path), "--banned-file", str(tmp_path / "missing.txt")]) == 2


def test_this_repository_is_clean(scrub: ModuleType) -> None:
    hits, files, messages = scrub.scan(scrub.ROOT, [])
    assert [str(hit) for hit in hits] == []
    assert files > 50 and messages > 0

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
        "Ze&#98;ra",  # only the entity-resolved text spells the term
        "paper&nbsp;boat",  # a named entity that resolves to the no-break space between the pair
    ],
)
def test_terms_are_found(scrub: ModuleType, line: str) -> None:
    hits = scrub.scan_text(line, "x.md", [])
    assert len(hits) == 1
    assert (hits[0].where, hits[0].line) == ("x.md", 1)
    assert "zebra" not in str(hits[0]).lower() and hits[0].text.endswith("****")


@pytest.mark.usefixtures("harmless")
def test_entities_are_resolved_before_the_words_are_split(scrub: ModuleType) -> None:
    for line in ("Ze&#98;ra", "paper&nbsp;boat", "Ze&#x62;ra"):
        assert scrub.scan_text("fine\n" + line, "x.md", []) != []
    assert scrub.scan_text("Ze&#98;r and zebras and paper&nbsp;boats", "x.md", []) == []


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
    assert [(hit.line, hit.rule, hit.text) for hit in hits] == [
        (1, "local pattern #2", "s****"),
        (2, "local pattern #1", "S****"),
    ]
    printed = "\n".join(str(hit) for hit in hits)
    assert address not in printed and "secretcorp" not in printed.lower() and "[a-z0-9" not in printed


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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one clean commit; ``tmp_path`` itself stays free for banned files."""
    root = tmp_path / "repo"
    root.mkdir()
    git("init", "-q", "-b", "main", cwd=root)
    (root / "fine.md").write_text("fine\n", encoding="utf-8")
    git("add", "fine.md", cwd=root)
    git("commit", "-q", "-m", "chore: start", cwd=root)
    return root


def test_hits_print_as_file_line_rule_and_masked_term(
    scrub: ModuleType, harmless: None, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "docs").mkdir()
    (repo / "docs" / "x.md").write_text("fine\nthe zebra\n", encoding="utf-8")
    assert scrub.main(["--root", str(repo)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "docs/x.md:2: test name: z****"
    assert lines[-1].endswith(": 1 HITS")


def test_path_names_are_scanned_as_line_zero_and_printed_masked(
    scrub: ModuleType, harmless: None, repo: Path
) -> None:
    (repo / "zebra-notes.md").write_text("fine\n", encoding="utf-8")  # untracked
    (repo / "paper").mkdir()
    (repo / "paper" / "boat.md").write_text("fine\n", encoding="utf-8")  # tracked, a pair across folders
    git("add", "paper", cwd=repo)
    (repo / "Ze&#98;ra.txt").write_text("a zebra\n", encoding="utf-8")  # the name needs entity decoding
    hits, files, _ = scrub.scan(repo, [])
    assert files == 4
    assert {(hit.where, hit.line) for hit in hits} == {("z****", 0), ("p****", 0), ("Z****", 0), ("Z****", 1)}
    printed = "\n".join(str(hit) for hit in hits).lower()
    assert "zebra" not in printed and "paper" not in printed and "boat" not in printed
    patterns = [("secret", re.compile(r"secretcorp", re.IGNORECASE))]
    (hit,) = scrub.scan_name("docs/SecretCorp-plan.md", patterns)
    assert (hit.where, hit.line, hit.rule, hit.text) == ("docs/S****", 0, "local pattern #1", "S****")
    assert scrub.scan_name("docs/plan.md", patterns) == []


def test_every_branch_and_annotated_tag_message_is_scanned(
    scrub: ModuleType, harmless: None, repo: Path
) -> None:
    git("checkout", "-q", "-b", "side", cwd=repo)
    git("commit", "-q", "--allow-empty", "-m", "docs: a zebra", cwd=repo)
    git("checkout", "-q", "main", cwd=repo)
    git("tag", "-a", "v1", "-m", "release with a paper boat", cwd=repo)
    git("tag", "light", cwd=repo)  # a lightweight tag has no message of its own
    hits, _, messages = scrub.scan(repo, [])
    assert messages == 3  # the start commit, the commit only the side branch reaches, the annotated tag
    assert sorted(hit.where.split()[0] for hit in hits) == ["commit", "tag"]
    assert all(hit.line == 1 and hit.text.endswith("****") for hit in hits)
    hits, _, messages = scrub.scan(repo, [], history=False)
    assert (hits, messages) == ([], 0)


def test_no_history_skips_commit_and_tag_messages(
    scrub: ModuleType, harmless: None, repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git("commit", "-q", "--allow-empty", "-m", "docs: a zebra", cwd=repo)
    assert scrub.main(["--root", str(repo)]) == 1
    capsys.readouterr()
    assert scrub.main(["--root", str(repo), "--no-history"]) == 0
    assert "0 commit and tag messages" in capsys.readouterr().out


def test_local_pattern_hits_name_the_pattern_but_not_its_source_or_text(
    scrub: ModuleType, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    banned = tmp_path / "banned.txt"
    # a byte order mark and CRLF line ends, as an editor on Windows may write them
    banned.write_bytes(b"\xef\xbb\xbf# a comment\r\n\r\n   \r\n" + rb"\bsecretcorp\b" + b"\r\n")
    (repo / "x.md").write_text("fine\nSecretCorp Ltd.\n", encoding="utf-8")
    assert scrub.main(["--root", str(repo), "--banned-file", str(banned)]) == 1
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "x.md:2: local pattern #1: S****"
    assert "secretcorp" not in out.lower() and "\\b" not in out and "1 local patterns" in out


def test_a_byte_order_mark_does_not_break_the_first_pattern(scrub: ModuleType, tmp_path: Path) -> None:
    banned = tmp_path / "banned.txt"
    banned.write_bytes(b"\xef\xbb\xbf" + rb"\bsecretcorp\b" + b"\n")
    ((source, pattern),) = scrub.load_patterns(banned)
    assert source == r"\bsecretcorp\b" and pattern.search("SecretCorp")


def test_an_invalid_pattern_is_a_usage_error_without_a_traceback(
    scrub: ModuleType, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    banned = tmp_path / "banned.txt"
    banned.write_text("fine\n(unclosed\n", encoding="utf-8")
    assert scrub.main(["--root", str(repo), "--banned-file", str(banned)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "banned file" in captured.err and "line 2" in captured.err
    assert "(unclosed" not in captured.err and "Traceback" not in captured.err


def test_a_banned_file_that_is_not_utf8_is_a_usage_error_without_a_traceback(
    scrub: ModuleType, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    banned = tmp_path / "banned.txt"
    banned.write_bytes("secretcorp".encode("utf-16"))  # what PowerShell's redirection writes
    assert scrub.main(["--root", str(repo), "--banned-file", str(banned)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "UTF-8" in captured.err and "Traceback" not in captured.err


@pytest.mark.parametrize(
    "content", [b"secretcorp\x00", b"# note\n\x00secretcorp\n", "secretcorp".encode("utf-16-le")]
)
def test_a_banned_file_with_nul_bytes_is_not_utf8_text(
    scrub: ModuleType, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes
) -> None:
    """UTF-16 without a byte order mark decodes as UTF-8 with NUL bytes between the letters."""
    banned = tmp_path / "banned.txt"
    banned.write_bytes(content)
    assert scrub.main(["--root", str(repo), "--banned-file", str(banned)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "not UTF-8 text" in captured.err and "Traceback" not in captured.err
    assert "secretcorp" not in captured.err


def test_a_root_that_is_not_a_repository_is_a_usage_error(
    scrub: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert scrub.main(["--root", str(plain)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "git repository" in captured.err and "Traceback" not in captured.err


def test_this_repository_is_clean(scrub: ModuleType) -> None:
    hits, files, messages = scrub.scan(scrub.ROOT, [])
    assert [str(hit) for hit in hits] == []
    assert files > 50 and messages > 0

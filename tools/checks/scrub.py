"""Scan the repository for banned names and terms (docs/handover.md, "Checks").

The terms every demo repository bans are stored as SHA-256 hashes of their case-folded form, so this
file does not contain them: the assistant and AI tool names, one banned name and the spellings of a
claim about how code was typed. Each line is split into words; words, hyphenated compounds and their
parts, camel-case parts and pairs of neighbouring words are hashed and compared. A never-committed
list of regular expressions (one per line, UTF-8 with or without a BOM, case-insensitive, ``#`` starts a
comment) is added with ``--banned-file``; matches on the allowlist are accepted, and the system font
stack ``-apple-system`` of the kit's CSS is masked before those patterns run.

Scanned: the name of every tracked or untracked, not ignored path (reported as line 0), the text of every
such file without NUL bytes (``git ls-files``), both as written and with HTML entities resolved, and
every commit message of every branch and tag (``git log --all``) and every annotated tag message.
``uv.lock`` is checked against the hashed terms only, because its hashes and sizes are random digits
that short numeric patterns can match.

Nothing a hit prints can be searched for: a matched term shows as its first character and ``****``, a
local pattern as ``local pattern #N`` (its position in the banned file, comments not counted), and a
path that hits is shown with the offending components masked.

Usage (from the repository root):
    uv run python tools/checks/scrub.py [--banned-file PATH] [--no-history] [--root PATH]
Exit codes: 0 clean, 1 hits, 2 the banned file cannot be read or compiled, or the root is not a git
repository.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_NAME = "assistant or AI tool name"
TYPING_CLAIM = "claim about how the code was typed"
HASHED_TERMS: dict[str, str] = {
    "c857d09db23e6822e3600bc06ad8d58f92ed62bc8efd81c753f77048662cb97d": TOOL_NAME,
    "c70eca6b0f88f44d81a41311647e50fda1ac454ec04ffd442b0eb4743a993131": TOOL_NAME,
    "60965168ce762e949600281ba6d01fee136e5b6e8257b1f216f9025ed324474c": TOOL_NAME,
    "7d3194f79e645c42e4396dda38be04766810ec6a00d00aced3ffc2a0a1f1a9ef": TOOL_NAME,
    "3ea125d0bff386e6754b3782b300016fc79a9cf8f8669c0a5c3db64467ddb681": TOOL_NAME,
    "5d72436256ada53828b51895a94bb8489e9f1ac4fe937a8024ef1594e7045ff6": TOOL_NAME,
    "683ec9b4c215b8391f2749b55d645adcea53cf5c571a28d923a18078927d1097": "banned name",
    "81007f7b79c7fec4d2f0dc38aabb461ed699bb998a4e4a72af0f6cc1ce49ee6e": TYPING_CLAIM,
    "7df7f6ff005c12f2c11cb3d81767ba673eec86c8dbc976542fdd04e0307e8530": TYPING_CLAIM,
    "80e1a78b46b54129577efb92008bef5eccf70451b799aa2594e585bd00165be5": TYPING_CLAIM,
}
ALLOWED = frozenset({"data-team@meridian.example"})
HASHED_ONLY = frozenset({"uv.lock"})
WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
HEX_RUN = re.compile(r"\b[0-9A-Fa-f]{32,}\b")
ALLOWED_SPANS = re.compile(r"-apple-system\b", re.IGNORECASE)
NBSP = chr(0xA0)

Patterns = Sequence[tuple[str, re.Pattern[str]]]


@dataclass(frozen=True)
class Hit:
    where: str
    line: int
    rule: str
    text: str

    def __str__(self) -> str:
        return f"{self.where}:{self.line}: {self.rule}: {self.text}"


def digest(term: str) -> str:
    return hashlib.sha256(term.casefold().encode("utf-8")).hexdigest()


def _masked(term: str) -> str:
    return term[:1] + "****"


def candidates(line: str) -> Iterator[str]:
    """Words, hyphenated compounds and their parts, camel-case parts and neighbouring word pairs."""
    words = WORD.findall(line)
    for index, word in enumerate(words):
        yield word
        parts = word.split("-")
        if len(parts) > 1:
            yield from parts
        for part in parts:
            pieces = CAMEL.findall(part)
            if len(pieces) > 1:
                yield from pieces
        if index + 1 < len(words):
            yield f"{word} {words[index + 1]}"


def _variants(text: str) -> list[str]:
    plain = text.replace(NBSP, " ")
    resolved = html.unescape(plain).replace(NBSP, " ")
    return [plain] if resolved == plain else [plain, resolved]


def _line_hits(line: str, patterns: Patterns) -> set[tuple[str, str]]:
    """The (rule, masked match) pairs of one line: hashed terms first, then the local patterns."""
    found: set[tuple[str, str]] = set()
    for term in candidates(line):
        rule = HASHED_TERMS.get(digest(term))
        if rule is not None:
            found.add((rule, _masked(term)))
    masked_line = ALLOWED_SPANS.sub(" ", HEX_RUN.sub("<hex>", line))
    for index, (_, pattern) in enumerate(patterns, start=1):
        for match in pattern.finditer(masked_line):
            if match.group(0) not in ALLOWED:
                found.add((f"local pattern #{index}", _masked(match.group(0))))
    return found


def scan_text(text: str, where: str, patterns: Patterns) -> list[Hit]:
    hits: set[Hit] = set()
    for variant in _variants(text):
        for number, line in enumerate(variant.splitlines(), start=1):
            hits.update(Hit(where, number, rule, shown) for rule, shown in _line_hits(line, patterns))
    return sorted(hits, key=lambda hit: (hit.where, hit.line, hit.rule, hit.text))


def _name_hits(name: str, patterns: Patterns) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for variant in _variants(name):
        found |= _line_hits(variant.replace("\r", " ").replace("\n", " "), patterns)
    return found


def scan_name(name: str, patterns: Patterns) -> list[Hit]:
    """Hits in a path name, reported as line 0 under a name that is masked where it hits."""
    found = _name_hits(name, patterns)
    if not found:
        return []
    parts = name.split("/")
    shown = [_masked(part) if _name_hits(part, patterns) else part for part in parts]
    where = "/".join(shown) if shown != parts else _masked(name)  # else: a pair across components
    return [Hit(where, 0, rule, text) for rule, text in sorted(found)]


class NotUtf8Text(ValueError):
    """The banned file decodes as UTF-8 but holds NUL bytes (UTF-16 without a BOM does)."""


def load_patterns(path: Path | None) -> list[tuple[str, re.Pattern[str]]]:
    """The patterns of a banned file (UTF-8, a BOM is dropped); an invalid one is a ``re.error`` that
    names its line but does not repeat it, and a file with NUL bytes is not text (``NotUtf8Text``)."""
    if path is None:
        return []
    patterns: list[tuple[str, re.Pattern[str]]] = []
    text = path.read_text(encoding="utf-8-sig")
    if "\0" in text:
        raise NotUtf8Text("a NUL byte")
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip() and not line.startswith("#"):
            try:
                patterns.append((line, re.compile(line, re.IGNORECASE)))
            except re.error as exc:
                raise re.error(f"line {number} is not a valid regular expression ({exc.msg})") from None
    return patterns


def repository_names(root: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", errors="replace")
    return sorted({name for name in listed.split("\0") if name})


def repository_files(root: Path) -> list[Path]:
    return [root / name for name in repository_names(root) if (root / name).is_file()]


def _records(stdout: bytes, field_count: int) -> list[list[str]]:
    """Split ``\\x1e``-terminated records of NUL-separated fields (the last field may hold newlines)."""
    records: list[list[str]] = []
    for record in stdout.decode("utf-8", errors="replace").split("\x1e"):
        fields = record.lstrip("\n").split("\0", field_count - 1)
        if len(fields) == field_count:
            records.append(fields)
    return records


def commit_messages(root: Path) -> list[tuple[str, str]]:
    """Every commit reachable from any branch, tag or other ref."""
    done = subprocess.run(
        ["git", "-C", str(root), "log", "--all", "--format=%H%x00%B%x1e"], capture_output=True, check=True
    )
    return [(sha[:12], message) for sha, message in _records(done.stdout, 2)]


def tag_messages(root: Path) -> list[tuple[str, str]]:
    """The messages of annotated tags (a lightweight tag has none of its own)."""
    done = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "for-each-ref",
            "--format=%(objecttype)%00%(objectname)%00%(contents)%1e",
            "refs/tags",
        ],
        capture_output=True,
        check=True,
    )
    return [(sha[:12], message) for kind, sha, message in _records(done.stdout, 3) if kind == "tag"]


def scan(root: Path, patterns: Patterns, history: bool = True) -> tuple[list[Hit], int, int]:
    """Hits, the number of files read as text and the number of commit and tag messages read."""
    hits: list[Hit] = []
    scanned = 0
    for name in repository_names(root):
        name_hits = scan_name(name, patterns)
        hits += name_hits
        where = name_hits[0].where if name_hits else name
        path = root / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        scanned += 1
        hits += scan_text(
            data.decode("utf-8", errors="replace"), where, [] if name in HASHED_ONLY else patterns
        )
    messages = (
        [("commit", sha, text) for sha, text in commit_messages(root)]
        + [("tag", sha, text) for sha, text in tag_messages(root)]
        if history
        else []
    )
    for kind, sha, message in messages:
        hits += scan_text(message, f"{kind} {sha}", patterns)
    return hits, scanned, len(messages)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan path names, files and commit and tag messages for banned names and terms."
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="repository to scan (default: this one)")
    parser.add_argument("--banned-file", type=Path, help="never-committed regular expressions, one per line")
    parser.add_argument("--no-history", action="store_true", help="skip the commit and tag messages")
    args = parser.parse_args(argv)
    try:
        patterns = load_patterns(args.banned_file)
    except (UnicodeDecodeError, NotUtf8Text):
        print("scrub: cannot use the banned file: it is not UTF-8 text", file=sys.stderr)
        return 2
    except (OSError, ValueError, re.error) as exc:
        print(f"scrub: cannot use the banned file: {exc}", file=sys.stderr)
        return 2
    try:
        hits, files, messages = scan(args.root, patterns, history=not args.no_history)
    except subprocess.CalledProcessError as exc:
        print(
            f"scrub: git failed in {args.root} (exit {exc.returncode}): is it a git repository?",
            file=sys.stderr,
        )
        return 2
    for hit in hits:
        print(hit)
    local = f" and {len(patterns)} local patterns" if patterns else ""
    verdict = "CLEAN" if not hits else f"{len(hits)} HITS"
    print(
        f"scrub: {files} files and {messages} commit and tag messages, {len(HASHED_TERMS)} committed terms{local}: {verdict}"
    )
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())

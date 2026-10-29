"""Scan the repository for banned names and terms (docs/handover.md, "Checks").

The terms every demo repository bans are stored as SHA-256 hashes of their case-folded form, so this
file does not contain them: the assistant and AI tool names, one banned name and the spellings of a
claim about how code was typed. Each line is split into words; words, hyphenated compounds and their
parts, camel-case parts and pairs of neighbouring words are hashed and compared. A never-committed
list of regular expressions (one per line, case-insensitive, ``#`` starts a comment) is added with
``--banned-file``; matches on the allowlist are accepted, and the system font stack ``-apple-system`` of
the kit's CSS is masked before those patterns run.

Scanned: every tracked or untracked, not ignored file without NUL bytes (``git ls-files``), as text and
with HTML entities resolved, and every commit message. ``uv.lock`` is checked against the hashed terms
only, because its hashes and sizes are random digits that short numeric patterns can match.

Usage (from the repository root):
    uv run python tools/checks/scrub.py [--banned-file PATH] [--no-history] [--root PATH]
Exit codes: 0 clean, 1 hits, 2 the banned file cannot be read or compiled.
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
    return term[0] + "*" * (len(term) - 1)


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


def scan_text(text: str, where: str, patterns: Patterns) -> list[Hit]:
    hits: set[Hit] = set()
    for variant in _variants(text):
        for number, line in enumerate(variant.splitlines(), start=1):
            for term in candidates(line):
                rule = HASHED_TERMS.get(digest(term))
                if rule is not None:
                    hits.add(Hit(where, number, rule, _masked(term)))
            masked_line = ALLOWED_SPANS.sub(" ", HEX_RUN.sub("<hex>", line))
            for source, pattern in patterns:
                for match in pattern.finditer(masked_line):
                    if match.group(0) not in ALLOWED:
                        hits.add(Hit(where, number, f"local pattern {source!r}", match.group(0)))
    return sorted(hits, key=lambda hit: (hit.where, hit.line, hit.rule, hit.text))


def load_patterns(path: Path | None) -> list[tuple[str, re.Pattern[str]]]:
    if path is None:
        return []
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            patterns.append((line, re.compile(line, re.IGNORECASE)))
    return patterns


def repository_files(root: Path) -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    names = sorted({name for name in listed.split("\0") if name})
    return [root / name for name in names if (root / name).is_file()]


def commit_messages(root: Path) -> list[tuple[str, str]]:
    done = subprocess.run(
        ["git", "-C", str(root), "log", "--format=%H%x00%B%x1e"], capture_output=True, check=False
    )
    if done.returncode != 0:  # no commits yet
        return []
    messages: list[tuple[str, str]] = []
    for record in done.stdout.decode("utf-8", errors="replace").split("\x1e"):
        record = record.lstrip("\n")
        if "\0" in record:
            sha, message = record.split("\0", 1)
            messages.append((sha[:12], message))
    return messages


def scan(root: Path, patterns: Patterns, history: bool = True) -> tuple[list[Hit], int, int]:
    hits: list[Hit] = []
    scanned = 0
    for path in repository_files(root):
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        scanned += 1
        name = path.relative_to(root).as_posix()
        hits += scan_text(
            data.decode("utf-8", errors="replace"), name, [] if name in HASHED_ONLY else patterns
        )
    messages = commit_messages(root) if history else []
    for sha, message in messages:
        hits += scan_text(message, f"commit {sha}", patterns)
    return hits, scanned, len(messages)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan files and commit messages for banned names and terms.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository to scan (default: this one)")
    parser.add_argument("--banned-file", type=Path, help="never-committed regular expressions, one per line")
    parser.add_argument("--no-history", action="store_true", help="skip the commit messages")
    args = parser.parse_args(argv)
    try:
        patterns = load_patterns(args.banned_file)
    except (OSError, re.error) as exc:
        print(f"scrub: cannot use the banned file: {exc}", file=sys.stderr)
        return 2
    hits, files, messages = scan(args.root, patterns, history=not args.no_history)
    for hit in hits:
        print(hit)
    local = f" and {len(patterns)} local patterns" if patterns else ""
    verdict = "CLEAN" if not hits else f"{len(hits)} HITS"
    print(
        f"scrub: {files} files and {messages} commit messages, {len(HASHED_TERMS)} committed terms{local}: {verdict}"
    )
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())

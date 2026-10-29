"""tools/sync_kit.py: palette parsing, the generated block, manifests, the copy and the check."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

DARK = ["#c38102", "#058DB5", "#02AB70", "#AB6FE5", "#CA445C", "#77A304", "#028E7F", "#7A84EF"]
LIGHT = ["#B45309", "#0369A1", "#15803D", "#7E22CE", "#EB4960", "#3B6201", "#00948A", "#4338CA"]
SEQ_DARK = ["#6D4200", "#8B5502", "#AB6901", "#CB7E04", "#EC940D", "#FFB257"]
SEQ_LIGHT = ["#F29B1D", "#D78602", "#BB7400", "#9F6202", "#845001", "#694002"]
DIV_DARK = ["#FFA9AF", "#EE6476", "#BC364E", "#3D3D3D", "#048073", "#0EB09E", "#57DDCA"]
DIV_LIGHT = ["#9D1135", "#D14A5F", "#FF7C8A", "#DEDEDE", "#36C3B0", "#039585", "#026359"]


def _array(values: list[str], quote: str) -> str:
    return ", ".join(f"{quote}{value}{quote}" for value in values)


def theme_js(style: str) -> str:
    if style == "freeze":
        return (
            "// chart colours\n"
            "export const palette = Object.freeze({\n"
            f"  dark: Object.freeze([{_array(DARK, chr(39))}]),\n"
            f"  light: Object.freeze([{_array(LIGHT, chr(39))}]),\n"
            "});\n"
            "export const sequential = Object.freeze({\n"
            f"  dark: Object.freeze([{_array(SEQ_DARK, chr(39))}]),\n"
            f"  light: Object.freeze([{_array(SEQ_LIGHT, chr(39))}]),\n"
            "});\n"
            "export const diverging = Object.freeze({\n"
            f"  dark: Object.freeze([{_array(DIV_DARK, chr(39))}]),\n"
            f"  light: Object.freeze([{_array(DIV_LIGHT, chr(39))}]),\n"
            "});\n"
            "export function theme(mode) { return { color: palette[mode] }; }\n"
        )
    if style == "pair":
        return (
            "const pair = (dark, light) => Object.freeze({ dark: Object.freeze(dark), light: Object.freeze(light) });\n"
            "\n"
            "export const palette = pair(\n"
            f"  [{_array(DARK, chr(39))}],\n"
            f"  [{_array(LIGHT, chr(39))}],\n"
            ");\n"
            "export const sequential = pair(\n"
            f"  [{_array(SEQ_DARK, chr(39))}],\n"
            f"  [{_array(SEQ_LIGHT, chr(39))}],\n"
            ");\n"
            "export const diverging = pair(\n"
            f"  [{_array(DIV_DARK, chr(39))}],\n"
            f"  [{_array(DIV_LIGHT, chr(39))}],\n"
            ");\n"
            "const TOKENS = { dark: { text: '#E6EDF3' }, light: { text: '#14181D' } };\n"
        )
    return (
        f'const palette = {{ "dark": [{_array(DARK, chr(34))}], "light": [{_array(LIGHT, chr(34))}] }};\n'
        f"let sequential = {{ dark: [{_array(SEQ_DARK, chr(34))}], light: [{_array(SEQ_LIGHT, chr(34))}] }};\n"
        f"var diverging = {{ dark: [{_array(DIV_DARK, chr(34))}], light: [{_array(DIV_LIGHT, chr(34))}] }};\n"
        "export { palette, sequential, diverging };\n"
    )


@pytest.fixture(scope="module")
def sync_kit(tool: Callable[[str], ModuleType]) -> ModuleType:
    return tool("tools/sync_kit.py")


@pytest.mark.parametrize("style", ["freeze", "plain", "pair"])
def test_parse_palette_reads_each_syntax(sync_kit: ModuleType, style: str) -> None:
    palette = sync_kit.parse_palette(theme_js(style))
    assert palette["PALETTE"]["dark"][0] == "#C38102"
    assert palette["PALETTE"]["light"] == tuple(LIGHT)
    assert palette["SEQUENTIAL"]["dark"] == tuple(SEQ_DARK)
    assert palette["DIVERGING"]["light"] == tuple(DIV_LIGHT)


def test_parse_palette_rejects_a_wrong_length(sync_kit: ModuleType) -> None:
    broken = theme_js("freeze").replace(", '#7A84EF'", "")
    with pytest.raises(sync_kit.KitError, match="PALETTE dark has 7 colours, expected 8"):
        sync_kit.parse_palette(broken)


def test_block_round_trip_and_replace(sync_kit: ModuleType) -> None:
    palette = sync_kit.parse_palette(theme_js("freeze"))
    block = sync_kit.render_block(palette)
    assert block.startswith(sync_kit.BLOCK_START) and block.endswith(sync_kit.BLOCK_END)
    assert all(len(line) <= 110 for line in block.splitlines())
    source = f"Theme = str\n\n{sync_kit.BLOCK_START}\nPALETTE = {{}}\n{sync_kit.BLOCK_END}\n\nx = 1\n"
    updated = sync_kit.replace_block(source, block)
    assert sync_kit.read_block(updated) == palette
    assert updated.endswith("\n\nx = 1\n")
    with pytest.raises(sync_kit.KitError, match="markers"):
        sync_kit.replace_block("x = 1\n", block)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("shape", ["list", "files", "mapping"])
def test_parse_manifest_shapes(sync_kit: ModuleType, shape: str) -> None:
    entries = [
        {"file": "dist/tokens.css", "bytes": 3, "sha256": "AB" * 32},
        {"file": "fonts/a.woff2", "sha256": "cd" * 32},
    ]
    payload: object
    if shape == "list":
        payload = entries
    elif shape == "files":
        payload = {"version": "v0.1.0", "files": entries}
    else:
        payload = {"dist/tokens.css": "AB" * 32, "fonts/a.woff2": {"sha256": "cd" * 32}}
    parsed = sync_kit.parse_manifest(json.dumps(payload).encode())
    assert parsed == {"tokens.css": "ab" * 32, "fonts/a.woff2": "cd" * 32}


def _kit_files() -> dict[str, bytes]:
    return {
        "tokens.css": b":root{--bg:#0B0F14}\n",
        "echarts-theme.js": theme_js("freeze").encode(),
        "fonts/fonts.css": b"@font-face{}\n",
    }


def _write_dist(root: Path, files: dict[str, bytes]) -> Path:
    dist = root / "dist"
    for name, data in files.items():
        target = dist / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = [
        {"file": f"dist/{name}", "bytes": len(data), "sha256": _sha(data)}
        for name, data in sorted(files.items())
    ]
    (dist / "MANIFEST.json").write_bytes(json.dumps(manifest, indent=2).encode())
    return dist


def test_verify_reports_missing_changed_and_extra_files(sync_kit: ModuleType, tmp_path: Path) -> None:
    files = sync_kit.read_dir(_write_dist(tmp_path, _kit_files()))
    assert sync_kit.verify(files) == []
    files["tokens.css"] = b"changed"
    files["extra.js"] = b""
    del files["fonts/fonts.css"]
    problems = sync_kit.verify(files)
    assert "fonts/fonts.css is listed in MANIFEST.json but missing" in problems
    assert "tokens.css does not match its SHA-256 in MANIFEST.json" in problems
    assert "extra.js is not listed in MANIFEST.json" in problems


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _kit_repo(tmp_path: Path) -> Path:
    """A tiny git clone with dist/ committed and tagged v9.9.9."""
    repo = tmp_path / "kit"
    repo.mkdir()
    _write_dist(repo, _kit_files())
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "kit", cwd=repo)
    _git("tag", "-a", "v9.9.9", "-m", "v9.9.9", cwd=repo)
    return repo


def _charts(sync_kit: ModuleType, tmp_path: Path) -> Path:
    charts = tmp_path / "charts.py"
    charts.write_text(f"Theme = str\n\n{sync_kit.BLOCK_START}\n{sync_kit.BLOCK_END}\n", encoding="utf-8")
    return charts


def test_sync_copies_the_tag_and_check_passes(sync_kit: ModuleType, tmp_path: Path) -> None:
    repo = _kit_repo(tmp_path)
    kit_dir = tmp_path / "web" / "kit"
    charts = _charts(sync_kit, tmp_path)

    copied = sync_kit.sync(repo, "v9.9.9", kit_dir=kit_dir, charts=charts)

    assert copied == 4
    assert (kit_dir / "VERSION").read_text(encoding="utf-8") == "v9.9.9\n"
    assert (kit_dir / "fonts" / "fonts.css").read_bytes() == b"@font-face{}\n"
    assert sync_kit.read_block(charts.read_text(encoding="utf-8"))["PALETTE"]["dark"][1] == "#058DB5"
    assert sync_kit.check("v9.9.9", repo, None, kit_dir=kit_dir, charts=charts) == []
    assert sync_kit.check("v9.9.9", tmp_path / "absent", repo / "dist", kit_dir=kit_dir, charts=charts) == []

    (kit_dir / "tokens.css").write_bytes(b"edited")
    problems = sync_kit.check("v9.9.9", repo, None, kit_dir=kit_dir, charts=charts)
    assert "tokens.css differs from the kit" in problems
    shutil.copy(repo / "dist" / "tokens.css", kit_dir / "tokens.css")
    charts.write_text(charts.read_text(encoding="utf-8").replace("#058DB5", "#000000"), encoding="utf-8")
    problems = sync_kit.check("v9.9.9", repo, None, kit_dir=kit_dir, charts=charts)
    assert any("palette block" in problem for problem in problems)


def test_vendored_kit_matches_its_manifest(sync_kit: ModuleType) -> None:
    assert (sync_kit.KIT_DIR / "VERSION").read_text(encoding="utf-8").strip() == sync_kit.KIT_TAG
    assert sync_kit.check(sync_kit.KIT_TAG, sync_kit.DEFAULT_KIT_REPO, None) == []


@pytest.mark.parametrize("tag", ["--output={out}", "-v9.9.9", "-", "--", ""])
def test_read_archive_refuses_a_tag_that_looks_like_an_option(
    sync_kit: ModuleType, tmp_path: Path, tag: str
) -> None:
    repo = _kit_repo(tmp_path)
    out = tmp_path / "pwned.tar"
    with pytest.raises(sync_kit.KitError, match="Refusing the tag"):
        sync_kit.read_archive(repo, tag.format(out=out))
    assert not out.exists()
    assert not (repo / out.name).exists()


def test_sync_refuses_the_option_tag_before_touching_anything(sync_kit: ModuleType, tmp_path: Path) -> None:
    repo = _kit_repo(tmp_path)
    kit_dir = tmp_path / "web" / "kit"
    with pytest.raises(sync_kit.KitError, match="Refusing the tag"):
        sync_kit.sync(repo, "--output=x.tar", kit_dir=kit_dir, charts=tmp_path / "charts.py")
    assert not kit_dir.parent.exists()
    assert not (repo / "x.tar").exists()


Entry = tuple[tarfile.TarInfo, bytes]


def _entry(name: str, data: bytes = b"x", kind: bytes = tarfile.REGTYPE, link: str = "") -> Entry:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = link
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    return info, data


def _tar(*entries: Entry) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for info, data in entries:
            archive.addfile(info, io.BytesIO(data) if info.isreg() else None)
    return buffer.getvalue()


def _serve(monkeypatch: pytest.MonkeyPatch, sync_kit: ModuleType, payload: bytes) -> list[list[str]]:
    """Make `git archive` return ``payload``; the returned list collects the commands that were run."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout=payload, stderr=b"")

    monkeypatch.setattr(sync_kit.subprocess, "run", fake_run)
    return calls


def _fake_clone(tmp_path: Path) -> Path:
    repo = tmp_path / "fake-kit"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return repo


def test_git_archive_gets_a_double_dash_before_the_tag(
    sync_kit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _serve(monkeypatch, sync_kit, _tar(_entry("dist/tokens.css")))
    assert sync_kit.read_archive(_fake_clone(tmp_path), "v9.9.9") == {"tokens.css": b"x"}
    assert calls[0][-5:] == ["archive", "--format=tar", "--", "v9.9.9", "dist"]
    assert calls[0][:3] == ["git", "-c", "core.autocrlf=false"]


UNSAFE_NAMES = [
    "",
    "/abs",
    "../x",
    "a/../b",
    "a//b",
    "./x",
    "a/./b",
    "a/",
    "x\\y",
    "C:/x",
    "a:b",
    "x/a:b",
    "a\x00b",
    "a\nb",
    "CON",
    "con.css",
    "a/PRN",
    "AUX.tar.gz",
    "nul",
    "COM1",
    "x/com9.txt",
    "LPT1",
    "lpt9.css",
    "dir/Nul .css",
]
SAFE_NAMES = ["tokens.css", "fonts/inter-latin-wght-normal.woff2", "console.js", "com10.css", "nullable.js"]


@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_check_relative_rejects_unsafe_names(sync_kit: ModuleType, name: str) -> None:
    with pytest.raises(sync_kit.KitError, match="unsafe path"):
        sync_kit._check_relative(name)


@pytest.mark.parametrize("name", SAFE_NAMES)
def test_check_relative_accepts_plain_names(sync_kit: ModuleType, name: str) -> None:
    sync_kit._check_relative(name)


@pytest.mark.parametrize(
    "name",
    ["../x", "dist/../x", "dist/a:b", "dist/a//b", "dist/CON.css", "dist/x\\y", "other/x", "dist", "/dist/x"],
)
def test_read_archive_rejects_unsafe_or_foreign_members(
    sync_kit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _serve(monkeypatch, sync_kit, _tar(_entry("dist/tokens.css"), _entry(name)))
    with pytest.raises(sync_kit.KitError, match="Refusing"):
        sync_kit.read_archive(_fake_clone(tmp_path), "v9.9.9")


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_read_archive_rejects_links_and_devices(
    sync_kit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: bytes
) -> None:
    _serve(
        monkeypatch,
        sync_kit,
        _tar(_entry("dist/tokens.css"), _entry("dist/link", kind=kind, link="/etc/passwd")),
    )
    with pytest.raises(sync_kit.KitError, match="not a regular file"):
        sync_kit.read_archive(_fake_clone(tmp_path), "v9.9.9")


def test_read_archive_skips_folders_and_rejects_duplicates(
    sync_kit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folders = (_entry("dist", kind=tarfile.DIRTYPE), _entry("dist/fonts", kind=tarfile.DIRTYPE))
    _serve(monkeypatch, sync_kit, _tar(*folders, _entry("dist/fonts/a.css", b"a")))
    assert sync_kit.read_archive(_fake_clone(tmp_path), "v9.9.9") == {"fonts/a.css": b"a"}
    _serve(monkeypatch, sync_kit, _tar(_entry("dist/a.css", b"1"), _entry("dist/a.css", b"2")))
    with pytest.raises(sync_kit.KitError, match="twice"):
        sync_kit.read_archive(_fake_clone(tmp_path), "v9.9.9")


def _earlier_copy(kit_dir: Path) -> dict[str, bytes]:
    kit_dir.mkdir(parents=True)
    (kit_dir / "VERSION").write_bytes(b"v0.0.1\n")
    (kit_dir / "old.css").write_bytes(b"old")
    return {"VERSION": b"v0.0.1\n", "old.css": b"old"}


def _leftovers(parent: Path) -> list[str]:
    return sorted(item.name for item in parent.iterdir() if item.name.startswith(".kit-"))


def test_sync_refuses_to_replace_a_folder_that_is_not_a_kit_copy(
    sync_kit: ModuleType, tmp_path: Path
) -> None:
    repo = _kit_repo(tmp_path)
    kit_dir = tmp_path / "web" / "kit"
    kit_dir.mkdir(parents=True)
    (kit_dir / "notes.txt").write_bytes(b"mine")
    with pytest.raises(sync_kit.KitError, match="not an earlier kit copy"):
        sync_kit.sync(repo, "v9.9.9", kit_dir=kit_dir, charts=_charts(sync_kit, tmp_path))
    assert sync_kit.read_dir(kit_dir) == {"notes.txt": b"mine"}
    assert _leftovers(kit_dir.parent) == []


def test_sync_refuses_to_replace_a_file(sync_kit: ModuleType, tmp_path: Path) -> None:
    repo = _kit_repo(tmp_path)
    kit_dir = tmp_path / "web" / "kit"
    kit_dir.parent.mkdir()
    kit_dir.write_bytes(b"mine")
    with pytest.raises(sync_kit.KitError, match="not a folder"):
        sync_kit.sync(repo, "v9.9.9", kit_dir=kit_dir, charts=_charts(sync_kit, tmp_path))
    assert kit_dir.read_bytes() == b"mine"


@pytest.mark.parametrize(
    "seed",
    [{}, {"VERSION": b"v0.0.1\n"}, {"MANIFEST.json": b"[]", "stale.css": b"old"}],
    ids=["empty", "version", "manifest"],
)
def test_sync_replaces_an_empty_folder_or_an_earlier_copy(
    sync_kit: ModuleType, tmp_path: Path, seed: dict[str, bytes]
) -> None:
    repo = _kit_repo(tmp_path)
    kit_dir = tmp_path / "web" / "kit"
    kit_dir.mkdir(parents=True)
    for name, data in seed.items():
        (kit_dir / name).write_bytes(data)
    assert sync_kit.sync(repo, "v9.9.9", kit_dir=kit_dir, charts=_charts(sync_kit, tmp_path)) == 4
    assert sorted(sync_kit.read_dir(kit_dir)) == [
        "MANIFEST.json",
        "VERSION",
        "echarts-theme.js",
        "fonts/fonts.css",
        "tokens.css",
    ]
    assert _leftovers(kit_dir.parent) == []


def test_sync_checks_charts_markers_before_touching_the_kit(sync_kit: ModuleType, tmp_path: Path) -> None:
    repo = _kit_repo(tmp_path)
    kit_dir = tmp_path / "web" / "kit"
    earlier = _earlier_copy(kit_dir)
    charts = tmp_path / "charts.py"
    charts.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(sync_kit.KitError, match="markers"):
        sync_kit.sync(repo, "v9.9.9", kit_dir=kit_dir, charts=charts)
    assert sync_kit.read_dir(kit_dir) == earlier
    assert charts.read_text(encoding="utf-8") == "x = 1\n"
    assert _leftovers(kit_dir.parent) == []


def test_sync_restores_the_earlier_copy_when_the_swap_fails(
    sync_kit: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _kit_repo(tmp_path)
    kit_dir = tmp_path / "web" / "kit"
    earlier = _earlier_copy(kit_dir)
    real_replace = os.replace

    def flaky(src: Path, dst: Path) -> None:
        if Path(dst) == kit_dir and not str(src).endswith(".old"):
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(sync_kit.os, "replace", flaky)
    with pytest.raises(sync_kit.KitError, match="disk full"):
        sync_kit.sync(repo, "v9.9.9", kit_dir=kit_dir, charts=_charts(sync_kit, tmp_path))
    assert sync_kit.read_dir(kit_dir) == earlier
    assert [item.name for item in kit_dir.parent.iterdir()] == ["kit"]


def test_a_second_sync_changes_nothing(sync_kit: ModuleType, tmp_path: Path) -> None:
    repo = _kit_repo(tmp_path)
    kit_dir = tmp_path / "web" / "kit"
    charts = _charts(sync_kit, tmp_path)
    sync_kit.sync(repo, "v9.9.9", kit_dir=kit_dir, charts=charts)
    kit_before = sync_kit.read_dir(kit_dir)
    charts_before = charts.read_bytes()
    assert b"#058DB5" in charts_before
    old = 1_000_000_000 * 10**9
    os.utime(charts, ns=(old, old))

    assert sync_kit.sync(repo, "v9.9.9", kit_dir=kit_dir, charts=charts) == 4
    assert sync_kit.update_palette(kit_dir, charts) is True

    assert sync_kit.read_dir(kit_dir) == kit_before
    assert charts.read_bytes() == charts_before
    assert charts.stat().st_mtime_ns == old
    assert sync_kit.check("v9.9.9", repo, None, kit_dir=kit_dir, charts=charts) == []
    assert _leftovers(kit_dir.parent) == []


def test_replace_block_is_idempotent(sync_kit: ModuleType) -> None:
    block = sync_kit.render_block(sync_kit.parse_palette(theme_js("freeze")))
    source = f"Theme = str\n\n{sync_kit.BLOCK_START}\n{sync_kit.BLOCK_END}\n\nx = 1\n"
    once = sync_kit.replace_block(source, block)
    assert sync_kit.replace_block(once, block) == once
    assert once.count(sync_kit.BLOCK_START) == 1 and once.count(sync_kit.BLOCK_END) == 1

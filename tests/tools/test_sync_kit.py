"""tools/sync_kit.py: palette parsing, the generated block, manifests, the copy and the check."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
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


def test_sync_copies_the_tag_and_check_passes(sync_kit: ModuleType, tmp_path: Path) -> None:
    repo = tmp_path / "kit"
    repo.mkdir()
    _write_dist(repo, _kit_files())
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "kit", cwd=repo)
    _git("tag", "-a", "v9.9.9", "-m", "v9.9.9", cwd=repo)
    kit_dir = tmp_path / "web" / "kit"
    charts = tmp_path / "charts.py"
    charts.write_text(f"Theme = str\n\n{sync_kit.BLOCK_START}\n{sync_kit.BLOCK_END}\n", encoding="utf-8")

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

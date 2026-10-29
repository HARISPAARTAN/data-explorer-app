"""The fallback images and the README screenshots exist with the sizes the page and the docs use."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

SCREENSHOTS = {
    "upload-1440.png": (1440, 900),
    "overview-1440.png": (1440, 900),
    "quality-1440.png": (1440, 900),
    "explore-1440.png": (1440, 900),
    "visualise-1440.png": (1440, 900),
    "download-1440.png": (1440, 900),
    "overview-390.png": (390, 844),
    "fallback-1440.png": (1440, 900),
}


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR", f"{path.name} is not a PNG"
    width, height = struct.unpack(">II", head[16:24])
    return width, height


@pytest.mark.parametrize("name", ["upload-1440.png", "visualise-1440.png"])
def test_fallback_images(repo_root: Path, name: str) -> None:
    path = repo_root / "web" / "assets" / name
    assert png_size(path) == (1440, 900)
    assert path.stat().st_size <= 600_000
    assert path.read_bytes() == (repo_root / "docs" / "screenshots" / name).read_bytes()


def test_readme_screenshots(repo_root: Path) -> None:
    folder = repo_root / "docs" / "screenshots"
    assert sorted(path.name for path in folder.iterdir()) == sorted(SCREENSHOTS)
    for name, size in SCREENSHOTS.items():
        assert png_size(folder / name) == size, name


def test_web_assets_folder_holds_only_the_fallback_images(repo_root: Path) -> None:
    assert sorted(path.name for path in (repo_root / "web" / "assets").iterdir()) == [
        "upload-1440.png",
        "visualise-1440.png",
    ]

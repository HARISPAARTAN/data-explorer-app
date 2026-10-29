"""tools/make_data.py regenerates the committed samples and fixtures exactly."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

SAMPLE_FILES = ("retail_orders.csv", "sensor_readings.csv", "client_survey.xlsx")


@pytest.fixture(scope="module")
def make_data(tool: Callable[[str], ModuleType]) -> ModuleType:
    return tool("tools/make_data.py")


def _same(make_data: ModuleType, name: str, fresh: bytes, committed: bytes) -> bool:
    if name.endswith(".xlsx"):
        return bool(make_data.cell_values(fresh) == make_data.cell_values(committed))
    return fresh == committed


def test_samples_regenerate_identically(make_data: ModuleType, repo_root: Path) -> None:
    fresh = make_data.build_samples()
    assert sorted(fresh) == sorted(SAMPLE_FILES)
    for name, data in fresh.items():
        committed = (repo_root / "src" / "data_explorer" / "samples" / name).read_bytes()
        assert _same(make_data, name, data, committed), name


def test_fixtures_regenerate_identically(make_data: ModuleType, repo_root: Path) -> None:
    fresh = make_data.build_fixture_files()
    assert len(fresh) == 16
    for name, data in fresh.items():
        assert _same(make_data, name, data, (repo_root / "fixtures" / name).read_bytes()), name


def test_size_limits(make_data: ModuleType) -> None:
    for name, data in make_data.build_samples().items():
        assert len(data) <= 1_000_000, name
    for name, data in make_data.build_fixture_files().items():
        assert len(data) < 50_000, name


def test_raw_shapes(make_data: ModuleType) -> None:
    samples = make_data.build_samples()
    retail = samples["retail_orders.csv"]
    assert retail.startswith(b"\xef\xbb\xbforder_id;order_date;")
    assert retail.decode("utf-8-sig").count("\n") == 6_061
    sensor = samples["sensor_readings.csv"].decode("cp1252")
    assert sensor.count("\n") == 8_641 and "Caffè" in sensor
    survey = make_data.cell_values(samples["client_survey.xlsx"])
    assert list(survey) == ["Responses", "Notes"]
    assert survey["Responses"][0][0] == "Client satisfaction survey 2025"
    assert survey["Responses"][3][:2] == ("response_id", "submitted_at")
    assert sum(1 for row in survey["Responses"][4:] if any(value is not None for value in row)) == 1_224
    assert len(survey["Notes"]) == 7


def test_special_fixtures(make_data: ModuleType) -> None:
    fixtures = make_data.build_fixture_files()
    assert fixtures["empty.csv"] == b""
    assert fixtures["legacy.xls"].startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    assert b"\x00" in fixtures["not_a_table.bin"] and len(fixtures["not_a_table.bin"]) == 4096
    assert fixtures["utf8_bom_semicolon_decimal_comma.csv"].startswith(b"\xef\xbb\xbf")
    fixtures["cp1252_semicolon.csv"].decode("cp1252")
    with pytest.raises(UnicodeDecodeError):
        fixtures["latin1_tab.tsv"].decode("cp1252")


def test_cli_writes_into_given_folders(make_data: ModuleType, tmp_path: Path) -> None:
    code = make_data.main(
        ["--samples-dir", str(tmp_path / "s"), "--fixtures", "--fixtures-dir", str(tmp_path / "f")]
    )
    assert code == 0
    assert sorted(path.name for path in (tmp_path / "s").iterdir()) == sorted(SAMPLE_FILES)
    assert len(list((tmp_path / "f").iterdir())) == 16

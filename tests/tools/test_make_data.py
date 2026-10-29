"""tools/make_data.py regenerates the committed samples and fixtures exactly."""

from __future__ import annotations

import csv
import datetime as dt
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
from openpyxl import load_workbook

SAMPLE_FILES = ("retail_orders.csv", "sensor_readings.csv", "client_survey.xlsx")
SAMPLES = Path("src") / "data_explorer" / "samples"
WORKBOOKS = (SAMPLES / "client_survey.xlsx", Path("fixtures") / "header_offset_two_sheets.xlsx")


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


def _csv_rows(path: Path, encoding: str, delimiter: str) -> list[dict[str, str]]:
    with path.open(encoding=encoding, newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def test_retail_planted_defects(repo_root: Path) -> None:
    rows = _csv_rows(repo_root / SAMPLES / "retail_orders.csv", "utf-8-sig", ";")
    assert len(rows) == 6_060
    ids = [row["order_id"] for row in rows]
    repeats = {i for i in range(1, len(rows)) if rows[i] == rows[i - 1]}
    assert len(repeats) == 60
    assert all(ids[i] == ids[i - 1] for i in repeats)
    assert len(set(ids)) == 6_000
    assert max(Counter(ids).values()) == 2
    deduped = [row for i, row in enumerate(rows) if i not in repeats]
    assert len(deduped) == 6_000 and len({row["order_id"] for row in deduped}) == 6_000
    assert sum(1 for row in rows if row["discount_pct"] == "") == 180
    units = [int(row["units"]) for row in rows]
    assert sum(1 for value in units if 120 <= value <= 400) == 15
    assert all(1 <= value <= 12 or 120 <= value <= 400 for value in units)
    assert sum(1 for value in units if 1 <= value <= 12) == 6_060 - 15
    assert {row["country"] for row in rows} == {"IT"}


def test_sensor_planted_defects(repo_root: Path) -> None:
    rows = _csv_rows(repo_root / SAMPLES / "sensor_readings.csv", "cp1252", ",")
    assert len(rows) == 8_640
    assert {row["firmware"] for row in rows} == {"2.4.1"}
    window = [dt.datetime(2025, 3, 21, 6, 0) + dt.timedelta(hours=hour) for hour in range(48)]
    stamps = {stamp.strftime("%Y-%m-%d %H:%M") for stamp in window}
    assert len(stamps) == 48
    inside = [row for row in rows if row["sensor_id"] == "MX-4" and row["timestamp"] in stamps]
    assert [row["timestamp"] for row in inside] == [stamp.strftime("%Y-%m-%d %H:%M") for stamp in window]
    for column in ("temperature_c", "humidity_pct", "co2_ppm"):
        assert all(row[column] == "" for row in inside), column
    assert sum(1 for row in rows if row["temperature_c"] == "") == 48
    assert sum(1 for row in rows if row["co2_ppm"] == "") == 48
    assert sum(1 for row in rows if row["humidity_pct"] == "") == 78
    spikes = [row for row in rows if row["co2_ppm"] == "9999"]
    assert len(spikes) == 12
    assert not any(row["sensor_id"] == "MX-4" and row["timestamp"] in stamps for row in spikes)


def test_survey_planted_defects(make_data: ModuleType, repo_root: Path) -> None:
    sheets = make_data.cell_values((repo_root / SAMPLES / "client_survey.xlsx").read_bytes())
    assert list(sheets) == ["Responses", "Notes"]
    header = list(sheets["Responses"][3])
    assert header[:2] == ["response_id", "submitted_at"] and header[-1] == "survey_wave"
    records = [
        dict(zip(header, row, strict=True))
        for row in sheets["Responses"][4:]
        if any(value is not None for value in row)
    ]
    assert len(records) == 1_224
    assert sum(1 for i in range(1, len(records)) if records[i] == records[i - 1]) == 24
    assert sum(1 for record in records if record["satisfaction"] is None) == 37
    assert sum(1 for record in records if record["comment"] is None) == 840
    seconds = [record["response_time_s"] for record in records]
    assert all(isinstance(value, int) for value in seconds)
    assert sum(1 for value in seconds if 20_001 <= value <= 90_000) == 10
    assert sum(1 for value in seconds if 60 <= value <= 1_800) == 1_224 - 10
    assert {record["survey_wave"] for record in records} == {2025}
    notes = sheets["Notes"]
    assert notes[0] == ("question", "text") and len(notes) == 1 + 6


@pytest.mark.parametrize("relative", WORKBOOKS, ids=lambda path: path.name)
def test_workbooks_carry_the_fixed_time(repo_root: Path, relative: Path) -> None:
    workbook = load_workbook(repo_root / relative, read_only=True)
    try:
        properties = workbook.properties
        assert properties.created == properties.modified == dt.datetime(2026, 10, 29)
    finally:
        workbook.close()


def test_two_builds_are_byte_identical(make_data: ModuleType) -> None:
    first = (make_data.build_samples(), make_data.build_fixture_files())
    time.sleep(1.1)  # openpyxl stamps whole seconds; a later build must still match byte for byte
    second = (make_data.build_samples(), make_data.build_fixture_files())
    assert first == second

"""The three samples load with the documented shapes and exactly the planted defects (docs/data-model.md)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest

from data_explorer.core.io import SAMPLES, sample_bytes
from data_explorer.core.profile import profile_dataset
from data_explorer.core.quality import (
    constant_columns,
    duplicates,
    iqr_outliers,
    missing_summary,
    outlier_rows,
)

Samples = dict[str, tuple[pd.DataFrame, Any]]


def test_shapes_and_reports(samples: Samples) -> None:
    retail, retail_report = samples["retail_orders"]
    sensor, sensor_report = samples["sensor_readings"]
    survey, survey_report = samples["client_survey"]
    assert retail.shape == (6_060, 11) and sensor.shape == (8_640, 9) and survey.shape == (1_224, 11)
    assert (retail_report.encoding, retail_report.delimiter, retail_report.decimal) == ("utf-8-sig", ";", ",")
    assert (sensor_report.encoding, sensor_report.delimiter, sensor_report.decimal) == ("cp1252", ",", ".")
    assert (survey_report.file_type, survey_report.sheet, survey_report.sheets) == (
        "xlsx",
        "Responses",
        ("Responses", "Notes"),
    )
    assert survey_report.header_row == 3 and retail_report.header_row == 0
    assert retail_report.renamed_columns == () and retail_report.warnings == ()


def test_duplicates(samples: Samples) -> None:
    for key, expected in (("retail_orders", 60), ("sensor_readings", 0), ("client_survey", 24)):
        report = duplicates(samples[key][0])
        assert (report.duplicate_rows, report.groups) == (expected, expected), key


def test_missing_values(samples: Samples) -> None:
    def summary(key: str) -> dict[str, int]:
        frame = missing_summary(samples[key][0])
        return dict(zip(frame["column"], frame["missing"], strict=True))

    assert summary("retail_orders") == {"discount_pct": 180}
    assert summary("sensor_readings") == {"humidity_pct": 78, "temperature_c": 48, "co2_ppm": 48}
    assert summary("client_survey") == {"comment": 840, "satisfaction": 37}


def test_sensor_offline_block_is_48_consecutive_hours(samples: Samples) -> None:
    sensor = samples["sensor_readings"][0]
    offline = sensor[(sensor["sensor_id"] == "MX-4") & sensor["temperature_c"].isna()]
    assert len(offline) == 48
    assert offline["timestamp"].iloc[0] == pd.Timestamp("2025-03-21 06:00")
    assert (offline["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all()
    assert offline["humidity_pct"].isna().all() and offline["co2_ppm"].isna().all()


def test_outliers(samples: Samples) -> None:
    retail = samples["retail_orders"][0]
    units = {item.column: item for item in iqr_outliers(retail)}["units"]
    assert (units.n_low, units.n_high) == (0, 15)
    rows = outlier_rows(retail, "units")
    assert len(rows) == 15 and rows["units"].between(120, 400).all()
    sensor = samples["sensor_readings"][0]
    sentinels = sensor.index[sensor["co2_ppm"] == 9999]
    assert len(sentinels) == 12 and set(sentinels) <= set(outlier_rows(sensor, "co2_ppm").index)
    survey = samples["client_survey"][0]
    slow = survey.index[survey["response_time_s"] > 20_000]
    assert len(slow) == 10 and set(slow) == set(outlier_rows(survey, "response_time_s").index)


def test_constant_columns(samples: Samples) -> None:
    def constants(key: str) -> dict[str, object]:
        return {item.name: item.value for item in constant_columns(samples[key][0])}

    assert constants("retail_orders") == {"country": "IT"}
    assert constants("sensor_readings") == {"firmware": "2.4.1"}
    assert constants("client_survey") == {"survey_wave": 2025}


def test_kinds(samples: Samples) -> None:
    kinds = profile_dataset(samples["retail_orders"][0]).kinds
    assert dict(kinds) == {"numeric": 4, "datetime": 1, "boolean": 0, "categorical": 5, "text": 1}
    assert samples["sensor_readings"][0]["timestamp"].dtype == "datetime64[us]"
    assert samples["client_survey"][0]["submitted_at"].dtype == "datetime64[us]"
    assert samples["retail_orders"][0]["order_date"].dtype == "datetime64[us]"


def test_sizes() -> None:
    for key in SAMPLES:
        assert len(sample_bytes(key)) <= 1_000_000, key


def test_regenerating_gives_identical_files(
    tool: Callable[[str], ModuleType], repo_root: Path, tmp_path: Path
) -> None:
    make_data = tool("tools/make_data.py")
    assert make_data.main(["--samples-dir", str(tmp_path)]) == 0
    for info in SAMPLES.values():
        fresh = (tmp_path / info.file_name).read_bytes()
        committed = sample_bytes(info.key)
        if info.file_name.endswith(".xlsx"):
            assert make_data.cell_values(fresh) == make_data.cell_values(committed)
        else:
            assert fresh == committed, info.file_name


@pytest.mark.parametrize("key", list(SAMPLES))
def test_no_names_or_addresses_in_text_columns(samples: Samples, key: str) -> None:
    frame = samples[key][0]
    text = " ".join(frame.select_dtypes(include=["str"]).astype("str").stack().dropna().unique().tolist())
    for marker in ("@", "Via ", "Str.", "S.p.A", "S.r.l", "GmbH", "Ltd"):
        assert marker not in text, marker

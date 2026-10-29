import dataclasses
import datetime as dt
import enum
import math

import numpy as np
import pandas as pd
import pytest

from data_explorer.core import json_safe


class Colour(enum.StrEnum):
    RED = "red"


@dataclasses.dataclass(frozen=True)
class Pair:
    left: float
    right: tuple[int, ...]


def test_missing_values_become_none() -> None:
    assert json_safe(None) is None
    assert json_safe(float("nan")) is None
    assert json_safe(np.float64("nan")) is None
    assert json_safe(float("inf")) is None
    assert json_safe(pd.NaT) is None
    assert json_safe(pd.NA) is None
    assert json_safe(np.datetime64("NaT", "us")) is None


def test_numbers_are_plain_and_rounded() -> None:
    assert json_safe(np.int64(7)) == 7 and type(json_safe(np.int64(7))) is int
    assert json_safe(np.bool_(True)) is True
    assert json_safe(np.float64(1.23456789)) == 1.234568
    assert json_safe(-0.0000001) == 0.0
    assert str(json_safe(-0.0)) == "0.0"
    assert math.isclose(json_safe(2 / 3), 0.666667)  # type: ignore[arg-type]


def test_dates_are_iso_8601() -> None:
    assert json_safe(pd.Timestamp("2025-03-01 08:30")) == "2025-03-01T08:30:00"
    assert json_safe(dt.date(2025, 3, 1)) == "2025-03-01"
    assert json_safe(np.datetime64("2025-03-01T08:30")) == "2025-03-01T08:30:00"


def test_containers_enums_and_dataclasses() -> None:
    assert json_safe(Colour.RED) == "red"
    assert json_safe({1: (1, 2.0, None)}) == {"1": [1, 2.0, None]}
    assert json_safe({"b", "a"}) == ["a", "b"]
    assert json_safe(np.array([1.5, np.nan])) == [1.5, None]
    assert json_safe(Pair(0.1234567, (1, 2))) == {"left": 0.123457, "right": [1, 2]}


def test_datetime64_arrays_are_iso_8601() -> None:
    assert json_safe(np.array(["2025-03-01"], dtype="datetime64[ns]")) == ["2025-03-01T00:00:00"]
    assert json_safe(np.array(["2025-03-01"], dtype="datetime64[us]")) == ["2025-03-01T00:00:00"]
    with_nat = np.array(["2025-03-01", "NaT"], dtype="datetime64[ns]")
    assert json_safe(with_nat) == ["2025-03-01T00:00:00", None]


def test_numpy_strings_become_plain_str() -> None:
    assert json_safe(np.str_("a")) == "a"
    assert type(json_safe(np.str_("a"))) is str


def test_unknown_types_raise() -> None:
    with pytest.raises(TypeError, match="object"):
        json_safe(object())


def test_json_object_requires_a_mapping_or_dataclass() -> None:
    from data_explorer.core import json_object

    assert json_object(Pair(1.0, ())) == {"left": 1.0, "right": []}
    with pytest.raises(TypeError, match="JSON object"):
        json_object([1, 2])

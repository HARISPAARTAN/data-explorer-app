"""Pure computation for the data explorer. Nothing in this package imports Streamlit."""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import math
from collections.abc import Mapping
from typing import TypeAlias

import numpy as np
import pandas as pd

JSONValue: TypeAlias = "None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]"

FLOAT_DECIMALS = 6

__all__ = ["FLOAT_DECIMALS", "JSONValue", "json_object", "json_safe"]


def json_safe(value: object) -> JSONValue:
    """Return ``value`` as plain JSON types.

    NaN, NaT, ``pd.NA`` and infinities become ``None``; floats are rounded to six decimals;
    timestamps and dates are ISO 8601 strings; enums give their value; mappings, sequences,
    arrays, sets (sorted) and dataclasses are converted recursively.
    """
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, enum.Enum):
        return json_safe(value.value)
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        if not math.isfinite(number):
            return None
        rounded = round(number, FLOAT_DECIMALS)
        return 0.0 if rounded == 0 else rounded
    if isinstance(value, str):
        return str(value)
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        return pd.Timestamp(value).isoformat()
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json_safe(dataclasses.asdict(value))
    if isinstance(value, set | frozenset):
        return [json_safe(item) for item in sorted(value, key=repr)]
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        if value.dtype.kind in "Mm":
            # ndarray.tolist() yields epoch integers for nanosecond units, so go through pandas
            # to get Timestamp / Timedelta / NaT objects that the scalar rules then handle.
            value = pd.Series(value.ravel()).astype(object).to_numpy().reshape(value.shape)
        return [json_safe(item) for item in value.tolist()]
    raise TypeError(f"Cannot convert a {type(value).__name__} object to JSON")


def json_object(value: object) -> dict[str, JSONValue]:
    """``json_safe`` for values that must become a JSON object (dataclasses and mappings)."""
    result = json_safe(value)
    if not isinstance(result, dict):
        raise TypeError(f"Expected a JSON object, got {type(result).__name__}")
    return result

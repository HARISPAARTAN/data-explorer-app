"""Column kinds and the statistics shown on the Overview page and in the profile exports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from data_explorer.core import JSONValue, json_object

Kind = Literal["numeric", "datetime", "boolean", "categorical", "text"]
KINDS: tuple[Kind, ...] = ("numeric", "datetime", "boolean", "categorical", "text")
CATEGORICAL_MAX_UNIQUE = 50
TOP_N = 5

Stat = float | int | str | None


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    kind: Kind
    dtype: str
    count: int
    missing: int
    missing_pct: float
    unique: int
    stats: Mapping[str, Stat]
    top: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return json_object(self)


@dataclass(frozen=True)
class DatasetProfile:
    n_rows: int
    n_cols: int
    n_cells: int
    missing_cells: int
    missing_cells_pct: float
    duplicate_rows: int
    memory_bytes: int
    kinds: Mapping[Kind, int]
    columns: tuple[ColumnProfile, ...]

    def to_dict(self) -> dict[str, JSONValue]:
        return json_object(self)


def classify(series: pd.Series[Any]) -> Kind:
    if pd.api.types.is_bool_dtype(series.dtype):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "datetime"
    if int(series.nunique(dropna=True)) <= CATEGORICAL_MAX_UNIQUE:
        return "categorical"
    return "text"


def _numeric_stats(series: pd.Series[Any]) -> dict[str, Stat]:
    values = series.dropna().astype("float64")
    if values.empty:
        empty: dict[str, Stat] = dict.fromkeys(("mean", "std", "min", "p25", "median", "p75", "max"))
        return empty | {"zeros": 0, "negatives": 0}
    quartiles = values.quantile([0.25, 0.5, 0.75]).tolist()
    integer = pd.api.types.is_integer_dtype(series.dtype)
    low, high = float(values.min()), float(values.max())
    return {
        "mean": float(values.mean()),
        "std": float(values.std(ddof=1)) if len(values) > 1 else None,
        "min": int(low) if integer else low,
        "p25": float(quartiles[0]),
        "median": float(quartiles[1]),
        "p75": float(quartiles[2]),
        "max": int(high) if integer else high,
        "zeros": int((values == 0).sum()),
        "negatives": int((values < 0).sum()),
    }


def _datetime_stats(series: pd.Series[Any]) -> dict[str, Stat]:
    values = series.dropna()
    if values.empty:
        return {"min": None, "max": None, "span_days": None}
    low, high = pd.Timestamp(values.min()), pd.Timestamp(values.max())
    return {
        "min": low.isoformat(),
        "max": high.isoformat(),
        "span_days": (high - low).total_seconds() / 86_400,
    }


def _top(series: pd.Series[Any]) -> tuple[tuple[str, int], ...]:
    counts = series.dropna().astype("str").value_counts()
    pairs = sorted(
        ((str(value), int(count)) for value, count in counts.items()), key=lambda item: (-item[1], item[0])
    )
    return tuple(pairs[:TOP_N])


def profile_column(series: pd.Series[Any], name: str) -> ColumnProfile:
    kind = classify(series)
    n_rows = len(series)
    missing = int(series.isna().sum())
    stats: dict[str, Stat] = {}
    top: tuple[tuple[str, int], ...] = ()
    if kind == "numeric":
        stats = _numeric_stats(series)
    elif kind == "datetime":
        stats = _datetime_stats(series)
    elif kind == "boolean":
        values = series.dropna().astype("bool")
        stats = {"true": int(values.sum()), "false": int((~values).sum())}
    else:
        top = _top(series)
        if kind == "text":
            lengths = series.dropna().astype("str").str.len()
            stats = {
                "mean_length": float(lengths.mean()) if len(lengths) else None,
                "max_length": int(lengths.max()) if len(lengths) else None,
            }
    return ColumnProfile(
        name=name,
        kind=kind,
        dtype=str(series.dtype),
        count=n_rows - missing,
        missing=missing,
        missing_pct=missing / n_rows * 100 if n_rows else 0.0,
        unique=int(series.nunique(dropna=True)),
        stats=stats,
        top=top,
    )


def profile_dataset(df: pd.DataFrame) -> DatasetProfile:
    if len(df.columns) == 0:
        raise ValueError("The table has no columns.")
    n_rows, n_cols = len(df), len(df.columns)
    columns = tuple(
        profile_column(df.iloc[:, position], str(name)) for position, name in enumerate(df.columns)
    )
    missing_cells = sum(column.missing for column in columns)
    n_cells = n_rows * n_cols
    return DatasetProfile(
        n_rows=n_rows,
        n_cols=n_cols,
        n_cells=n_cells,
        missing_cells=missing_cells,
        missing_cells_pct=missing_cells / n_cells * 100 if n_cells else 0.0,
        duplicate_rows=int(df.duplicated(keep="first").sum()) if n_rows else 0,
        memory_bytes=int(df.memory_usage(deep=True).sum()),
        kinds={kind: sum(1 for column in columns if column.kind == kind) for kind in KINDS},
        columns=columns,
    )

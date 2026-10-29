"""Data-quality checks: missing values, duplicates, constant columns and IQR outliers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from data_explorer.core import JSONValue, json_object, json_safe

K_MIN = 0.5
K_MAX = 5.0
MIN_OUTLIER_VALUES = 4
DUPLICATE_SAMPLE = 20
MATRIX_BINS = 100
MATRIX_MAX_COLUMNS = 50
OUTLIER_ROWS_SHOWN = 200
MATRIX_COLUMNS = ["bin", "row_from", "row_to", "column", "missing_share"]


def _check_columns(df: pd.DataFrame, columns: Sequence[str]) -> None:
    unknown = [str(column) for column in columns if column not in df.columns]
    if unknown:
        raise ValueError(f"Unknown column: {', '.join(unknown)}")


def _check_k(k: float) -> None:
    if not K_MIN <= k <= K_MAX:
        raise ValueError(f"The fence factor k must be between 0.5 and 5.0, got {k}.")


def _is_measure(series: pd.Series[Any]) -> bool:
    return bool(pd.api.types.is_numeric_dtype(series.dtype) and not pd.api.types.is_bool_dtype(series.dtype))


def missing_summary(df: pd.DataFrame) -> pd.DataFrame:
    n_rows = len(df)
    rows = []
    for position, name in enumerate(df.columns):
        missing = int(df.iloc[:, position].isna().sum())
        if missing:
            rows.append((str(name), missing, missing / n_rows * 100))
    rows.sort(key=lambda row: -row[1])
    frame = pd.DataFrame(rows, columns=["column", "missing", "missing_pct"])
    return frame.astype({"column": "str", "missing": "int64", "missing_pct": "float64"})


def missing_matrix(
    df: pd.DataFrame, bins: int = MATRIX_BINS, max_columns: int = MATRIX_MAX_COLUMNS
) -> pd.DataFrame:
    """Share of missing cells per column in up to ``bins`` consecutive row blocks (1-based rows)."""
    if bins < 1 or max_columns < 1:
        raise ValueError("bins and max_columns must be at least 1.")
    n_rows = len(df)
    positions = list(range(len(df.columns)))
    if len(positions) > max_columns:
        counts = df.isna().sum().tolist()
        positions = sorted(sorted(positions, key=lambda p: (-int(counts[p]), p))[:max_columns])
    blocks = min(bins, n_rows)
    if blocks == 0 or not positions:
        return pd.DataFrame({name: [] for name in MATRIX_COLUMNS}).astype(
            {
                "bin": "int64",
                "row_from": "int64",
                "row_to": "int64",
                "column": "str",
                "missing_share": "float64",
            }
        )
    sizes = np.array([n_rows // blocks + (1 if i < n_rows % blocks else 0) for i in range(blocks)])
    starts = np.concatenate(([0], np.cumsum(sizes)[:-1]))
    missing = df.iloc[:, positions].isna().to_numpy(dtype=np.int64)
    shares = np.add.reduceat(missing, starts, axis=0) / sizes[:, None]
    names = [str(df.columns[p]) for p in positions]
    records: dict[str, list[Any]] = {name: [] for name in MATRIX_COLUMNS}
    for block in range(blocks):
        for index, name in enumerate(names):
            records["bin"].append(block + 1)
            records["row_from"].append(int(starts[block]) + 1)
            records["row_to"].append(int(starts[block] + sizes[block]))
            records["column"].append(name)
            records["missing_share"].append(float(shares[block, index]))
    return pd.DataFrame(records).astype({"column": "str", "missing_share": "float64"})


@dataclass(frozen=True)
class DuplicateReport:
    subset: tuple[str, ...]
    duplicate_rows: int
    groups: int
    sample_rows: pd.DataFrame = field(compare=False, repr=False)

    def to_dict(self) -> dict[str, JSONValue]:
        return {"subset": list(self.subset), "duplicate_rows": self.duplicate_rows, "groups": self.groups}


def duplicates(
    df: pd.DataFrame, subset: Sequence[str] | None = None, sample: int = DUPLICATE_SAMPLE
) -> DuplicateReport:
    """Rows identical (in ``subset`` or all columns) to an earlier row; groups are distinct duplicated keys."""
    chosen = tuple(str(column) for column in subset) if subset else ()
    _check_columns(df, chosen)
    columns = list(chosen) if chosen else list(df.columns)
    if len(df) == 0 or not columns:
        return DuplicateReport(chosen, 0, 0, df.iloc[0:0])
    later = df.duplicated(subset=columns, keep="first")
    duplicate_rows = int(later.sum())
    groups = int(len(df.loc[later, columns].drop_duplicates()))
    involved = df.loc[df.duplicated(subset=columns, keep=False)]
    if len(involved):
        group_ids = involved.groupby(columns, dropna=False, sort=False).ngroup().to_numpy()
        involved = involved.iloc[np.argsort(group_ids, kind="stable")]
    return DuplicateReport(chosen, duplicate_rows, groups, involved.head(sample))


@dataclass(frozen=True)
class ConstantColumn:
    name: str
    value: JSONValue
    all_missing: bool


def constant_columns(df: pd.DataFrame) -> tuple[ConstantColumn, ...]:
    """Columns with at most one distinct non-missing value; empty columns have all_missing=True."""
    result = []
    for position, name in enumerate(df.columns):
        values = df.iloc[:, position].dropna()
        if values.nunique() <= 1:
            if values.empty:
                result.append(ConstantColumn(str(name), None, True))
            else:
                result.append(ConstantColumn(str(name), json_safe(values.iloc[0]), False))
    return tuple(result)


@dataclass(frozen=True)
class OutlierSummary:
    column: str
    q1: float
    q3: float
    iqr: float
    lower: float
    upper: float
    n_low: int
    n_high: int
    pct: float


def _values(series: pd.Series[Any]) -> np.ndarray[Any, np.dtype[np.float64]]:
    return series.dropna().to_numpy(dtype="float64")


def _fences(
    values: np.ndarray[Any, np.dtype[np.float64]], k: float
) -> tuple[float, float, float, float, float] | None:
    if len(values) < MIN_OUTLIER_VALUES:
        return None
    q1, q3 = (float(q) for q in np.quantile(values, [0.25, 0.75]))
    iqr = q3 - q1
    if iqr == 0:
        return None
    return q1, q3, iqr, q1 - k * iqr, q3 + k * iqr


def iqr_outliers(df: pd.DataFrame, k: float = 1.5) -> tuple[OutlierSummary, ...]:
    _check_k(k)
    result = []
    for position, name in enumerate(df.columns):
        series = df.iloc[:, position]
        if not _is_measure(series):
            continue
        values = _values(series)
        fences = _fences(values, k)
        if fences is None:
            continue
        q1, q3, iqr, lower, upper = fences
        n_low, n_high = int((values < lower).sum()), int((values > upper).sum())
        result.append(
            OutlierSummary(
                str(name), q1, q3, iqr, lower, upper, n_low, n_high, (n_low + n_high) / len(values) * 100
            )
        )
    return tuple(result)


def zero_iqr_columns(df: pd.DataFrame) -> tuple[str, ...]:
    names = []
    for position, name in enumerate(df.columns):
        series = df.iloc[:, position]
        if _is_measure(series):
            values = _values(series)
            if len(values) >= MIN_OUTLIER_VALUES and _fences(values, K_MIN) is None:
                names.append(str(name))
    return tuple(names)


def outlier_rows(df: pd.DataFrame, column: str, k: float = 1.5) -> pd.DataFrame:
    _check_k(k)
    _check_columns(df, [column])
    series = df[column]
    if not _is_measure(series):
        raise ValueError(f"Column {column} is not numeric.")
    fences = _fences(_values(series), k)
    if fences is None:
        return df.iloc[0:0]
    lower, upper = fences[3], fences[4]
    numbers = series.astype("float64")
    mask = ((numbers < lower) | (numbers > upper)).to_numpy(dtype=bool, na_value=False)
    return df.loc[mask]


@dataclass(frozen=True)
class QualityReport:
    k: float
    missing: pd.DataFrame = field(compare=False, repr=False)
    duplicates: DuplicateReport = field(compare=False)
    constant_columns: tuple[ConstantColumn, ...] = ()
    outliers: tuple[OutlierSummary, ...] = ()
    zero_iqr: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "missing": [json_object(row) for row in self.missing.to_dict(orient="records")],
            "duplicates": self.duplicates.to_dict(),
            "constant_columns": [json_object(item) for item in self.constant_columns],
            "outliers": {
                "k": self.k,
                "columns": [json_object(item) for item in self.outliers],
                "zero_iqr": list(self.zero_iqr),
            },
        }


def quality_report(df: pd.DataFrame, k: float = 1.5, subset: Sequence[str] | None = None) -> QualityReport:
    return QualityReport(
        k=k,
        missing=missing_summary(df),
        duplicates=duplicates(df, subset),
        constant_columns=constant_columns(df),
        outliers=iqr_outliers(df, k),
        zero_iqr=zero_iqr_columns(df),
    )

"""Text downloads (docs/data-model.md, "Downloads"): two CSV dialects with formula escaping, a JSON and a Markdown profile.

Everything here is deterministic: no timestamps, sorted keys, floats rounded to six decimals.
"""

from __future__ import annotations

import json
import re
from pathlib import PureWindowsPath
from typing import Any, Literal

import pandas as pd

from data_explorer import __version__
from data_explorer.core import JSONValue, json_object
from data_explorer.core.filters import ViewSpec, format_filter
from data_explorer.core.io import LoadReport
from data_explorer.core.profile import ColumnProfile, DatasetProfile
from data_explorer.core.quality import QualityReport

Dialect = Literal["comma", "semicolon"]
ExportKind = Literal["csv", "json", "md"]
Scope = Literal["dataset", "view"]

SCHEMA_VERSION = 1
GENERATOR = f"data-explorer-app {__version__}"
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
MIME: dict[ExportKind, str] = {"csv": "text/csv", "json": "application/json", "md": "text/markdown"}
SUFFIXES: dict[ExportKind, str] = {"csv": "_filtered.csv", "json": "_profile.json", "md": "_profile.md"}
STEM_MAX = 60
DISALLOWED = re.compile(r"[^A-Za-z0-9_-]+")
DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}
DECIMAL_NAMES = {".": "point", ",": "comma"}
DASH = "–"


# --- CSV --------------------------------------------------------------------------------------


def _iso(series: pd.Series[Any]) -> pd.Series[Any]:
    values = series.dropna()
    if values.empty or bool((values == values.dt.normalize()).all()):
        pattern = "%Y-%m-%d"
    elif bool((values.dt.microsecond != 0).any()):
        pattern = "%Y-%m-%dT%H:%M:%S.%f"
    else:
        pattern = "%Y-%m-%dT%H:%M:%S"
    formatted: pd.Series[Any] = series.dt.strftime(pattern)
    return formatted


def _escape(series: pd.Series[Any]) -> pd.Series[Any]:
    text = series.astype("str")
    risky = text.str.startswith(FORMULA_PREFIXES, na=False).to_numpy(dtype=bool)
    return text.where(~risky, "'" + text)


def _escape_label(label: str) -> str:
    return "'" + label if label.startswith(FORMULA_PREFIXES) else label


def to_csv_bytes(df: pd.DataFrame, dialect: Dialect = "comma", escape_formulas: bool = True) -> bytes:
    """The frame as CSV: comma (UTF-8, decimal point) or semicolon (UTF-8 with BOM, decimal comma)."""
    if dialect not in ("comma", "semicolon"):
        raise ValueError(f"Unknown CSV dialect {dialect!r}; use comma or semicolon.")
    columns: dict[str, pd.Series[Any]] = {}
    for position, name in enumerate(df.columns):
        series = df.iloc[:, position]
        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            columns[str(name)] = _iso(series)
        elif pd.api.types.is_numeric_dtype(series.dtype) or pd.api.types.is_bool_dtype(series.dtype):
            columns[str(name)] = series
        elif escape_formulas:
            columns[str(name)] = _escape(series)
        else:
            columns[str(name)] = series
    frame = pd.DataFrame(columns, index=df.index)
    semicolon = dialect == "semicolon"
    # The labels are escaped on the way out and the keys of ``columns`` stay as they are: two labels that
    # escape to the same text must not merge into one column.
    header = [_escape_label(label) if escape_formulas else label for label in columns]
    text = frame.to_csv(
        index=False,
        header=header,
        sep=";" if semicolon else ",",
        decimal="," if semicolon else ".",
        lineterminator="\n",
        na_rep="",
    )
    return text.encode("utf-8-sig" if semicolon else "utf-8")


# --- file names -------------------------------------------------------------------------------


def export_file_name(source_name: str, kind: ExportKind) -> str:
    if kind not in SUFFIXES:
        raise ValueError(f"Unknown export kind {kind!r}; use csv, json or md.")
    name = PureWindowsPath(source_name.replace("/", "\\")).name
    stem = name.rsplit(".", 1)[0] if "." in name else name
    cleaned = DISALLOWED.sub("_", stem).strip("_")[:STEM_MAX].strip("_")
    return (cleaned or "dataset") + SUFFIXES[kind]


# --- profiles ---------------------------------------------------------------------------------


def _check_scope(scope: str) -> None:
    if scope not in ("dataset", "view"):
        raise ValueError(f"Unknown profile scope {scope!r}; use dataset or view.")


def profile_payload(
    report: LoadReport,
    profile: DatasetProfile,
    quality: QualityReport,
    view: ViewSpec,
    rows_in_view: int,
    *,
    scope: Scope = "dataset",
) -> dict[str, JSONValue]:
    _check_scope(scope)
    source = report.to_dict()
    warnings = source.pop("warnings", [])
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "source": source,
        "warnings": warnings,
        "shape": {
            "rows": profile.n_rows,
            "columns": profile.n_cols,
            "cells": profile.n_cells,
            "missing_cells": profile.missing_cells,
            "missing_cells_pct": profile.missing_cells_pct,
            "duplicate_rows": profile.duplicate_rows,
            "kinds": dict(profile.kinds),
        },
        "view": {
            "filter_text": format_filter(view.filter),
            "columns": None if view.columns is None else list(view.columns),
            "sort": [{"column": key.column, "descending": key.descending} for key in view.sort],
            "rows_in_view": rows_in_view,
            "scope": scope,
        },
        "columns": [column.to_dict() for column in profile.columns],
        "quality": quality.to_dict(),
    }
    return json_object(payload)


def profile_json(
    report: LoadReport,
    profile: DatasetProfile,
    quality: QualityReport,
    view: ViewSpec,
    rows_in_view: int,
    *,
    scope: Scope = "dataset",
) -> str:
    payload = profile_payload(report, profile, quality, view, rows_in_view, scope=scope)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def _cell(value: object) -> str:
    text = DASH if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _number(value: object) -> str:
    if value is None:
        return DASH
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return f"{value:,.0f}"
        if abs(value) >= 1:
            return f"{value:,.2f}"
        return f"{value:.4g}"
    return _cell(value)


def _pct(value: float) -> str:
    return f"{value:.1f} %"


def _code(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    if not longest:
        return f"`{text}`"
    fence = "`" * (longest + 1)
    return f"{fence} {text} {fence}"


def _table(header: list[str], align: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _most_frequent(column: ColumnProfile) -> str:
    if column.top:
        value, count = column.top[0]
        return f"{_cell(value)} ({count:,})"
    if column.kind == "boolean":
        return f"true {column.stats.get('true', 0):,} · false {column.stats.get('false', 0):,}"
    return DASH


def profile_markdown(
    report: LoadReport,
    profile: DatasetProfile,
    quality: QualityReport,
    view: ViewSpec,
    rows_in_view: int,
    *,
    scope: Scope = "dataset",
) -> str:
    _check_scope(scope)
    lines = [f"# Data profile: {_cell(report.file_name)}", ""]
    target = "the full dataset" if scope == "dataset" else "the current view"
    lines += [f"Generated by {GENERATOR}. Profile of {target}.", ""]

    renamed = ", ".join(f"{_code(old)} → {_code(new)}" for old, new in report.renamed_columns) or "none"
    lines += ["## Source", ""]
    lines += _table(
        ["Property", "Value"],
        ["---", "---"],
        [
            ["File", _cell(report.file_name)],
            ["Type", report.file_type.upper()],
            ["Size", f"{report.size_bytes:,} bytes"],
            ["SHA-256", f"`{report.sha256}`"],
            ["Encoding", _cell(report.encoding)],
            ["Delimiter", DELIMITER_NAMES.get(report.delimiter or "", DASH)],
            ["Decimal separator", DECIMAL_NAMES.get(report.decimal or "", DASH)],
            ["Sheet", _cell(report.sheet)],
            ["Header row", str(report.header_row + 1)],
            ["Renamed columns", _cell(renamed)],
            ["Date columns", _cell(", ".join(report.date_columns) or "none")],
            ["Blank cells read as missing", f"{report.blank_to_missing:,}"],
        ],
    )

    lines += ["", "## Shape", ""]
    missing = f"{profile.missing_cells:,} ({_pct(profile.missing_cells_pct)})"
    lines += _table(
        ["Rows", "Columns", "Missing cells", "Duplicate rows"],
        ["---:", "---:", "---:", "---:"],
        [[f"{profile.n_rows:,}", f"{profile.n_cols:,}", missing, f"{profile.duplicate_rows:,}"]],
    )
    kinds = " · ".join(f"{count} {kind}" for kind, count in profile.kinds.items() if count)
    lines += ["", f"Column kinds: {kinds}."]

    filter_text = format_filter(view.filter)
    sort = ", ".join(
        f"{_code(key.column)} {'descending' if key.descending else 'ascending'}" for key in view.sort
    )
    lines += ["", "## View", ""]
    lines.append(f"- Filter: {_code(filter_text) if filter_text else 'none, all rows are in the view'}")
    lines.append(
        f"- Columns: {', '.join(_code(c) for c in view.columns) if view.columns is not None else 'all'}"
    )
    lines.append(f"- Sort: {sort or 'none'}")
    lines.append(f"- Rows in view: {rows_in_view:,}")

    lines += ["", "## Columns", ""]
    lines += _table(
        ["Column", "Type", "dtype", "Missing %", "Unique", "Min", "Median", "Mean", "Max", "Most frequent"],
        ["---", "---", "---", "---:", "---:", "---:", "---:", "---:", "---:", "---"],
        [
            [
                _cell(column.name),
                column.kind,
                _cell(column.dtype),
                _pct(column.missing_pct),
                f"{column.unique:,}",
                _number(column.stats.get("min")),
                _number(column.stats.get("median")),
                _number(column.stats.get("mean")),
                _number(column.stats.get("max")),
                _most_frequent(column),
            ]
            for column in profile.columns
        ],
    )

    lines += ["", "## Missing values", ""]
    if quality.missing.empty:
        lines.append("No missing values.")
    else:
        lines += _table(
            ["Column", "Missing", "Missing %"],
            ["---", "---:", "---:"],
            [
                [_cell(row["column"]), f"{int(row['missing']):,}", _pct(float(row["missing_pct"]))]
                for row in quality.missing.to_dict(orient="records")
            ],
        )

    duplicates = quality.duplicates
    compared = "all columns" if not duplicates.subset else ", ".join(_code(c) for c in duplicates.subset)
    lines += ["", "## Duplicates", ""]
    lines.append(
        f"{duplicates.duplicate_rows:,} duplicate rows in {duplicates.groups:,} groups, compared on {compared}."
    )

    lines += ["", "## Constant columns", ""]
    if not quality.constant_columns:
        lines.append("None.")
    else:
        lines += _table(
            ["Column", "Value", "All missing"],
            ["---", "---", "---"],
            [
                [_cell(item.name), _cell(item.value), "yes" if item.all_missing else "no"]
                for item in quality.constant_columns
            ],
        )

    lines += ["", f"## Outliers (IQR rule, k = {quality.k:g})", ""]
    if not quality.outliers:
        lines.append("No numeric column with at least 4 values and an IQR above 0.")
    else:
        lines += _table(
            ["Column", "Q1", "Q3", "Lower fence", "Upper fence", "Below", "Above", "Share"],
            ["---", "---:", "---:", "---:", "---:", "---:", "---:", "---:"],
            [
                [
                    _cell(item.column),
                    _number(item.q1),
                    _number(item.q3),
                    _number(item.lower),
                    _number(item.upper),
                    f"{item.n_low:,}",
                    f"{item.n_high:,}",
                    _pct(item.pct),
                ]
                for item in quality.outliers
            ],
        )
    if quality.zero_iqr:
        lines += [
            "",
            "Skipped because the IQR is 0: " + ", ".join(_code(name) for name in quality.zero_iqr) + ".",
        ]

    if report.warnings:
        lines += ["", "## Warnings", ""]
        lines.extend(f"- {_cell(warning)}" for warning in report.warnings)
    return "\n".join(lines) + "\n"

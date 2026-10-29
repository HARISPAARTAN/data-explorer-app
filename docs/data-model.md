# Data model

Everything lives in memory. One session holds one `pandas.DataFrame` and the frozen dataclasses below; nothing is written to disk in either runtime, and a browser reload starts empty.

## In memory

| Type | Fields | Made by |
|---|---|---|
| `LoadReport` | `file_name`, `file_type` (`csv` or `xlsx`), `size_bytes`, `sha256`, `encoding`, `delimiter`, `decimal`, `sheet`, `sheets`, `header_row` (0-based), `n_rows`, `n_cols`, `renamed_columns`, `date_columns`, `blank_to_missing`, `warnings` | `core.io.load_table`, `core.io.load_sample` |
| `ColumnProfile` | `name`, `kind`, `dtype`, `count`, `missing`, `missing_pct`, `unique`, `stats`, `top` | `core.profile.profile_dataset` |
| `DatasetProfile` | `n_rows`, `n_cols`, `n_cells`, `missing_cells`, `missing_cells_pct`, `duplicate_rows`, `memory_bytes`, `kinds`, `columns` | `core.profile.profile_dataset` |
| `QualityReport` | `k`, `missing`, `duplicates`, `constant_columns`, `outliers`, `zero_iqr` | `core.quality.quality_report` |
| `ViewSpec` | `filter` (`FilterSpec`: `mode`, `conditions`), `columns` (`None` for all), `sort` (up to 3 `SortKey`) | the Explore page, `core.filters.parse_filter` |

`LoadReport`, `ColumnProfile`, `DatasetProfile` and `QualityReport` have `to_dict()`, which returns plain JSON values: NaN and NaT become `null`, timestamps ISO 8601 strings, floats are rounded to 6 decimals. A `ViewSpec` is written by `view_to_json` instead ([Filter JSON](#filter-json)). The session keys that hold these objects are listed in [architecture.md](architecture.md#session-state).

## Column kinds

| Kind | Rule | Statistics |
|---|---|---|
| `boolean` | bool dtype (text columns with only `true` and `false`, in any case, are read as booleans) | `true`, `false` |
| `numeric` | any other numeric dtype | `mean`, `std` (ddof 1), `min`, `p25`, `median`, `p75`, `max`, `zeros`, `negatives` |
| `datetime` | datetime dtype | `min`, `max`, `span_days` |
| `categorical` | anything else with at most 50 distinct non-missing values | the 5 most frequent values |
| `text` | anything else | the 5 most frequent values, `mean_length`, `max_length` |

## Reading files

Accepted: `.csv`, `.tsv`, `.txt` (delimited text) and `.xlsx`. Anything else, including legacy `.xls`, is refused with a message that names the file.

- Encoding: a byte order mark gives `utf-8-sig`; otherwise `utf-8` if the first MiB decodes, else `cp1252` if it decodes, else `latin-1`.
- Delimiter: `,`, `;`, tab or `|`, sniffed from the first 64 KiB.
- Decimal separator: `,` only when the delimiter is not `,` and at least 60 % of the number-like fields in the first 200 lines look like `1.234,56` or `3,5`.
- Excel: the sheet with the most non-empty cells in its first 200 rows.
- Header row, in CSV and Excel files: the first of the first 20 rows whose non-empty cells are all text and fill at least half of the widest row. The Upload page offers the row, the sheet, the encoding, the delimiter and the decimal separator under Reading options.
- Header names are stripped; an empty name becomes `column_<n>`, a repeated one gets `_2`, `_3`; every rename is listed in the report.
- Empty fields, the usual missing-value tokens and cells with only spaces become missing values.
- Dates: a text column becomes a datetime column when at least 95 % of its non-missing values parse with the first of these formats that does so: `%Y-%m-%d`, `%Y-%m-%d %H:%M`, `%Y-%m-%d %H:%M:%S`, `%Y-%m-%d %H:%M:%S.%f`, `%Y-%m-%dT%H:%M`, `%Y-%m-%dT%H:%M:%S`, `%Y-%m-%dT%H:%M:%S.%f`, `%d/%m/%Y`, `%d/%m/%Y %H:%M`, `%d/%m/%Y %H:%M:%S`, `%d.%m.%Y`, `%d.%m.%Y %H:%M`, `%d.%m.%Y %H:%M:%S`, tried in this order. ISO 8601 times with a UTC offset are converted to UTC, with a warning. Month-first dates are never inferred. Values that do not parse become missing, with a warning; a column that looks like dates but matches no format stays text, with a warning.
- Limits are checked before anything is cut: a file over a limit is refused, never truncated (see [Limits](#limits)).

## Filter grammar

A filter is a flat list of up to 10 conditions joined by one word: `AND` (every condition must hold) or `OR` (at least one). Mixing the two is a syntax error, and there are no parentheses ([ADR 0003](adr/0003-flat-filter-grammar.md)). Keywords are case-insensitive.

```text
filter    = condition , { joiner , condition } ;
joiner    = "AND" | "OR" ;
condition = column , ( compare | between | member | textop | nullcheck ) ;
column    = "`" , { character - "`" | "``" } , "`" ;
compare   = ( "=" | "!=" | "<" | "<=" | ">" | ">=" ) , literal ;
between   = "BETWEEN" , literal , "AND" , literal ;
member    = [ "NOT" ] , "IN" , "(" , literal , { "," , literal } , ")" ;
textop    = ( "CONTAINS" | "NOT CONTAINS" | "STARTS WITH" | "ENDS WITH" ) , string ;
nullcheck = "IS NULL" | "IS NOT NULL" ;
literal   = number | string | "TRUE" | "FALSE" ;
number    = [ "-" ] , digit , { digit } , [ "." , digit , { digit } ] ;
string    = '"' , { character - ( '"' | "\" ) | "\\" | '\"' } , '"' ;
```

| Kind | Operators |
|---|---|
| numeric | `=` `!=` `<` `<=` `>` `>=` `BETWEEN` `IN` `NOT IN` |
| datetime | `=` `<` `<=` `>` `>=` `BETWEEN` (dates are strings such as `"2025-03-01"` or `"2025-03-01 08:00"`) |
| boolean | `=` with `TRUE` or `FALSE` |
| categorical | `=` `!=` `IN` `NOT IN` `CONTAINS` `NOT CONTAINS` `STARTS WITH` `ENDS WITH` |
| text | `=` `!=` `CONTAINS` `NOT CONTAINS` `STARTS WITH` `ENDS WITH` |
| every kind | `IS NULL` `IS NOT NULL` |

Rules: a missing value matches only `IS NULL`, so `!=`, `NOT IN` and `NOT CONTAINS` leave it out too. Text operators ignore case. `BETWEEN` includes both ends. A date without a time means the whole day: `= "2025-03-01"` is that day, `<= "2025-03-31"` includes all of 31 March, `> "2025-03-31"` starts on 1 April. An empty filter keeps every row. The text form the app writes always backticks column names (a backtick inside a name is doubled), so reading it back gives the same filter.

## Filter JSON

The Explore page keeps its view (filter, columns, sort) as a `ViewSpec`. Its canonical JSON (sorted keys, no spaces) is the cache key of the filtered view. This filter, with the columns `store` and `units` and a descending sort on `units`:

```text
`units` BETWEEN 2 AND 10 AND `order_date` >= "2025-01-01"
```

gives:

```json
{"columns":["store","units"],"filter":{"conditions":[{"column":"units","op":"between","value":[2,10]},{"column":"order_date","op":"ge","value":"2025-01-01"}],"mode":"all"},"sort":[{"column":"units","descending":true}]}
```

The same, indented:

```json
{
  "columns": ["store", "units"],
  "filter": {
    "conditions": [
      {"column": "units", "op": "between", "value": [2, 10]},
      {"column": "order_date", "op": "ge", "value": "2025-01-01"}
    ],
    "mode": "all"
  },
  "sort": [{"column": "units", "descending": true}]
}
```

`op` is one of `eq`, `ne`, `lt`, `le`, `gt`, `ge`, `between`, `in`, `not_in`, `contains`, `not_contains`, `starts_with`, `ends_with`, `is_null`, `not_null`; `mode` is `all` (`AND`) or `any` (`OR`); `value` is a number, a string, `true`, `false`, a list (`between`, `in`, `not_in`) or `null` (the null checks).

## Samples

Three invented datasets ship inside the package (`src/data_explorer/samples/`), so the same path works in the wheel, the Docker image and the browser. `tools/make_data.py` generates them with the seed 20261029; the defects are planted in exact numbers on distinct rows, and duplicates are copies of rows without any other defect, so every count is independent. Each file is below 1 MB. The kinds are those the Overview page shows.

### Retail orders (`retail_orders.csv`)

Orders of a fictional homeware chain in eight Lombard cities, 1 January 2024 to 30 June 2025. UTF-8 with BOM, semicolons, decimal commas, dates as dd/mm/yyyy. 6,060 rows × 11 columns.

| Column | Kind | Contents |
|---|---|---|
| `order_id` | text | `ORD-000001` to `ORD-006000` |
| `order_date` | datetime | order day |
| `store` | categorical | Milan, Bergamo, Brescia, Como, Monza, Pavia, Varese, Lecco |
| `category` | categorical | Kitchen, Textiles, Lighting, Storage, Decor, Garden |
| `units` | numeric | 1 to 12, apart from the planted outliers |
| `unit_price_eur` | numeric | price per unit in euros |
| `discount_pct` | numeric | 0, 5, 10, 15 or 20 |
| `revenue_eur` | numeric | units × price × (100 − discount) / 100, two decimals |
| `payment` | categorical | Card, Cash, Voucher |
| `customer_type` | categorical | New, Returning |
| `country` | categorical | always IT |

Planted defects:

- 60 exact duplicate rows
- 180 missing discount_pct values
- 15 units values between 120 and 400 (IQR outliers)
- country is always IT

### Sensor readings (`sensor_readings.csv`)

Hourly climate readings of six office sensors over 60 days from 1 March 2025. cp1252, commas, decimal points, ISO timestamps. 8,640 rows × 9 columns.

| Column | Kind | Contents |
|---|---|---|
| `timestamp` | datetime | every hour, `YYYY-MM-DD HH:MM` |
| `sensor_id` | categorical | MX-1 to MX-6 |
| `room` | categorical | Caffè, Meeting room A, Meeting room B, Open space north, Open space south, Library |
| `temperature_c` | numeric | air temperature, one decimal |
| `humidity_pct` | numeric | relative humidity, one decimal |
| `co2_ppm` | numeric | 400 to 1,400, apart from the sentinel values |
| `occupancy` | numeric | people in the room; 0 outside working hours |
| `battery_pct` | numeric | sensor battery level |
| `firmware` | categorical | always 2.4.1 |

Planted defects:

- sensor MX-4 offline for 48 hours (temperature, humidity and CO2 missing)
- 30 further missing humidity_pct values
- 12 co2_ppm sentinel values of 9999
- firmware is always 2.4.1

### Client survey (`client_survey.xlsx`)

Satisfaction survey of a fictional service provider: an Excel workbook with a Responses and a Notes sheet. The header is on row 4, below two title rows and a blank row; the Notes sheet holds the question texts. 1,224 rows × 11 columns.

| Column | Kind | Contents |
|---|---|---|
| `response_id` | text | `R-0001` to `R-1200` |
| `submitted_at` | datetime | date and time of the answer |
| `industry` | categorical | Manufacturing, Retail, Logistics, Healthcare, Finance, Public sector |
| `company_size` | categorical | 1-9, 10-49, 50-249, 250+ |
| `region` | categorical | North, Centre, South, Islands |
| `satisfaction` | numeric | 1 to 5 |
| `nps` | numeric | 0 to 10 |
| `would_recommend` | categorical | Yes, No |
| `response_time_s` | numeric | 60 to 1,800 seconds, apart from the planted long times |
| `comment` | categorical | one of twelve fixed phrases, or empty |
| `survey_wave` | numeric | always 2025 |

Planted defects:

- 24 exact duplicate rows
- 37 missing satisfaction values
- 840 empty comments
- 10 response_time_s values above 20,000
- survey_wave is always 2025

## Test fixtures

`tools/make_data.py --fixtures` writes the small files in `fixtures/` that the tests read: one per encoding and delimiter (`utf8_comma.csv`, `utf8_bom_semicolon_decimal_comma.csv`, `cp1252_semicolon.csv`, `latin1_tab.tsv`, `pipe_delimited.txt`), an Excel file with the header below title rows and two sheets (`header_offset_two_sheets.xlsx`), awkward headers (`duplicate_and_blank_headers.csv`), mixed date formats (`dates_mixed.csv`), cells with only spaces (`whitespace_cells.csv`), cells that start like spreadsheet formulas (`formula_cells.csv`), the chart edge cases (`two_numeric_columns.csv`, `one_numeric_column.csv`) and the files that must be refused or give zero rows (`header_only.csv`, `empty.csv`, `not_a_table.bin`, `legacy.xls`).

## Downloads

| Download | Format |
|---|---|
| CSV, comma | delimiter `,`, decimal point, UTF-8 without BOM, `\n` line ends, a header row, no index, dates ISO 8601, a missing value as an empty field |
| CSV, semicolon | delimiter `;`, decimal comma, UTF-8 with BOM, otherwise the same; opens directly in Excel with Italian or German regional settings |
| Profile JSON | `schema_version` (1), `generator`, `source` (the load report without its warnings), `warnings`, `shape`, `view` (`filter_text`, `columns`, `sort`, `rows_in_view`, `scope`), `columns` (one profile per column), `quality` (missing values, duplicates, constant columns, outliers with `k`); indented by 2, sorted keys |
| Profile Markdown | `# Data profile: <file>`, then Source, Shape, View, Columns, Missing values, Duplicates, Constant columns, Outliers, and Warnings when the load gave any |

In both CSV dialects a text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets a leading `'`, so a spreadsheet shows it instead of evaluating it; numeric columns are never changed. The files are named `<stem>_filtered.csv`, `<stem>_profile.json` and `<stem>_profile.md`, where the stem is the uploaded file's name reduced to letters, digits, `_` and `-` (at most 60 characters, `dataset` if nothing is left). The profiles contain no timestamps, so the same input always gives the same bytes ([ADR 0005](adr/0005-text-only-downloads.md)).

## Limits

| Limit | Server | Browser |
|---|---|---|
| File size, rows, columns | 50 MB, 1,000,000, 500 (lower with environment variables) | 20 MB, 200,000, 200 |
| Filter conditions, sort keys, values offered for `IN` | 10, 3, the 200 most frequent | the same |
| Rows shown: preview, Explore table, outlier rows, duplicate sample | 100, 1,000, 200, 20 | the same |
| Charts: bins, bar categories, line series, scatter points, heatmap columns, missing-value blocks × columns | 5 to 100, top 50, 8, 5,000, 20, 100 × 50 | the same |

1 MB here is 1,048,576 bytes. The downloads always contain every row of the current view; only the tables on screen are cut, and the page says so.

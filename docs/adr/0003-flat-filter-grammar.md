# ADR 0003: Flat filter grammar

Status: accepted (2026-10-29)

## Context

Contributors build filters with widgets; analysts want to read, edit and paste them as text, and see them in the downloaded profile. Widgets and text must describe exactly the same filter, and the filter must give a stable cache key.

## Decision

A filter is a flat list of up to 10 conditions joined by one joiner, `AND` or `OR`, with no parentheses ([data model](../data-model.md#filter-grammar)). Columns are always backticked in the text form; strings are double-quoted with backslash escapes. A recursive-descent parser written for this grammar reports the position of the first error and what was expected there; a formatter writes the text form, and a hypothesis property checks that parsing the formatted text gives the original filter. Missing values match only `IS NULL`, and dates without a time mean the whole day. The canonical JSON of the view is the cache key.

## Consequences

- Every filter the widgets can build has one text form, and every valid text loads back into the widgets.
- A filter such as A AND (B OR C) cannot be written; `IN` covers the common case of several values in one column, and the download can be filtered again.
- Error messages point at a character position, which the Explore page shows.

## Alternatives considered

- pandas `query` strings: evaluate expressions, which is a risk on a shared server, and cannot be shown as widgets.
- A full boolean grammar with parentheses: the widgets could not show nesting simply.
- SQL through an embedded database: one more engine to pin and test in both runtimes.

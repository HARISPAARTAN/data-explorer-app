# ADR 0005: Text-only downloads

Status: accepted (2026-10-29)

## Context

Users take the filtered data back into Excel, with Italian, German or English regional settings, and analysts attach a profile of the file to a ticket. Downloads must be safe to open and easy to test.

## Decision

The app offers text downloads only: the current view as CSV in two dialects (comma with UTF-8, or semicolon with decimal comma and UTF-8 with BOM), and the profile as JSON and as Markdown ([data model](../data-model.md#downloads)). Text cells that start like a formula get a leading apostrophe in both CSV dialects. The profiles are deterministic: no timestamps, sorted keys, fixed rounding.

## Consequences

- The semicolon dialect opens directly in Excel with Italian or German settings; the comma dialect suits English settings and other tools.
- Dates arrive as ISO 8601 text, which Excel recognises; there is no formatting.
- Golden-file tests compare the profile byte for byte.

## Alternatives considered

- XLSX downloads: binary files that are harder to compare in tests, plus a second write path for styles and formulas.
- PDF reports: a layout engine in both runtimes for a document the Markdown profile already covers.

# Administrator CSV exports

The Administrator **Export CSV** button downloads the readable layout. The same
existing authenticated endpoint supports both layouts:

- `/api/fr13/reports/export.csv?reportType=payments&layout=readable`
- `/api/fr13/reports/export.csv?reportType=payments&layout=legacy`

Omitting `layout` on the Backend API retains the original legacy layout and file
name. The `/api/fr13/reports/export?format=csv` alias also supports `layout`.
The portal defaults to readable; its existing download URL accepts `layout=legacy`
for callers that need the previous layout. All existing filters are forwarded.
Unknown layouts are rejected before loading report data.

## Readable layout

The report title matches the selected type: system summary, users, packages,
campaigns, feedback, bookings or payments. Report information and source limits
precede summary metrics and the final detailed-record table. There is no trailing
end-of-report record. Every CSV row has the same number of columns, with blank
padding in the information and summary sections. CSV cannot store styling,
column widths, frozen headers or filters.

Detailed fields have explicit, ordered human-readable headings for each report
type. The headings describe existing source fields; operator IDs are not presented
as business names. Alternate stored fields have separate columns so no value is
overwritten. Additional sanitized fields follow the stable columns in sorted order,
labelled with both a readable name and the original key in brackets. Nested
objects/lists use Unicode JSON. This preserves all exported fields without
introducing a database projection or dropping historical fields.

Null/missing values are blank; zero and false remain distinct. Amounts are not
recalculated, rounded or reformatted. Dates retain their source format, timezone
and precision; no unavailable dates are invented. UTF-8 BOM and CRLF records
support Excel import. Standard CSV quoting preserves embedded commas, quotes and
newlines as a single record. Spreadsheet formula prefixes are neutralized with
an apostrophe, including fields in metadata and headings. Existing recursive
sensitive-field exclusion remains applied before export.

Excel may infer numeric identifiers, dates or long numbers when opening CSV
directly. Use **Data → From Text/CSV**, choose UTF-8, and import identifier columns
as Text to retain leading zeros and long IDs. CSV cannot enforce spreadsheet cell
types or guarantee native numeric precision in Excel. The UTF-8 file itself
retains the source text and available precision.

## Scope and financial interpretation

The existing service loads at most 500 records per source category and exports
at most 200 matching detailed records. The readable report states the actual
limit flags, matching count and exported count. Summary values cover the filtered
loaded source scope and can exceed the displayed detail count. Reaching a source
cap does not establish complete system coverage.

All summary metrics come directly from the existing report payload. The export
does not recompute aggregations. Paid MYR totals include their reported test-mode
portion; that portion is not additional income. No real settlement or supplier
reservation is implied. Active campaigns are a subset of approved campaigns;
feedback moderation categories may overlap. Booking detail may combine hotel
bookings and package payment projections according to the existing service.

## Optional Excel export

Deferred: the Backend runtime requirements contain no XLSX writer. Adding a
runtime dependency and a separate download contract is unnecessary for the CSV
fix. A future isolated XLSX enhancement can provide typed cells, an overview
sheet, formatted detail tables, widths, wrapping, autofilters and frozen headers.
The CSV and PDF routes remain available.

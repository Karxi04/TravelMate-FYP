# Administrator spreadsheet exports

## Download choices

- **Export Excel (.xlsx)** is the recommended styled report. It follows the supplied
  reference: merged pink title/information block, green column headers, cyan
  numbered rows, wrapped text, borders, alternating row shading, frozen headings
  and first column, and filters. Identifiers are written as text.
- **Export CSV (.csv)** uses the compact layout: readable metadata, one explicit
  header row and numbered data rows. CSV cannot store colours, merges, widths,
  multiple sheets or cell types.
- **Advanced CSV (all fields)** retains the PR85 readable layout, including every
  sanitized additional field. This is the complete-field compatibility download.
- Existing API callers still receive the original legacy CSV unless they choose
  a layout explicitly.

## Existing and additional contracts

All routes remain authenticated Administrator-only and use the same report
criteria, summary service, sensitive-field redaction and record-limit policies.

- Existing CSV: `/api/fr13/reports/export.csv?reportType=payments`
- Original legacy CSV: same URL with `layout=legacy`
- Advanced PR85 layout: same URL with `layout=readable`
- Compact CSV: same URL with `layout=compact`
- Styled Excel: `/api/fr13/reports/export.xlsx?reportType=payments`
- Existing export alias accepts `format=csv` or `format=xlsx`.
- The existing portal download URL forwards these options and all report filters.
  Its CSV default is compact. Invalid layouts fail before loading records.

PDF exports and their generators are unchanged.

## Compact primary views

Payments with a known all-MYR loaded scope have eight columns:
No., Order Reference, Product Type, Product Name, Amount (MYR), Payment Status,
Test Mode and Created Date. Mixed, missing or unknown currencies retain a
separate Currency column; the export never assumes MYR from missing data.

Other report types use their own small, explicit presentation schemas. Optional
booking dates, participant counts, types and statuses are omitted when absent
throughout the loaded scope. Hotel costs and currency use the existing
`hotelCost`/`hotelCurrency` fields when canonical amount/currency are absent.
Booking status remains separate from payment status. Existing snapshot names
are used when a generic or missing product title needs a factual fallback.

System Summary CSV contains only No., Category, Metric and Value, from the
existing counts and summary payload. It does not append mixed technical records.
Excel starts with **System Overview** and partitions the available exported
records into logical category sheets. Grouping uses explicit populated record
fields; ambiguous/unclassified rows remain in **Other Records**. Each exported
record appears once. These sheets describe only the already-capped detail payload,
not all source-category records. Other report workbooks have a primary details
sheet and a separate Report Summary sheet.

No arbitrary backend fields are added to primary tables. Full original
sanitized fields remain accessible through Advanced CSV and legacy CSV.

## Values, security and scope

Missing/null is blank, zero remains zero, and test mode is Yes/No only when the
source supplies a boolean. Sequence numbers are display-only, never identifiers.
No business values or financial totals are recomputed. Metadata distinguishes
matching count, exported detail count and rows on each worksheet.

Timezone-aware timestamps are displayed in UTC. Naive historical date strings
stay as recorded. The advanced and legacy exports retain original date text.
Amounts use numeric cells when Excel can represent the available significant
digits; values beyond Excel's 15-digit precision are retained as text. Display
formats retain cents and available extra decimal places. No currency conversion
is performed. Dates and exact source precision remain available in Advanced CSV.

CSV uses UTF-8 BOM, standard quoting and spreadsheet-formula neutralization.
XLSX writes source strings explicitly as text and disables formula, numeric-string
and URL conversion. No macros or external links are generated. Text exceeding
Excel's 32,767-character cell limit fails explicitly with an Advanced CSV hint
instead of silently truncating data.

The existing 500-per-source and 200-detail limits are unchanged. Source caps,
incomplete exports and test-mode financial disclosures remain visible. Summary
metrics can exceed displayed detail counts because they cover filtered loaded
source scope. Active and approved campaign categories overlap; feedback moderation
categories may overlap. Paid test-mode records are not real income or independent
supplier reservation confirmation.

## Runtime dependency and verification

The explicit added Backend dependency is `XlsxWriter>=3.2,<4`, tested with 3.3.1.
It is a focused write-only XLSX library supporting in-memory output and disabled
automatic formula/URL conversion:
https://xlsxwriter.readthedocs.io/workbook.html

Install updated Backend requirements through the owner's approved deployment
procedure before enabling the new Excel route. Development verification installed
the writer only in a task-specific D-workspace dependency directory. No protected
running environment or service was changed.

Excel itself opened generated workbooks read-only and rendered them for visual
inspection, in addition to isolated tests of XML styles, values, quoting, filters,
freeze panes, limits, authorization and compatibility. No source records were
loaded from production Firebase for this work.

# Assignment 2 Phase 0 audit

## A. Dataset overview

- 120 student IDs identified against an expected 120.
- 129 original attachments make up 128 submission versions. 7 students submitted multiple versions.
- 120 latest versions selected and 8 superseded. Version decisions pending: 0. Unidentified versions: 0.
- The numeric export groups were cross-checked against attachment labels, member paths and item or student ID fields when available. No independent class roster was supplied. The folder count verifies coverage against the reported headcount.
- All 129 extracted attachments matched the original bulk ZIP members by path and SHA-256. Each was counted once. A second SHA-256 check confirmed the bulk ZIP and attachments retained the same contents.
- The bulk ZIP SHA-256 is `254df7ad7e0198da9bcd9df01241ed858e237a36b355321edaef11fe9c736b81`.

## B. Dataset counts

| Count | All versions | Selected versions |
|---|---:|---:|
| Marketplace data rows, one representation per version | 1,921 | 1,801 |
| Marketplace candidate rows, including alternate tables | 2,026 | 1,906 |
| Supporting provenance table rows identified | 109 | 109 |
| Standalone image files | 1,923 | 1,803 |
| Readable standalone images | 1,923 | 1,803 |
| Unreadable standalone image files | 0 | 0 |
| Images with extension differing from decoded format | 182 | 167 |
| Unreadable or unrecognized table files | 0 | 0 |
| Other unreadable or ambiguous archive entries | 0 | 0 |
| Embedded workbook media entries | 15 | 15 |
| Explicit local photo references | 1,831 | 1,711 |
| Resolved local photo references | 1,813 | 1,693 |
| Resolved references to readable images | 1,813 | 1,693 |
| Of resolved references, linked by unique stem | 184 | 124 |
| Of resolved references, linked by normalized stem | 77 | 62 |
| Missing local references after filename/stem lookup | 18 | 18 |
| Ambiguous local photo references | 0 | 0 |
| External photo references | 0 | 0 |
| Rows without explicit photo | 90 | 90 |
| Inferred item-to-file links | 109 | 109 |
| Rows with at least one direct or inferred file link | 1,920 | 1,800 |
| Files linked from multiple rows | 0 | 0 |
| Image files without a direct or inferred link | 1 | 1 |
| Distinct standalone image SHA-256 hashes | 1,801 | 1,801 |
| Byte-identical image groups | 105 | 2 |
| Image files in byte-identical groups | 227 | 4 |
| Case-insensitive basename collision groups | 87 | 72 |
| Rows with a nonblank item ID | 1,906 | 1,786 |
| Distinct observed nonblank item ID strings (unambiguous ID lists) | 165 | 165 |
| Item ID strings shared across versions in scope | 67 | 52 |

Ranges cover alternative marketplace tables. Rows are parsed, non-empty item records, excluding headers, blank rows, and entries without item evidence. The manifest identifies candidate, preamble and footer evidence. Candidate-row totals include alternate exports of the same items. Workbook media entries and standalone images use distinct counts. System artifacts are listed in the issues CSV.

Photo references count cell entries naming a local file, including multiple names in one cell when present. Resolution uses exact archive paths or unique basename matches. Unique stems and separator or repeated extension variants are flagged. Item ID inference uses a unique full stem or a complete one-to-one number match within a submission. A missing explicit filename can coexist with an inferred item-to-file link. Unreferenced files are those without either a resolved local name or an inferred association. SHA-256 groups count byte equality among standalone images. The audit did not measure visual similarity or verify the photographed object against the listing. Distinct item ID strings are a preliminary check because student-specific IDs can be missing or repeated.

## C. Schema overview

Observed formats across 120 chosen or unresolved candidate tables: CSV (86), XLSX (33), semicolon-delimited (1).

| Field | Headers observed | Files or sheets lacking the field |
|---|---|---:|
| item id | `ID`, `Id`, `Item ID`, `Item_ID`, `item ID`, `item id`, `item_id` | 1 |
| photo | `Image`, `Item Image`, `Item Photo`, `Item Photo (filename)`, `Item photo`, `Item_Photo`, `Item_photo`, `Photo`, `Photo Filename`, `image_file`, `image_filename`, `item Photo`, `item_photo`, `photo` | 6 |
| title | `Title`, `title` | 0 |
| description | `Descreption`, `Description`, `description` | 0 |
| category | `Category`, `category` | 0 |
| age | `Age`, `Age (Year)`, `Age (Years)`, `Age (years)`, `Approximate age`, `age`, `age_years`, `approximate_age_years` | 0 |
| condition | `Condition`, `Condition (1-5)`, `Condition (1–5)`, `condition`, `condition(1-5)` | 0 |
| price | `Price`, `price` | 0 |
| currency | `Currency`, `currency` | 1 |
| unmapped | `link` | — |
- **Item id**. integer text (105), text (1681).
- **Age**. Excel float (72), Excel int (329), decimal text (219), integer text (744), text (62).
- **Condition**. Excel int (461), decimal text (15), integer text (1268), text (37).
- **Price**. Excel float (27), Excel int (463), decimal text (144), integer text (1118), text (16).
- **Currency**. decimal text (15), integer text (6), text (1745).
- **Photo**. text (1711).

## D. Important findings

- The expected class baseline is 1,800 rows and 1,800 standalone images. The audit verified **1,803 standalone image files**, a difference of **+2** from the reported 1,801.
- The selected set has **1,801 distinct image hashes** across 1,803 physical files. A total of 4 files belong to 2 byte-identical groups. The counting method behind the original report is unknown.
- Price, currency, age, and condition were inspected as recorded. The source uses numeric spreadsheet cells and numeric or qualified text. Age headers mix unspecified units with explicit years, and age values include other unit wording. The issues CSV records representative formats and row locations for Phase 1 and Phase 2.

| Attachment reference | Candidate item rows | Images | Resolved refs | Missing refs | Unreferenced files |
|---|---:|---:|---:|---:|---:|
| [identifier] | 15 | 17 | 14 | 1 | 0 |
| [identifier] | 16 | 16 | 16 | 0 | 0 |

- Attachment `[identifier]` has 17 files and 15 item rows. Worksheet row 12 names an absent single file. Its matching item-specific folder contains 3 images with 3 distinct hashes. The folder supports an association with that row, pending review of the individual photos.

- The 16-image submission (attachment `[identifier]`) has 16 marketplace rows and 16 resolved references, with 16 distinct image hashes within the submission. The extra file corresponds to an extra item row.

## E. Decisions and unresolved issues

- **Chronology.** Bulk ZIP member timestamps and numbered attachment labels agree. All attachment numbers unique and seven digits: yes. Timestamp regressions in increasing attachment order: 0. ZIP time is recorded as export evidence. Official submission-system times and timezone were unavailable. The extracted file timestamps and submission completeness played no part in selection.
- **Split submission.** The simultaneously exported `dataset.csv` and `images.zip` contain complementary data and images for the same export group. The manifest records both paths under one version.
- **Table selection.** The audit compares field meanings, row contents, newline encodings and plain numeric representations to recognize equivalent CSV and Excel exports. Explicit Excel thousands formatting can explain a match. Non-equivalent marketplace candidates stay visible for review. Ancillary provenance files and workbook sheets stay outside the marketplace count.
- **Resolved table discrepancy for attachment `[identifier]`.** ZIP member clocks show 2026-10-28T21:01:10 for CSV and 2026-10-28T21:09:34 for Excel. The workbook records its own modification time as 2026-10-28T19:09:33Z. ZIP clocks have no stored timezone. The timestamps support a later workbook save. The CSV lacks an independent revision record. Source row 7 differs in currency (CSV AED, Excel ILS). Source row 13 differs in age (CSV blank, Excel Unknown). Excel is authoritative and both original files are preserved.
- **Later review.** Investigate missing, inferred and mismatched photo links in Phase 1. Check missing values, duplicate IDs, byte-identical images and questionable values in Phase 2. Preserve the original records.

## F. Readiness assessment

**Ready for Phase 1 with documented issues.** Phase 1 can begin upon approval of this audit.

The audit inspected the three-page assignment brief and the 76-page lecture chapter. It uses the lecture's distinction between structured and unstructured data, schema integration, and checks for incomplete, noisy and inconsistent data. Phase 0 produced no integrated dataset, cleaning or EDA.

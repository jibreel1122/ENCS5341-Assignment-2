# Assignment 2 Phase 1 integration audit

## Input and output

- Integrated 120 approved latest tables from 129 catalogued attachments and 128 submission versions. The 8 superseded versions were excluded from integration. The authoritative workbook decision in Phase 0 was carried through.
- Exported **1,801 observations**, **120 students**, **132 raw category strings**, and **21 columns**. Category counts use exact non-empty source strings. Blank or whitespace-only category fields occur on 1 row(s). Case, spelling, and spacing variants can inflate the count before cleaning.
- Per-student row counts are 15 rows for 119 student(s), 16 rows for 1 student(s). The combined count agrees with the Phase 0 manifest. Input formats were CSV (86), XLSX (33), semicolon-delimited (1).
- SHA-256 for the unchanged CSV baseline is `27a07b988858d3393f20dee6c07fed389a721f04834a2104fc9e00488b5a24af`.

## Unified schema and source mappings

| Unified column | Source headers |
|---|---|
| `original_item_id` | `ID`, `Id`, `Item ID`, `item ID`, `item id`, `Item ID `, `Item_ID`, `item_id` |
| `title` | ` Title`, `Title`, `title`, `Title ` |
| `description` | ` Description`, `Descreption`, `Description`, `description`, `Description ` |
| `category` | ` Category`, `Category`, `category` |
| `age_raw` | ` Age`, `Age`, `age`, `Age `, `Age (Year)`, `Age (Years)`, `Age (years)`, `age_years`, `Approximate age`, `approximate_age_years` |
| `condition_raw` | ` Condition`, `Condition`, `condition`, `Condition `, `Condition (1-5)`, `Condition (1–5)`, `condition(1-5)` |
| `price_raw` | ` Price`, `Price`, `price`, `Price ` |
| `currency_raw` | ` Currency`, `Currency`, `currency`, `Currency ` |
| `listing_link_raw` | `link` |
| `image_reference_raw` | `Image`, `image_file`, `image_filename`, `Item Image`, `Item Photo`, `Item photo`, `item Photo`, `Item Photo (filename)`, `Item_Photo`, `Item_photo`, `item_photo`, `Photo`, `photo`, `Photo Filename` |

Full column order: `record_id`, `student_id`, `submission_id`, `source_table`, `source_sheet`, `source_row`, `original_item_id`, `title`, `description`, `category`, `age_raw`, `age_header_unit`, `condition_raw`, `price_raw`, `currency_raw`, `listing_link_raw`, `image_reference_raw`, `image_status`, `image_links`, `image_flags`, `source_extras`.

- **Source provenance.** `student_id` and `submission_id` come from the manifest. `source_table` is a JSON array starting with a path relative to the source root, followed by exact archive member paths. `source_sheet` names the worksheet when present. `source_row` is the one-based worksheet row or the first physical line of the delimited record.
- **Identifiers.** All 1,801 generated IDs are unique. `record_id` uses the approved submission identifier and the source row. `original_item_id` preserves the source text and leading zeros. There are 166 distinct nonblank original ID strings across 1,786 rows, including 52 repeated strings. 15 rows have no original ID. The Phase 0 comparison trimmed surrounding spaces and counted 165 distinct IDs. The export preserves the exact strings.
- **Value types.** Source values are strings in UTF-8 CSV. Exact delimited text, spacing, placeholders, currency labels, and invalid-looking values were retained. Spreadsheet cells are serialized from their stored values. The intended later types are numeric price, numeric age with an explicit unit, and a 1–5 ordinal condition rating. `age_header_unit` records years only where the source header declares it. Unspecified units stay blank, and units written in the age cell stay in `age_raw`.
- **Schema gaps.** Photo references are absent from 6 selected schemas, item IDs from 1, and currency from 1. Missing columns yield empty CSV fields. Listing links retain their own field. `source_extras` stores compact JSON for additional cells, embedded hyperlinks, and the original parsed sequences of structurally aligned rows.

## Structural integration decisions

- Recovered 12 quoted descriptions with leading layout whitespace. The closing quote and the five trailing fields establish the boundaries.
- Recovered the identifiable trailing fields on 12 rows with unquoted prose commas. The remaining title and description fragments have no reliable boundary. The first text cells stay literal and the original fragment sequence is in `source_extras`. The local issue inventory identifies the affected source rows.
- Preserved additional populated source cells on 1 row(s) and embedded worksheet hyperlinks on 30 rows. Blank worksheet rows and identified non-item notes remain in their source files. No observation was removed to reconcile an expected count.

## Image associations

| Record association | Rows |
|---|---:|
| Confirmed | 1,507 |
| Plausible | 293 |
| Ambiguous | 0 |
| Missing | 1 |

- Verified 1,803 submission-scoped image locators and 1,801 distinct SHA-256 hashes. Phase 0 decoded 1,803 images from the same verified attachment bytes. The resulting dataset carries 1,802 image links. Unlinked standalone image files total 1.
- `image_reference_raw` preserves the source reference. `image_links` holds JSON objects with an exact relative locator and the association method. `image_flags` records missing reference or recovery evidence even when a plausible file was found. Each locator is scoped to its original attachment, which prevents cross-submission filename collisions.
- Confirmed means the recorded path or a uniquely matching complete filename identifies a file in the submission. Plausible links use a unique stem, normalized separators or extensions, an item-ID match, a complete numeric pairing, or an item-specific folder. Confirmation is about the file reference. The audit did not verify visual correspondence with the marketplace listing.
- Association methods by file link: `exact_path` (731), `filename` (776), `item_id_folder` (3), `item_id_sequence` (31), `item_id_stem` (75), `normalized_stem` (62), `stem` (124).
- 18 rows still have an unmatched explicit filename. Inferred links are labeled in the CSV.
- 1 row(s) carry multiple associations. The matching item-ID folder contains 3 photos in total. The original explicit references remain in the CSV.
- Unresolved record IDs: `[identifier]`.
- The remaining image has no corresponding explicit path, filename, or item-ID key. The image metadata yielded no item-specific identifier. A single leftover image and record are insufficient evidence. Both remain available locally.

## Source preservation checks

- Reopened all 120 original selected tables and compared 1,801 rows against their CSV records. The check covers mapped fields, untouched fragments, recovered suffixes, extra cells, hyperlinks, source locations and image evidence.
- Price headers observed: ` Price` (1), `Price` (109), `Price ` (2), `price` (8). Qualified headings total 0. The 1 source table(s) without a currency column account for 15 rows. Their price headers supply no currency value.
- Age headers observed: ` Age` (1), `Age` (91), `Age ` (1), `Age (Year)` (1), `Age (Years)` (1), `Age (years)` (17), `Approximate age` (1), `age` (2), `age_years` (4), `approximate_age_years` (1). Years are explicit in 24 tables and 360 rows. The other 1,441 rows have no header-declared unit.
- Verified all 12 unquoted rows and 12 quoted repairs against the original cells. All 6 of 6 recovered unquoted category labels also occur on intact source rows.
- Excel item ID cells include 496 non-empty text IDs and 0 numeric IDs. The 15 zero-prefixed numeric strings were verified verbatim. No numerical display conversion was needed.
- The source check reproduced the association statuses for 1,801 rows. It enforces a complete explicit filename match for confirmed single-file links.
- The counts above are calculated at runtime. Structural recovery is rule-based. The approved workbook choice is recorded in the Phase 0 manifest and keyed to the two original file hashes.

## Validation and readiness

- Checked the bulk export hash and all 129 original attachment contents before and after integration. Read only the exact tables and images listed in the approved manifest during integration.
- Read the exported UTF-8 CSV using the standard library. Verified the column order, generated ID uniqueness, every field's round-trip value, and each selected student's row count. The writer emits a deterministic record and column order. Identical reruns leave the existing raw baseline in place.
- The issue inventory retains the Phase 0 entries and adds source-specific Phase 1 findings. **Ready for Phase 2 with documented issues.** The raw CSV is the baseline. Later cleaning belongs in a separate output.

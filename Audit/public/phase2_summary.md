# Assignment 2 Phase 2 data quality assessment

## Baseline and scope

- Verified 1,801 observations, 120 students, 21 columns and 1,801 unique record IDs. The raw data contain 132 nonblank category labels and 166 distinct nonblank exact original IDs.
- The raw CSV matched Phase 1 SHA-256 before and after the assessment. The digest is `27a07b988858d3393f20dee6c07fed389a721f04834a2104fc9e00488b5a24af`. Verified all 129 original attachments against their export and hashed the 1,803 selected standalone images. Parsed values were used only in memory.
- Assignment 2 §3 defines the required assessment. Assignment 1 §§2 and 4 specify approximate age in years and require a recorded currency, with no default. Assignment 1 §5 defines the five condition labels. The lecture informs missing-value treatment, sample standard deviation, Pearson's second skewness and IQR review.

## Missing and incomplete values

| Column | Total | Empty | Whitespace | Placeholder | Empty metadata or format only | Absent source column | Missing / absent | Percent | Available | Interpretation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `record_id` | 1,801 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% | 1,801 | Identifier or provenance |
| `student_id` | 1,801 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% | 1,801 | Identifier or provenance |
| `submission_id` | 1,801 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% | 1,801 | Identifier or provenance |
| `source_table` | 1,801 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% | 1,801 | Identifier or provenance |
| `source_sheet` | 1,801 | 1,305 | 0 | 0 | 0 | 0 | 1,305 | 72.46% | 496 | Optional or not applicable |
| `source_row` | 1,801 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% | 1,801 | Identifier or provenance |
| `original_item_id` | 1,801 | 15 | 0 | 0 | 0 | 15 | 15 | 0.83% | 1,786 | Identifier or provenance |
| `title` | 1,801 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% | 1,801 | Analytical attribute |
| `description` | 1,801 | 1 | 0 | 2 | 0 | 0 | 3 | 0.17% | 1,798 | Analytical attribute |
| `category` | 1,801 | 1 | 0 | 0 | 0 | 0 | 1 | 0.06% | 1,800 | Analytical attribute |
| `age_raw` | 1,801 | 373 | 0 | 12 | 0 | 0 | 385 | 21.38% | 1,416 | Analytical attribute |
| `age_header_unit` | 1,801 | 1,441 | 0 | 0 | 0 | 0 | 1,441 | 80.01% | 360 | Optional or not applicable |
| `condition_raw` | 1,801 | 15 | 0 | 5 | 0 | 0 | 20 | 1.11% | 1,781 | Analytical attribute |
| `price_raw` | 1,801 | 29 | 3 | 1 | 0 | 0 | 33 | 1.83% | 1,768 | Analytical attribute |
| `currency_raw` | 1,801 | 21 | 2 | 12 | 0 | 15 | 35 | 1.94% | 1,766 | Analytical attribute |
| `listing_link_raw` | 1,801 | 1,786 | 0 | 0 | 0 | 1,786 | 1,786 | 99.17% | 15 | Optional or not applicable |
| `image_reference_raw` | 1,801 | 90 | 0 | 0 | 0 | 90 | 90 | 5.00% | 1,711 | Image evidence |
| `image_status` | 1,801 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00% | 1,801 | Image evidence |
| `image_links` | 1,801 | 0 | 0 | 0 | 1 | 0 | 1 | 0.06% | 1,800 | Image evidence |
| `image_flags` | 1,801 | 0 | 0 | 0 | 1,507 | 0 | 1,507 | 83.68% | 294 | Optional or not applicable |
| `source_extras` | 1,801 | 0 | 0 | 0 | 1,746 | 0 | 1,746 | 96.95% | 55 | Optional or not applicable |

Absent source columns are a subset of the missing/absent count. Optional fields include CSV worksheet names, optional links, and empty JSON for flags or extra cells. A raw photo field may be absent while an associated file is available. The image status distinguishes these cases. Zero stays a recorded value.
- 431 rows have a missing analytical field. Missing age affects 62 submissions. A maximum of 15 ages are missing in one submission. 3 affected submissions have no age values.
- Recorded age placeholders are Unknown (2), Unkown (8), unkown (2).
- Highest missing ages by exact raw category are `Electronics` 60/361, `Clothing and accessories` 37/169, `Furniture` 35/178.
- Available analytically comparable price and age pairs total 1,361. Price and valid condition pairs total 1,720, and price and nonblank category pairs total 1,740. These availability counts still require currency-specific comparison.

## Duplicate assessment

| Evidence | Groups | Affected records |
|---|---:|---:|
| Exact original ID within a submission | 0 | 0 |
| Exact original ID across students | 52 | 1,672 |
| Likely ID formatting collision within a submission | 0 | 0 |
| Different representations of the same normalized ID across students | 30 | 1,725 |
| Exact values across the seven item attributes | 0 | 0 |
| Same normalized title and description | 0 | 0 |
| Same recorded listing address or workbook hyperlink target | 0 | 0 |
| Shared normalized title only (insufficient evidence) | 20 | 42 |

- Byte-identical photo files form 2 groups of 4 files across 4 item records. 2 groups cross submissions. 0 individual paths were linked to multiple records. Exact photo reuse with agreeing item context and prices merits review, but does not by itself establish the same listing.
- Found 35 additional item pairs with compatible category family, currency, amount or a possible grouping interpretation, and strong text or model-token evidence. Used 64-bit adjacent-pixel dHash only on these candidate pairs. 35 pairs had nonidentical files to compare, and 14 met the distance threshold of 5 bits. Review listing identity before excluding observations. Similar models can be legitimate separate items.
- Optional listing links by source form are worksheet hyperlink target (15). The comparison uses saved worksheet targets where the cell has display text. No links were fetched.

## Representation and validity findings

- **Category.** The proposed map covers all 1,801 records (missing (1), proposed (1,633), retain (102), review (65)). 41 rows have outer spaces. Case, accents, spacing, equivalent conjunctions, and reviewed singular/plural or synonym pairs share a proposal. Specific product subcategories stay distinct. Category families pool related labels only for diagnostics. 65 rows have broad or overlapping labels and 4 have product-title cues warranting category review.
- **Currency.** Recorded forms and their proposed code mappings are in the value-frequency table. Resolved diagnostic currencies are AED (9), AUD (1), CHF (19), EGP (6), EUR (23), GBP (54), ILS (1,218), INR (1), IQD (1), JOD (10), LYD (1), SAR (4), SEK (1), SGD (7), TWD (2), USD (399). ILS, NIS, Shekel and ₪ are equivalent labels. Dollar alone leaves the currency unresolved. The 1 table(s) without a currency column contribute 15 rows. In those rows the text or price fields contain 0 explicit code/symbol cues and 0 listing links. Phase 1 found no currency in price headers.
- **Age.** 360 rows have a header declaring years. For plain numbers in other headers (1,441 total rows with unspecified headers), Assignment 1 supplies the intended unit. Explicit units in cells take precedence. Only definite month values were expressed in years for diagnostics. Ranges, ambiguous units and narrative conflicts are reviewed separately. Observed assessment forms are missing (385), months (6), numeric (1,388), unit typo review (1), years text (21).
- **Condition.** Assessed forms are assignment label (15), integer (1,720), integer format (30), missing (20), number and label (15), outside scale (1). Standalone condition labels and number/label pairs were checked against Assignment 1's rubric.
- **Price.** Assessed forms are ambiguous separator (6), missing (33), plain (1,755), supported grouping (6), zero documented (1). Mixed grouping and decimal punctuation is usable when unambiguous or corroborated by the original workbook format. An otherwise uncorroborated single comma stays unresolved. A zero with explicit free-offer wording is valid and stays separate from paid-price diagnostics.

| Review flag | Attribute | Records |
|---|---|---:|
| negative | `price_raw` | 0 |
| nonfinite | `price_raw` | 0 |
| unparseable | `price_raw` | 0 |
| embedded currency | `price_raw` | 0 |
| ambiguous separator | `price_raw` | 6 |
| zero review | `price_raw` | 0 |
| zero documented | `price_raw` | 1 |
| negative | `age_raw` | 0 |
| nonfinite | `age_raw` | 0 |
| unparseable | `age_raw` | 0 |
| age range review | `age_raw` | 0 |
| unit typo review | `age_raw` | 1 |
| header cell unit conflict | `age_raw` | 0 |
| description age disagreement | `age_raw` | 0 |
| outside scale | `condition_raw` | 1 |
| fractional | `condition_raw` | 0 |
| label conflict | `condition_raw` | 0 |
| unparseable | `condition_raw` | 0 |
| nonfinite | `condition_raw` | 0 |
| ambiguous label | `currency_raw` | 10 |
| unsupported label | `currency_raw` | 0 |
| price currency conflict | `currency_raw` | 0 |

## IQR outlier diagnostics

Price includes 1,741 eligible rows. Exclusions are ambiguous separator (6), currency ambiguous label (10), currency missing (10), missing (33), zero documented (1). Age includes 1,415 eligible rows. Exclusions are missing (385), unit typo review (1). Each excluded row is counted under its first blocking reason. 33 price rows have an interpretable amount and currency but fall in currency samples too small for fences. Price cohorts use each currency separately. Overall fences require at least 10 values, and category-family fences require at least 25 within the same unit. Age cohorts use years. Quartiles use linear interpolation, fences use 1.5 × IQR, and sample SD uses n−1. Pearson's second coefficient is omitted for zero SD or an unassessed cohort.

| Attribute | Unit | Scope | n | Mean | Median | SD | Pearson S | Q1 | Q3 | IQR | Lower fence | Upper fence | Low flags | High flags |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| price | AED | All eligible | 9 | — | — | — | — | — | — | — | — | — | — | — |
| price | AUD | All eligible | 1 | — | — | — | — | — | — | — | — | — | — | — |
| price | CHF | All eligible | 19 | 245.105 | 180 | 223.566 | 0.873639 | 70.5 | 352.5 | 282 | -352.5 | 775.5 | 0 | 1 |
| price | EGP | All eligible | 6 | — | — | — | — | — | — | — | — | — | — | — |
| price | EUR | All eligible | 23 | 430.687 | 180 | 619.085 | 1.21479 | 53.375 | 460 | 406.625 | -556.562 | 1,069.94 | 0 | 4 |
| price | GBP | All eligible | 53 | 183.593 | 70 | 376.561 | 0.904978 | 20 | 180 | 160 | -220 | 420 | 0 | 7 |
| price | ILS | All eligible | 1205 | 3,081.78 | 100 | 29,474.4 | 0.303496 | 30 | 550 | 520 | -750 | 1,330 | 0 | 162 |
| price | ILS | Books | 99 | 29.1717 | 20 | 28.3884 | 0.969241 | 15 | 30 | 15 | -7.5 | 52.5 | 0 | 12 |
| price | ILS | Clothing and accessories | 176 | 128.403 | 60 | 301.326 | 0.681025 | 30 | 120 | 90 | -105 | 255 | 0 | 13 |
| price | ILS | Electronics | 299 | 879.518 | 374.84 | 1,857.3 | 0.815179 | 70 | 1,250 | 1,180 | -1,700 | 3,020 | 0 | 10 |
| price | ILS | Furniture | 122 | 678.902 | 300 | 1,066.63 | 1.0657 | 100 | 775 | 675 | -912.5 | 1,787.5 | 0 | 16 |
| price | ILS | Kitchen and household items | 181 | 280.343 | 80 | 504.89 | 1.19041 | 25 | 350 | 325 | -462.5 | 837.5 | 0 | 18 |
| price | ILS | Musical instruments | 35 | 1,167.97 | 500 | 1,696.38 | 1.18129 | 315 | 949.5 | 634.5 | -636.75 | 1,901.25 | 0 | 6 |
| price | ILS | Sports equipment | 81 | 1,048.38 | 350 | 1,633.69 | 1.28247 | 120 | 1,100 | 980 | -1,350 | 2,570 | 0 | 12 |
| price | ILS | Tools | 42 | 127.429 | 27.5 | 233.317 | 1.28489 | 15 | 80 | 65 | -82.5 | 177.5 | 0 | 9 |
| price | ILS | Toys and games | 61 | 170.426 | 35 | 309.441 | 1.31294 | 10 | 150 | 140 | -200 | 360 | 0 | 10 |
| price | ILS | Vehicles | 25 | 73,456 | 38,000 | 96,967.7 | 1.09694 | 12,000 | 85,000 | 73,000 | -97,500 | 194,500 | 0 | 3 |
| price | INR | All eligible | 1 | — | — | — | — | — | — | — | — | — | — | — |
| price | IQD | All eligible | 1 | — | — | — | — | — | — | — | — | — | — | — |
| price | JOD | All eligible | 10 | 92.5 | 85 | 62.9925 | 0.357185 | 38.75 | 138.75 | 100 | -111.25 | 288.75 | 0 | 0 |
| price | LYD | All eligible | 1 | — | — | — | — | — | — | — | — | — | — | — |
| price | SAR | All eligible | 4 | — | — | — | — | — | — | — | — | — | — | — |
| price | SEK | All eligible | 1 | — | — | — | — | — | — | — | — | — | — | — |
| price | SGD | All eligible | 7 | — | — | — | — | — | — | — | — | — | — | — |
| price | TWD | All eligible | 2 | — | — | — | — | — | — | — | — | — | — | — |
| price | USD | All eligible | 398 | 959.784 | 57.925 | 8,033.97 | 0.336767 | 19.99 | 217.5 | 197.51 | -276.275 | 513.765 | 0 | 50 |
| price | USD | Books | 33 | 35.3294 | 15 | 65.4452 | 0.931897 | 8 | 30 | 22 | -25 | 63 | 0 | 4 |
| price | USD | Clothing and accessories | 69 | 817.823 | 60 | 3,854.33 | 0.589849 | 22 | 245.95 | 223.95 | -313.925 | 581.875 | 0 | 8 |
| price | USD | Electronics | 79 | 213.69 | 119 | 342.706 | 0.8289 | 28.985 | 249.48 | 220.495 | -301.757 | 580.223 | 0 | 8 |
| price | USD | Furniture | 38 | 646.623 | 272 | 1,089.97 | 1.0311 | 80.915 | 658.743 | 577.828 | -785.826 | 1,525.48 | 0 | 4 |
| price | USD | Kitchen and household items | 49 | 102.862 | 50 | 162.379 | 0.976639 | 22 | 111 | 89 | -111.5 | 244.5 | 0 | 5 |
| price | USD | Sports equipment | 31 | 108.158 | 49.99 | 140.808 | 1.23932 | 24.31 | 131 | 106.69 | -135.725 | 291.035 | 0 | 2 |
| price | USD | Tools | 26 | 57.7796 | 32.935 | 64.7061 | 1.15188 | 12.505 | 82.5 | 69.995 | -92.4875 | 187.493 | 0 | 2 |
| price | USD | Toys and games | 35 | 196.223 | 20 | 624.509 | 0.846537 | 13.5 | 44.975 | 31.475 | -33.7125 | 92.1875 | 0 | 5 |
| age | years | All eligible | 1415 | 8.32877 | 3 | 16.6731 | 0.958806 | 1 | 7 | 6 | -8 | 16 | 0 | 160 |
| age | years | Books | 122 | 11.7 | 4 | 18.5139 | 1.24771 | 2 | 9 | 7 | -8.5 | 19.5 | 0 | 26 |
| age | years | Clothing and accessories | 204 | 7.83088 | 2 | 17.8746 | 0.978628 | 1 | 5 | 4 | -5 | 11 | 0 | 24 |
| age | years | Electronics | 331 | 4.70027 | 3 | 7.39139 | 0.6901 | 1 | 5 | 4 | -5 | 11 | 0 | 28 |
| age | years | Furniture | 149 | 9.72489 | 4 | 13.979 | 1.2286 | 2 | 10 | 8 | -10 | 22 | 0 | 17 |
| age | years | Kitchen and household items | 204 | 9.68836 | 3 | 22.0982 | 0.907997 | 1 | 6 | 5 | -6.5 | 13.5 | 0 | 26 |
| age | years | Musical instruments | 49 | 17.4324 | 10 | 19.9089 | 1.11997 | 3 | 26.5 | 23.5 | -32.25 | 61.75 | 0 | 3 |
| age | years | Sports equipment | 93 | 5.09311 | 3 | 8.0807 | 0.777079 | 1 | 6 | 5 | -6.5 | 13.5 | 0 | 5 |
| age | years | Tools | 57 | 6.03573 | 4 | 8.8821 | 0.687585 | 2 | 6 | 4 | -4 | 12 | 0 | 5 |
| age | years | Toys and games | 83 | 8.97698 | 3.5 | 14.2393 | 1.15392 | 1 | 9 | 8 | -11 | 21 | 0 | 11 |
| age | years | Vehicles | 34 | 8.05882 | 7 | 5.57016 | 0.570265 | 4 | 9.75 | 5.75 | -4.625 | 18.375 | 0 | 2 |

- Unique candidates across overall and family fences total 288 price rows and 187 age rows. A row can contribute to several fences. Each record/attribute pair has one issue entry with its applicable scopes.
- Age context for 6 candidates. Century-scale age needs source context or collection-year verification.
- Age context for 168 candidates. Check listing and variant context before treating the observation as erroneous.
- Age context for 8 candidates. Historical wording supports a plausible extreme age.
- Age context for 5 candidates. The year in the title supports a plausible extreme age.
- Price context for 258 candidates. Check listing and variant context before treating the observation as erroneous.
- Price context for 30 candidates. High-value asset context supports a plausible extreme price.
- Example retained for review. 'chicken farm' at 800,000 ILS.
- Example retained for review. 'Antique Hand-Painted Dome-Top Wooden Box, Early 19th Century' at 216 years.
- An outlier flag is evidence for investigation. Retain plausible extreme ages and high-value assets. The issue inventory preserves original values, item titles, comparison units and fences for contextual review.

## Image and structural findings

- Verified 1,803 image files with 1,801 distinct byte hashes. Associations by record are confirmed (1,507), missing (1), plausible (293). 1 file(s) remain unlinked, and 1 row(s) have multiple photo links. Confirmed means file-reference confirmation. Visual correspondence with a listing has not been verified.
- 1 submission(s) exceed the requested item count and 2 exceed the expected image count. 12 repaired quoted rows were structurally verified in Phase 1. 12 rows still have uncertain text boundaries and retain their fragments. The unresolved image does not block analysis of available item attributes.

## Proposed Phase 3 treatment

| Issue | Evidence | Preferred treatment and reason | Remaining uncertainty |
|---|---|---|---|
| Missing data | 385 ages and 33 prices missing | Preserve missingness. Use available valid values per analysis and report sample sizes. Concentration in certain submissions makes blanket imputation particularly weak. Use an explicit Unknown label only for categorical reporting where useful. | Missingness mechanisms are unverified. |
| Identifier reuse | 52 exact ID groups across students | Retain generated IDs and Original IDs. Check repeat groups separately from record duplication. | Local naming is not marketplace identity. |
| Duplicate evidence | 2 identical-photo groups, 35 further candidate pairs | Require convincing listing or capture evidence before excluding records. Preserve file and source provenance. | Same item versus reused photo is unresolved. |
| Categories | Full mapping and review statuses in the category CSV | Apply only equivalent labels after approval. Keep original labels, distinct subcategories, and uncertain assignments traceable. | Review broad and context-conflict labels. |
| Currency | 35 missing and 10 ambiguous | Normalize evidenced labels, and compare within currency. If a pooled comparison is required, use ILS with documented published rates for the collection date and direction, retaining source amounts and codes. | Missing codes and undocumented dates limit conversion. |
| Age and condition | Assignment 1 gives years and the condition scale | Use explicit cell units or the verified course default for years. Apply the documented label rubric. Resolve unsupported or invalid scores from evidence or leave the analytical value unavailable. | Text-unit typo, narrative conflicts, or abnormal ratings need verification. |
| Extreme values | 288 price and 187 age IQR candidates | Retain plausible extremes. Compare in compatible groups and correct only with source evidence. | Some extreme prices and unusual estimated ages remain unverified. |
| Incomplete text or images | Source fragments and per-file association confidence | Keep records; preserve uncertain text and linkage status. | Further labeling requires original evidence. |

The inventory has 613 issue entries covering 1,776 distinct records. Counts overlap across attributes and rules. Entries without a record refer to unlinked files.
Issue types and counts are ambiguous label (1), ambiguous separator (1), byte identical images (2), category context review (1), category label review (1), image reference confidence (1), iqr outlier candidate (475), missing image association (1), missing information (8), original id format reuse across students (30), original id reused across students (52), outside scale (1), possible duplicate item record (35), unit typo review (1), unlinked image files (1), unresolved title description boundary (1), zero documented (1).

**Ready for Phase 3 review.** The recommended treatments are proposals. Ambiguous currency, separator, duplicate, and text cases need source evidence or an approved decision to leave them unresolved.

# Phase 3 cleaning and preprocessing

## Reconciliation

- Raw data contains 1,801 observations from 120 students. The cleaned CSV contains 1,751 observations from 120 students and 38 columns.
- Excluded 50 observations and retained 41 representatives in 41 reviewed groups covering 91 source observations. The prior run excluded 49 across 40 groups. The corrected photo links support every consolidation edge. There were no conflicting reviewed pairs or asking prices within those groups. Retained representatives use the documented listing, field-completeness and source-alignment evidence. Conflicting subjective grades or ages remain in the raw source. The cleaning log maps every exclusion to its retained row.
- The independent scan used full and cropped perceptual hashes, exact image hashes, listing keys, and title and description similarity across all raw rows without filtering by category, price, or currency. Inspected 67 additional candidate pairs side by side. Verdicts were consolidate copy (2), distinct (53), related (2), similar (9), stock-like (1). Consolidation requires corroborating item and listing evidence. A photograph reused with conflicting asking prices is insufficient. The classmates' definition and pair list are unavailable.
- Reconciled the raw file hash before and after execution and compared 129 original attachment files against the frozen export. Raw SHA-256 is `27a07b988858d3393f20dee6c07fed389a721f04834a2104fc9e00488b5a24af`.
- Cleaned CSV SHA-256 is `35eb876d1529b2f6d2158d14e8fce4a94824c00b2827a6900087b8f088e1f2ae`.
- Raw exact nonblank category labels total 132. The cleaned data has 98 specific labels and 12 broader groups. A photograph-based category judgment covers the previously unclassified object. Its unresolved maker, origin, and purpose do not prevent classification by visible form.

## Missingness and evidence

Raw missingness includes blanks, whitespace and explicit placeholders. Before-imputation counts use the retained rows after supported source work. The original currency row counts ambiguous codes as unresolved after source review.

| Attribute | Raw missing | Retained before imputation | Cleaned missing |
|---|---:|---:|---:|
| Title | 0 (0.00%) | 0 (0.00%) | 0 (0.00%) |
| Description | 3 (0.17%) | 0 (0.00%) | 0 (0.00%) |
| Category | 1 (0.06%) | 0 (0.00%) | 0 (0.00%) |
| Age | 385 (21.38%) | 311 (17.76%) | 0 (0.00%) |
| Condition | 20 (1.11%) | 13 (0.74%) | 0 (0.00%) |
| Price | 33 (1.83%) | 39 (2.23%) | 0 (0.00%) |
| Currency of original amount | 35 (1.94%) | 41 (2.34%) | 41 (2.34%) |
| Image association | 1 (0.06%) | 5 (0.29%) | 5 (0.29%) |

The independent union calculation gives **431 (23.93%)** with at least one missing analytical source field. Counting only blank or whitespace fields gives 416 (23.10%). Restricting that definition to age, condition and price gives 405 (22.49%) and including their placeholders gives 419 (23.26%). Those definitions can explain part of the reported difference. The classmates' exact rule and dataset are unavailable. After cleaning the core-field union is 0 (0.00%).

| Analytical field | Value origin | Records |
|---|---|---:|
| age_years | corrected | 41 |
| age_years | estimated_edition_year | 2 |
| age_years | estimated_era_midpoint | 3 |
| age_years | estimated_model_year | 25 |
| age_years | estimated_purchase_year | 1 |
| age_years | estimated_usage_duration | 2 |
| age_years | imputed_category_median | 281 |
| age_years | imputed_global_median | 6 |
| age_years | imputed_group_median | 24 |
| age_years | observed | 1,366 |
| condition_rating | corrected | 57 |
| condition_rating | estimated_visual_condition | 4 |
| condition_rating | imputed_global_mode | 13 |
| condition_rating | observed | 1,676 |
| condition_rating | recovered_source | 1 |
| price_ils | converted | 537 |
| price_ils | corrected | 10 |
| price_ils | estimated_limited_comparable | 2 |
| price_ils | estimated_market_median | 8 |
| price_ils | imputed_category_median | 3 |
| price_ils | imputed_comparable_median | 36 |
| price_ils | observed | 1,151 |
| price_ils | recovered_source | 4 |

The age recovery review used all missing rows. Explicit model, edition, era, purchase and usage evidence produces approximate ages with separate method labels. Photographs corroborate item types and model details. Age estimates based on broader group or global donor pools carry a separate quality flag. Condition estimates use the Assignment 1 rubric and visible wear where it is sufficiently informative. The rating of 9 is preserved in raw data. The source description supports a cleaned rating of 5.
Local judgments supplied 3 missing descriptions. Descriptions contain supported visible details and previously recorded facts. The log records reasons and any limits on those inferences. The 12 unresolved title/description boundaries keep their original source fragments.

## Currency and photos

- Applied the frozen 2026-11-25 snapshot to 541 retained foreign-currency prices. Counts by original code are AED (9), AUD (1), CHF (19), EGP (6), EUR (23), GBP (54), INR (1), IQD (1), JOD (10), LYD (1), SAR (4), SEK (1), SGD (7), TWD (2), USD (402). The ILS identity and Decimal cross-rates were verified. Currency values are current-rate equivalents and source amounts are preserved.
- Follow-up price decisions total 14. Methods were estimated limited comparable (2), estimated market median (8), recovered source (4). Listing matches establish original currency and retain the recorded amounts. Reviewed comparables use observed local amounts or fixed public asking prices, with the evidence date, currency, units, and applicability recorded in the private log. Asking prices can differ from local completed transactions.
- 0 analytical prices remain blank. 41 records with unresolved original currency have a separate ILS estimate.
- Across the full source, applied 14 within-attachment replacements and 1 bread-box link. Detached 5 visually inconsistent associations without a supported replacement. Their original links remain traceable. Plausibility and limited visual evidence remain explicit. Multiple legitimate views are retained.
- Retained image-record statuses are insufficient visual information (1), mismatch unresolved (5), recovered visual link (1), replaced (14), uncertain (32), visually consistent (1,698).
- Unresolved source age and price flags carried into the cleaned data are age source review (9), price source review (14). Price and age were not capped, smoothed or deleted based on IQR.

## Imputation validation

Each usable source-valued target was masked in a five-fold split by student, seed 5341. Donors were other students, excluding photo-linked relatives, inferred values, suspicious numeric values, and the free offer for price estimation. Comparable methods use matching product subtype and title/model similarity. Parts-only offers use separate price pools. Donors can be filtered by observable product generation or size. Narrow, explicitly listed product types can use two independent donors when the product match is clear. Age and condition outcomes were excluded as price predictors to protect the required relationship analyses. Sparse price cohorts use separately reviewed comparables. Results on real missing targets can differ because the missingness mechanism is unknown.

| Field | Method | Test coverage | Common n | MAE | Log1p MAE | Signed bias | Exact agreement |
|---|---|---:|---:|---:|---:|---:|---:|
| age_years | global_mean | 1398/1398 | 554 | 6.412 | 0.982 | 2.262 | 0.0% |
| age_years | global_median | 1398/1398 | 554 | 4.373 | 0.682 | -2.694 | 10.8% |
| age_years | group_median | 1395/1398 | 554 | 4.342 | 0.670 | -2.374 | 9.7% |
| age_years | category_mean | 1244/1398 | 554 | 6.106 | 0.903 | 1.968 | 0.0% |
| age_years | category_median | 1244/1398 | 554 | 4.329 | 0.668 | -2.108 | 11.6% |
| age_years | comparable_median | 603/1398 | 554 | 4.391 | 0.681 | -2.093 | 9.7% |
| condition_rating | global_mode | 1734/1734 | 724 | 0.692 | 0.158 | 0.264 | 44.8% |
| condition_rating | global_median | 1734/1734 | 724 | 0.692 | 0.158 | 0.264 | 44.8% |
| condition_rating | group_mode | 1727/1734 | 724 | 0.693 | 0.159 | 0.246 | 44.8% |
| condition_rating | category_mode | 1556/1734 | 724 | 0.714 | 0.163 | 0.291 | 43.4% |
| condition_rating | category_median | 1556/1734 | 724 | 0.695 | 0.159 | 0.253 | 44.5% |
| condition_rating | comparable_mode | 784/1734 | 724 | 0.772 | 0.175 | 0.156 | 39.9% |
| price_ils | global_median_benchmark | 1687/1687 | 680 | 3483.860 | 1.562 | -3411.788 | 1.3% |
| price_ils | group_median_benchmark | 1680/1687 | 680 | 3361.209 | 1.299 | -2513.892 | 1.0% |
| price_ils | category_median | 1498/1687 | 680 | 2517.795 | 1.219 | -1815.255 | 1.3% |
| price_ils | comparable_median | 733/1687 | 680 | 2966.258 | 0.962 | -644.763 | 2.4% |

Applied priorities by field are age_years (category_median → group_median → global_median), condition_rating (global_mode → category_mode → group_mode), price_ils (comparable_median → category_median).
For price, log1p error captures relative scale in skewed cohorts. A lower overall benchmark error does not make a mixed-product pool appropriate for a rare book or commercial motor. The price method and donor range are documented per row.

## Statistical sensitivity and post-cleaning IQR

| Attribute | Cohort | n | Mean | Median | Sample SD |
|---|---|---:|---:|---:|---:|
| age_years | source-valued | 1,407 | 8.248 | 3.000 | 16.489 |
| age_years | completed | 1,751 | 7.591 | 3.000 | 15.186 |
| condition_rating | source-valued | 1,734 | 3.730 | 4.000 | 0.972 |
| condition_rating | completed | 1,751 | 3.732 | 4.000 | 0.967 |
| price_ils | source-valued | 1,702 | 3433.180 | 150.000 | 29337.286 |
| price_ils | completed | 1,751 | 3346.860 | 140.000 | 28928.377 |

| Attribute | Cohort | n | Q1 | Q3 | Q1 − 1.5 IQR | Q3 + 1.5 IQR | Lower | Upper |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| age_years | source-valued | 1,407 | 1.000 | 7.000 | -8.000 | 16.000 | 0 | 158 |
| age_years | completed | 1,751 | 2.000 | 6.000 | -4.000 | 12.000 | 0 | 206 |
| price_ils | source-valued | 1,702 | 40.000 | 636.517 | -854.776 | 1531.294 | 0 | 220 |
| price_ils | completed | 1,751 | 40.000 | 633.880 | -850.820 | 1524.700 | 0 | 221 |

| Relationship | Cohort | n | Pearson r | Spearman rho |
|---|---|---:|---:|---:|
| age_years and price | source-valued | 1,362 | 0.0629 | 0.1790 |
| age_years and price | completed | 1,751 | 0.0446 | 0.1722 |
| condition_rating and price | source-valued | 1,685 | 0.0056 | 0.1014 |
| condition_rating and price | completed | 1,751 | 0.0056 | 0.1011 |

| Condition rating | Source-valued | Completed |
|---|---:|---:|
| 1 | 41 | 41 |
| 2 | 143 | 143 |
| 3 | 441 | 441 |
| 4 | 728 | 745 |
| 5 | 381 | 381 |

For observed-only analysis, select methods `observed`, `corrected`, `converted` and `recovered_source` for each attribute involved in the analysis. Estimate and imputation methods remain individually identifiable. Later work should compare important findings across these cohorts and report sample sizes.

Assignment 1 §§2, 4, 5, and 7 establish the approximate years, currency, rating and image rules. Assignment 2 §3 requires documented handling of data quality issues and §4 motivates preserving associations for analysis. Lecture slides 20–22 guide recovery and imputation, slides 23–24 and 69–70 guide IQR investigation, and slide 26 supports resolving value conflicts and redundant observations.

## Readiness

The cleaned CSV and cleaning log reconcile every original observation. Sensitive row-level findings and review inputs stay in the course workspace. The observed-only and completed cohorts are available for Phase 4 after review.

# Pre-cleaning checkpoint

## Baseline and source verification

- Reconciled 129 original attachments, 128 versions and 120 student groups. The export's dated attachment records and numbered sequence corroborate selection order. The source system's submission timestamps remain unavailable.
- Rechecked 120 latest submissions and excluded 8 older versions. The nonstandard row and image counts remain 15 item rows / 17 images (1), 16 item rows / 16 images (1).
- Verified 1,801 rows against the selected source tables with separate CSV and workbook reads. The integrated records retain source IDs, fields, currency and age header evidence, hyperlinks and structural exceptions. The approved workbook remains authoritative and the extra item row remains present.
- Inspected 3 nonempty omitted source rows. They contain student-identification notes or metadata without marketplace item fields. Blank rows and actual headers were counted separately.
- Original attachment bytes and the raw baseline passed before and after verification. Raw SHA-256 is `27a07b988858d3393f20dee6c07fed389a721f04834a2104fc9e00488b5a24af`.

## Quantitative verification and revised interpretation

- Reconciled all 21 missingness counts and rates, category frequencies and the Phase 2 price, currency, age and condition frequency table. No baseline repair was required.
- The Phase 2 table covers all columns. The main missing analytical values are age 385 (21.38%), price 33 (1.83%), currency 35 (1.94%), condition 20 (1.11%), description 3 (0.17%), category 1 (0.06%).
- Independently recomputed the original 45 IQR scopes and 45 scopes after the approved interpretations. Checked quartiles, mean, median, sample SD, Pearson skewness and each tail count. Outliers are assessed within original currency or in years.
- Phase 2 reported 288 price and 187 age candidates. The approved exact comma forms and age typo yield 284 and 187 candidates. The outlier inventory retains both results, source text and the filing status of photo evidence.
- The original charts use paid-price cohorts in ILS and USD plus ages in years. Boxplot fences are calculated on original values. The log-spaced display exposes long tails and the age display accommodates zero.

## Actual visual coverage

- Accounted for 1,803 file locators and 1,801 distinct byte hashes. 1,803 files have logged visual judgments. 0 files remain unreviewed. 1 file(s) have no established structural association.
- Recorded visual verdicts are insufficient visual information (1), uncertain (33), unlinked image (1), visually consistent (1,749), visually inconsistent (19).
- 16 original file-reference confirmations have a visual mismatch. The initial check matched written names correctly. Visual review now separates those source-reference errors from mapping code. There are 14 proposed same-attachment replacements and 5 mismatches without a supported replacement. The proposal requires detaching the old associations together before applying replacements and checks that no proposed target is reused or taken from a visually supported link.
- Four neighboring image observations were initially assigned the next preview's product description. Larger source previews established the shoe and three car verdicts. Only review notes changed.
- Photo observations supplied category suggestions for 114 rows. The full proposal covers all 1,801 rows with 97 specific labels and 13 broader groups, including an unresolved group where evidence is insufficient. Row decisions are context proposal (64), reviewed, unresolved (2), source label (1,664), visual proposal (71). Proposed label changes by basis are context proposal (64), reviewed, unresolved (2), source label (362), visual proposal (71).
- The previously unlinked file visibly shows a wooden box labeled Bread. A matching record from the same submission has the only unresolved image association. This supports 1 proposed additional link. The source lacks an exact filename match or unique identifier, so approval is pending.
- Compared files using full-frame and central-crop difference hashes with a mean-color gate. The candidate list has 98 image pairs including earlier duplicate candidates and the multiple-photo item. Near hashes identify candidates and can miss more aggressive crops or alternate viewpoints.
- Actually inspected 98 pairs side by side. 0 pairs remain. Recorded findings are copy (55), distinct (11), exact (2), possible crop (1), same item likely (6), same item possible (1), same item, different view (8), same submitted set (3), similar (6), stock-like (3), stock-like reuse (1), uncertain (1). A reused photograph alone cannot establish listing identity.
- Proposed 40 consolidated groups affecting 89 observations, with 49 proposed analytical exclusions. Distinctive photo scenes and matching listing attributes support these groups. When strong physical-item matches carry different asking prices, retain those price variants and flag them for sensitivity analysis. Choose representatives with saved listing evidence and fuller analytical fields, followed by stronger source alignment and a stable ID tie-break. Conflicting values stay in the raw records and the private review inventory.
- Individually reviewed 481 of 481 record/attribute cases. Price cases are plausible genuine extreme (271), supported formatting or unit correction (9), unresolved suspicious value (14). Age cases are plausible genuine extreme (176), supported formatting or unit correction (2), unresolved suspicious value (9).
- Review used product context, compatible original currencies or years, and images where useful. Some apparent extremes reflect real premium goods, vintage collections, or a business facility. Product or quantity uncertainty still limits several estimates.
- 3 flagged book age(s) disagree materially with the stated edition year. Reprints or an estimate referring to time owned could explain the gap. Keep the original age and seek copy-specific evidence before replacing it.

## Fixed ILS conversion snapshot

- Covers 16 resolved codes, including the ILS identity rate. Checked source publications on 2026-11-25 local time. Published nonidentity rates by date are 2026-11-24 (15).
- Prefer direct Bank of Israel reference rates. Cross ECB quotes through EUR, UAE quotes through AED or USD, and the Libya and Taiwan quotes through USD. Each rate records its direction, operands, date, and source. This is a fixed contemporary equivalent, with no claim about historical item collection values or executable trades.
- The Bank of Israel and ECB quote 3.6627 and 3.6618 ILS per EUR on the same publication date, a difference of 0.0009 ILS or 0.0246% of the direct quote. The banks publish separate reference series. Use the Bank of Israel rate for direct EUR amounts and matching ECB numerator and denominators for INR and SGD. The quote date alone cannot identify the cause of the difference.
- 1,748 rows have sufficient price and currency evidence for a future ILS value. 45 rows have unresolved currency identity. Price, title and description contain 0 explicit currency cues among those rows. A blank or generic dollar label stays unresolved without independent evidence. The course gives no default currency.

## Treatment sensitivity

- The proposed numerical interpretations yield 1,416 usable ages. Complete-case retention across key item fields would leave 1,361 of 1,801 rows. Available-case denominators preserve other usable observations. Missing ages cluster, and the mechanism is unknown.

| Age treatment in records with a usable ILS amount | n | Age sample SD | Pearson age/price r |
|---|---:|---:|---:|
| available cases | 1,367 | 16.847 | 0.0534 |
| global mean | 1,748 | 14.897 | 0.0413 |
| global median | 1,748 | 15.062 | 0.0421 |

The in-memory comparison quantifies how filling available-price rows with one age value changes variance and correlation. It does not establish the true relationship for missing ages. Removing all incomplete rows can select against affected submissions. Removing age loses a required analysis. Group imputations preserve some between-group differences but still suppress within-group variation. Predictive filling would require defensible missingness assumptions and validation. Use per-analysis availability and record denominators.

The preferred strategy uses separate raw and analytical fields, conservative category aliases and broader groups, a dated ILS field, year-valued ages, Assignment 1 ordinal codes, and separate quality flags. Choose medians, IQRs and explicit sensitivity summaries for long tails. Binning, regression smoothing, clustering, clipping, normalization, and one-hot encoding serve no required cleaning purpose here. An optional grouping for display can remain separate from the continuous analysis.

Relevant lecture slides are 18–22 for completeness and missing treatment, 23–24 for noise and smoothing, 26 for data value conflicts and redundancy, 27–34 for transformations, 38–46 for descriptive statistics and skewness, and 68–71 for histograms, boxplots and IQR. Assignment 1 §§2, 4, 5 and 7 define units, codes and linkage expectations. Assignment 2 §§2–4 define the integration, quality and EDA requirements.

## Readiness

**The checkpoint is ready for review. Phase 3 requires explicit approval.**
Approve the proposal to apply the supported category and image mappings, consolidate the strong duplicate groups, and carry unresolved values and associations forward with flags. No cleaning has been applied.

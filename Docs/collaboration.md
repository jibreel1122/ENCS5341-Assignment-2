# Phase 0–3 collaboration handoff

## Work from the approved baseline

For Phase 4, authorized collaborators need the two approved datasets, the local Phase 3 summary, and access to the cleaning log for provenance and interpretation. Put the CSVs in the local data root and audit files under its `Audit/` directory. Both datasets contain source identifiers and must be transferred through the approved course channel while the repository is public. Confirm SHA-256 before use.

| Dataset | Rows × columns | SHA-256 |
|---|---:|---|
| `marketplace_raw.csv` | 1,801 × 21 | `27a07b988858d3393f20dee6c07fed389a721f04834a2104fc9e00488b5a24af` |
| `marketplace_cleaned.csv` | 1,751 × 38 | `35eb876d1529b2f6d2158d14e8fce4a94824c00b2827a6900087b8f088e1f2ae` |

The audit selected 120 latest submissions from 128 versions and reconciled 129 original attachments. Integration retained 1,801 records and inventoried 1,803 photographs. Quality assessment recorded 431 rows with at least one missing analytical source field under its placeholder-aware definition. Cleaning retained all 120 students after 50 exclusions across 41 reviewed duplicate groups. Analytical age, condition and ILS price are complete. Use the value-origin columns for observed-only sensitivity comparisons.

## Reproduce the approved workflow

Use the commands and dependencies in the README from a collaborator's own local data root. Preserve the original export basename and directory layout. The following seven review files are inputs to reproduction. Transfer them privately alongside access to the authorized original bulk ZIP and matching extracted source tree.

| Local path under the data root | Purpose |
|---|---|
| `Working/PreCleaning/visual_judgments.csv` | Image associations and corrections keyed by locator and hash |
| `Working/PreCleaning/duplicate_judgments.csv` | Earlier duplicate review |
| `Working/PreCleaning/outlier_judgments.csv` | Individual outlier assessments |
| `Working/PreCleaning/category_judgments.csv` | Contextual category decisions |
| `Working/PreCleaning/phase3_source_judgments.csv` | Source recovery and classification judgments |
| `Working/PreCleaning/phase3_price_evidence.csv` | Fixed listing and comparable-price evidence |
| `Working/PreCleaning/Phase3DuplicateReview/judgments.csv` | Final duplicate review |

The six project scripts, README and requirements are the tracked workflow. The checkpoint regenerates the audit exchange-rate table from frozen operands. Compare it with the [shareable reference](exchange_rates.csv). The final duplicate scan regenerates its candidate table, which cleaning checks against the private judgments. Compare the regenerated datasets with the hashes above.

## Sharing inventory

| Destination | Essential files |
|---|---|
| GitHub, suitable for the public tree | Six workflow scripts, README, requirements, ignore rules, this aggregate handoff, and the frozen exchange-rate reference. Review future notebooks and reports for sensitive outputs before sharing. |
| Approved course channel now. Eligible for a private repository only with explicit course authorization and restricted collaborator access | Both approved datasets. `Audit/phase0_submission_manifest.csv`, `Audit/phase0_issues.csv`, the four `Audit/phase0_summary.md` through `Audit/phase3_summary.md` reports, `Audit/phase2_issues.csv`, `Audit/phase2_category_mapping.csv`, `Audit/phase3_cleaning_log.csv`, and `Audit/pre_cleaning_review.md` and `Audit/pre_cleaning_decisions.md`. Keep the generated category, duplicate, outlier and visual review tables with the private audit trail if collaborators need direct access. |
| Approved course channel for original material and private evidence | Original submissions, archives, extracted source files, photographs, private listing evidence, and the seven manual review inputs above. Obtain course PDFs through course resources unless redistribution is permitted. |
| Regenerate locally as needed | Candidate tables, frequency tables, diagnostic plots and previews. Keep contact sheets, obsolete exports, temporary review helpers and caches out of the collaboration package. |

The four final submission files are `marketplace_raw.csv`, `marketplace_cleaned.csv`, `assignment2_analysis.ipynb`, and `assignment2_report.pdf`. The notebook and report are later-phase deliverables.

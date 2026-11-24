# ENCS5341 Assignment 2

A reproducible Python workflow for auditing, integrating, cleaning, and exploring the second-hand marketplace submissions collected in Assignment 1.

## Progress

Phase 1 is complete. The raw baseline contains 1,801 observations from 120 selected submissions, 21 columns, and 132 distinct nonblank category strings. Category spelling and spacing remain as recorded.

The integration used the approved Excel source for the one conflicting CSV/Excel pair. It verified 1,803 standalone image locators, including 1,801 distinct image hashes. The CSV records 1,507 image associations confirmed by path or filename, 293 plausible associations, and one unmatched record. One image remains unlinked. Twelve rows preserve an uncertain title/description boundary in their original CSV fragments. Phase 2 awaits approval.

## Project layout

| Path | Purpose |
|---|---|
| `Scripts/phase0_audit.py` | Verify the bulk export, select submissions, and audit tables and images |
| `Scripts/phase1_integration.py` | Integrate the selected tables and preserve original values and source references |
| `requirements.txt` | Python dependencies |
| `LocalData/` | Private local inputs for collaborators |
| `LocalData/Audit/` | Local manifest, issue inventory, and audit summaries |
| `LocalData/marketplace_raw.csv` | Sensitive local baseline produced by Phase 1 |
| `Notebooks/` and `Docs/` | Reviewed notebooks and documentation as the assignment progresses |

## Reproduce the audit and raw baseline

Use Python 3.11 or later and a RAR-capable `tar.exe` on Windows or `bsdtar` on other platforms. Pillow needs AVIF support. From the repository root, install the dependencies with `python -m pip install -r requirements.txt`.

Obtain the course-authorized bulk ZIP through the approved course channel. Place it and its matching extracted directory in `LocalData/`, preserving all paths inside the archive. For example, if the ZIP is `LocalData/class-submissions.zip`, extract its contents into `LocalData/class-submissions/`. Keep both copies for the byte comparison.

```sh
python Scripts/phase0_audit.py --root LocalData --export class-submissions.zip
python Scripts/phase1_integration.py --root LocalData
```

Use the actual ZIP filename in the command. For the existing course workspace with one matching ZIP and extracted directory at its root, run both scripts without the path arguments. Phase 1 reads the validated manifest, updates the local issue inventory, and writes `marketplace_raw.csv` under the source root. Identical reruns leave the baseline in place.

The raw CSV and local audit files contain student IDs and original paths. Authorized collaborators can regenerate them locally. Read source value columns as strings to preserve identifiers, blanks, and literal placeholders. `source_table` and the locators in `image_links` are JSON arrays. The first element is relative to the source root and subsequent elements locate members inside archives.

Share code, aggregate findings, and reviewed notebooks through GitHub. Review notebook outputs and any final deliverables for sensitive data before committing them. Keep course PDFs and student inputs in the approved course channel.

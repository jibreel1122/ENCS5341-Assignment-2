# ENCS5341 Assignment 2

A reproducible Python workflow for auditing, integrating, cleaning, and exploring the second-hand marketplace submissions collected in Assignment 1.

## Progress

Phase 0 is complete. The audit selected 120 student submissions with 1,801 marketplace rows and 1,803 readable standalone images. Two byte-identical pairs account for the difference between the file count and the 1,801 distinct image hashes.

One selected submission contains competing CSV and Excel tables. The audit uses the workbook under the approved fallback because its currency entries consistently use ILS. The archive timestamps support a later workbook save, and the CSV has no independent revision metadata. The selection applies only to the exact pair of source files identified by their SHA-256 digests. Phase 1 awaits approval.

## Project layout

| Path | Purpose |
|---|---|
| `Scripts/phase0_audit.py` | Verify the bulk export, select submissions, and audit tables and images |
| `requirements.txt` | Python dependencies |
| `LocalData/` | Private local inputs for collaborators |
| `LocalData/Audit/` | Local manifest, issue inventory, and audit summary produced by the command below |
| `Notebooks/` and `Docs/` | Reviewed notebooks and documentation as the assignment progresses |

## Reproduce Phase 0

Use Python 3.11 or later and a RAR-capable `tar.exe` on Windows or `bsdtar` on other platforms. Pillow needs AVIF support. From the repository root, install the dependencies with `python -m pip install -r requirements.txt`.

Obtain the course-authorized bulk ZIP through the approved course channel. Place it and its matching extracted directory in `LocalData/`, preserving all paths inside the archive. For example, if the ZIP is `LocalData/class-submissions.zip`, extract its contents into `LocalData/class-submissions/`. Keep both copies for the byte comparison.

```sh
python Scripts/phase0_audit.py --root LocalData --export class-submissions.zip
```

Use the actual ZIP filename in the command. For an existing course workspace with one matching ZIP and extracted directory at its root, run `python Scripts/phase0_audit.py`.

The local audit files contain student IDs and original paths. Authorized collaborators can regenerate them locally. Share code, aggregate findings, and reviewed notebooks through GitHub. Review notebook outputs and any final deliverables for sensitive data before committing them. Keep course PDFs and student inputs in the approved course channel.

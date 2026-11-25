"""Create public, pseudonymized copies of approved Phase 0–3 outputs."""
import csv, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "Data"
PUBLIC_AUDIT = ROOT / "Audit" / "public"
DATA.mkdir(exist_ok=True)
PUBLIC_AUDIT.mkdir(parents=True, exist_ok=True)
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)")
URL = re.compile(r"https?://\S+|www\.\S+", re.I)
PATH = re.compile(r"(?:[A-Za-z]:\\|compressed-attachments-from-\S+|/Users/\S+)[^\s,;]*", re.I)
ID = re.compile(r"\br-\d{7}-\d+\b|\b\d{7}\b")

raw = list(csv.DictReader((ROOT / "marketplace_raw.csv").open(encoding="utf-8-sig", newline="")))
clean = list(csv.DictReader((ROOT / "marketplace_cleaned.csv").open(encoding="utf-8-sig", newline="")))
mapping = {row["record_id"]: f"item-{i:04d}" for i, row in enumerate(raw, 1)}

def scrub(text):
    text = URL.sub("[link omitted]", text)
    text = PHONE.sub("[contact omitted]", text)
    text = ID.sub("[identifier omitted]", text)
    return "\n".join(line.rstrip() for line in text.splitlines())

def output(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})

raw_fields = ("public_record_id", "title", "description", "category", "age_raw", "age_header_unit",
              "condition_raw", "price_raw", "currency_raw", "image_status", "image_flags")
clean_fields = ("public_record_id", "title_clean", "description_clean", "category_clean", "category_group",
                "age_years", "age_method", "condition_rating", "condition_method", "price_original_amount",
                "currency_original_code", "price_ils", "price_method", "price_currency",
                "image_status_clean", "quality_flags")
for rows, source_id, path, fields, text_fields in (
    (raw, "record_id", DATA / "marketplace_raw.csv", raw_fields, ("title", "description")),
    (clean, "record_id", DATA / "marketplace_cleaned.csv", clean_fields, ("title_clean", "description_clean"))):
    public = []
    for row in rows:
        item = {"public_record_id": mapping[row[source_id]]}
        item.update({f: row.get(f, "") for f in fields if f != "public_record_id"})
        for f in text_fields:
            item[f] = scrub(item[f])
        public.append(item)
    output(path, public, fields)

# Publish aggregate audit reports after removing direct identifiers and source paths.
for name in ("phase0_summary.md", "phase1_summary.md", "phase2_summary.md", "phase3_summary.md",
             "pre_cleaning_review.md", "pre_cleaning_decisions.md"):
    source = ROOT / "Audit" / name
    if source.exists():
        text = source.read_text(encoding="utf-8")
        text = URL.sub("[source link omitted]", text)
        text = PATH.sub("[local path omitted]", text)
        text = ID.sub("[identifier]", text)
        (PUBLIC_AUDIT / name).write_text(text, encoding="utf-8")

log = list(csv.DictReader((ROOT / "Audit" / "phase3_cleaning_log.csv").open(encoding="utf-8-sig", newline="")))
safe_log = []
for row in log:
    item = dict(row)
    item["record_id"] = mapping.get(item["record_id"], "")
    item["related_record_ids"] = json.dumps([mapping[x] for x in json.loads(item["related_record_ids"]) if x in mapping])
    for field in ("original_value", "final_value", "evidence"):
        item[field] = scrub(item[field])
        item[field] = PATH.sub("[source path omitted]", item[field])
        if "compressed-attachments" in item[field]:
            item[field] = "[source media reference omitted]"
output(PUBLIC_AUDIT / "phase3_cleaning_log.csv", safe_log, list(log[0]))

# Aggregate mappings and value frequencies contain no provenance, only category labels.
for source, target in (("phase2_category_mapping.csv", "phase2_category_mapping.csv"),
                       ("phase2_value_frequencies.csv", "phase2_value_frequencies.csv")):
    file = ROOT / "Audit" / source
    if file.exists():
        (PUBLIC_AUDIT / target).write_bytes(file.read_bytes())

"""Build the unchanged marketplace baseline from the validated Phase 0 manifest."""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
from openpyxl import load_workbook
from PIL import Image

import phase0_audit as audit


SOURCE_COLUMNS = {
    "item_id": "original_item_id",
    "photo": "image_reference_raw",
    "title": "title",
    "description": "description",
    "category": "category",
    "age": "age_raw",
    "condition": "condition_raw",
    "price": "price_raw",
    "currency": "currency_raw",
    "listing_link": "listing_link_raw",
}
COLUMNS = (
    "record_id", "student_id", "submission_id", "source_table", "source_sheet", "source_row",
    "original_item_id", "title", "description", "category", "age_raw", "age_header_unit",
    "condition_raw", "price_raw", "currency_raw", "listing_link_raw", "image_reference_raw",
    "image_status", "image_links", "image_flags", "source_extras",
)
CONFIRMED = {"exact_path", "filename"}


def local_path(root, relative):
    path = (root / relative).resolve()
    if not audit.valid_member(relative) or not path.is_relative_to(root):
        raise ValueError("A manifest path escapes the source root.")
    return path


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader), reader.fieldnames


def manifest_inputs(root):
    manifest, _ = read_csv(local_path(root, "Audit/phase0_submission_manifest.csv"))
    selected = [row for row in manifest if row["selection_status"] == "selected"]
    statuses = Counter(row["selection_status"] for row in manifest)
    if not selected or set(statuses) - {"selected", "superseded"}:
        raise ValueError("The Phase 0 manifest has unresolved or missing selections.")
    if any(row["phase1_input_eligible"] != "yes" for row in selected):
        raise ValueError("A selected submission is blocked in the Phase 0 manifest.")
    if any(len({row[key] for row in rows}) != len(rows) for key, rows in
           (("student_id", selected), ("submission_id", manifest), ("tabular_data_locator", selected))):
        raise ValueError("The manifest repeats a selected student, submission, or table.")
    return manifest, sorted(selected, key=lambda row: (row["student_id"], row["submission_id"])), statuses


def verify_originals(root, manifest):
    """Check original attachments independently of the manifest's table selection."""
    paths = {row["bulk_export_path"] for row in manifest}
    if len(paths) != 1:
        raise ValueError("Expected one bulk export.")
    bulk = local_path(root, paths.pop())
    summary = local_path(root, "Audit/phase0_summary.md").read_text(encoding="utf-8")
    expected = re.search(r"bulk ZIP SHA-256 is `([a-f0-9]{64})`", summary)
    if not expected or audit.digest_file(bulk).hex() != expected[1]:
        raise ValueError("The bulk export hash differs from the Phase 0 baseline.")
    attachments = {}
    for row in manifest:
        for source, member in zip(json.loads(row["original_submission_paths"]),
                                  json.loads(row["bulk_export_members"]), strict=True):
            if member in attachments:
                raise ValueError("A bulk export member is listed more than once.")
            attachments[member] = local_path(root, source)
    with ZipFile(bulk) as archive:
        members = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
        if len(members) != len(attachments) or set(members) != attachments.keys():
            raise ValueError("The manifest and bulk export attachment inventories differ.")
        for member, source in attachments.items():
            with archive.open(member) as stream:
                expected_digest = hashlib.file_digest(stream, "sha256").digest()
            if audit.digest_file(source) != expected_digest:
                raise ValueError(f"An original attachment differs from the bulk export: {source.name}")
    return len(attachments)


def read_archive_members(archive, paths):
    """Read only manifest-listed members, including any nested ZIP members."""
    grouped = defaultdict(list)
    for member, *nested in paths:
        if not audit.valid_member(member):
            raise ValueError("Unsafe archive member in the manifest.")
        grouped[member].append(tuple(nested))
    results = {}
    for member, tails in grouped.items():
        if isinstance(archive, ZipFile):
            matches = [entry for entry in archive.infolist() if entry.filename == member]
            if len(matches) != 1 or matches[0].is_dir() or (matches[0].external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Missing or unsafe ZIP member: {member}")
            data = archive.read(matches[0])
        else:
            matches = [entry for entry in archive.getmembers() if entry.name == member]
            if len(matches) != 1 or not matches[0].isfile():
                raise ValueError(f"Missing or unsafe RAR member: {member}")
            with archive.extractfile(matches[0]) as stream:
                data = stream.read()
        if () in tails:
            results[(member,)] = data
        if any(tails):
            with ZipFile(io.BytesIO(data)) as nested:
                results.update({(member, *tail): value
                                for tail, value in read_archive_members(nested, filter(None, tails)).items()})
    return results


def read_selected_files(root, sources, locators):
    files = {}
    by_attachment = defaultdict(list)
    for source, *members in locators:
        if source not in sources:
            raise ValueError("A locator points outside its selected submission.")
        by_attachment[source].append(tuple(members))
    for source, paths in by_attachment.items():
        path = local_path(root, source)
        if paths == [()]:
            files[(source,)] = path.read_bytes()
        else:
            archive = audit.open_rar(path) if path.suffix.lower() == ".rar" else ZipFile(path)
            with archive:
                files.update({(source, *members): data
                              for members, data in read_archive_members(archive, paths).items()})
    return files


def table_records(data, spec):
    if spec["format"] != "XLSX":
        return audit.delimited_records(data.decode(spec["encoding"]), spec["delimiter"], True), {}
    book = load_workbook(io.BytesIO(data), data_only=False, keep_links=False)
    try:
        worksheet = book[spec["sheet"]]
        rows, hyperlinks = [], {}
        for number, cells in enumerate(worksheet.iter_rows(), 1):
            rows.append((number, tuple(cell.value for cell in cells)))
            refs = [{"column": cell.column, "target": cell.hyperlink.target, "location": cell.hyperlink.location}
                    for cell in cells if cell.hyperlink]
            if refs:
                hyperlinks[number] = refs
        return rows, hyperlinks
    finally:
        book.close()


def field_role(header):
    if audit.display(header).strip().lower() == "link":
        return "listing_link"
    return audit.role(header)


def align_delimited(raw, header, delimiter):
    """Recover anchored suffix fields. Leave uncertain prose boundaries visible."""
    roles = [field_role(name) for name in header]
    suffix = ("category", "age", "condition", "price", "currency")
    if (len(raw) <= len(header) or tuple(roles[-5:]) != suffix or "description" not in roles
            or not str(raw[-5]).strip() or not re.fullmatch(r"[A-Z]{3}", raw[-1].strip())
            or not all(audit.NUMBER.fullmatch(v.strip()) for v in raw[-4:-1])):
        return raw, ""
    first = roles.index("description")
    if first != len(header) - 6 or roles[first - 1] != "title":
        return raw, ""
    # A space before the opening quote made the original CSV lexer miss it.
    initial = re.match(r'^(\s+)"', raw[first])
    if initial and raw[-6].rstrip().endswith('"'):
        quoted = delimiter.join(raw[first:-5]).strip()
        try:
            fields = next(csv.reader([quoted], delimiter=delimiter, strict=True))
        except csv.Error:
            fields = []
        if len(fields) == 1:
            trailing = raw[-6][len(raw[-6].rstrip()):]
            description = initial[1] + fields[0] + trailing
            return [*raw[:first], description, *raw[-5:]], "space_prefixed_quoted_description"
    # Without quotes, the prose fragments do not establish where the title ends.
    # Keep the first title and description cells and preserve the full sequence.
    return [*raw[:first + 1], *raw[-5:]], "unquoted_prose_boundary"


def project_fields(raw, header, delimiter, hyperlinks):
    fields, alignment = align_delimited(raw, header, delimiter) if delimiter else (raw, "")
    mapped, unnamed = {}, []
    for index in range(max(len(fields), len(header))):
        name = audit.display(header[index]) if index < len(header) else ""
        value = audit.display(fields[index]) if index < len(fields) else ""
        column = SOURCE_COLUMNS.get(field_role(name))
        if column:
            mapped[column] = value
        elif value:
            unnamed.append({"column": index + 1, "header": name, "value": value})
    extras = {}
    if alignment:
        extras.update({"alignment": alignment, "parsed_source_fields": list(raw)})
    if unnamed:
        extras["additional_cells"] = unnamed
    if hyperlinks:
        extras["hyperlinks"] = hyperlinks
    age_header = next((audit.display(h) for h in header if field_role(h) == "age"), "")
    mapped["age_header_unit"] = "years" if re.search(r"\byears?\b", age_header.replace("_", " "), re.I) else ""
    return mapped, extras


def integrate_submission(root, row, issues, stats, schema):
    source = tuple(json.loads(row["tabular_data_locator"]))
    images = [tuple(path) for path in json.loads(row["image_file_locators"])]
    sources = json.loads(row["original_submission_paths"])
    spec, = [t for t in json.loads(row["table_candidates"])
             if tuple(t["locator"]) == source and t["sheet"] == row["table_sheet"]]
    if len(set(images)) != len(images) or source in images or len(images) != int(row["image_files"]):
        raise ValueError("Image locator inventory disagrees with the Phase 0 manifest.")
    files = read_selected_files(root, sources, [source, *images])
    data = files.pop(source)
    if hashlib.sha256(data).hexdigest() != spec["source_sha256"]:
        raise ValueError("The selected table differs from the Phase 0 manifest.")
    all_rows, hyperlinks = table_records(data, spec)
    cells = dict(all_rows)
    header = cells[spec["header_row"]]
    roles = [field_role(name) for name in header]
    if len(set(filter(None, roles))) != sum(map(bool, roles)):
        raise ValueError("Two source columns map to the same unified field.")
    for name, role in zip(header, roles):
        if role in SOURCE_COLUMNS:
            schema[SOURCE_COLUMNS[role]].add(str(name))
    stats["absent_fields"].update(set(SOURCE_COLUMNS) - set(roles))
    sub = audit.Submission(row["student_id"], sources, [])
    table = audit.worksheet_table(sub, source, spec["sheet"], spec["format"], spec["encoding"],
                                  spec["delimiter"], all_rows)
    if (table is None or table.header_row != spec["header_row"] or list(table.headers) != spec["columns"]
            or len(table.rows) != int(row["data_rows"]) or table.footers != spec["rows_without_item_evidence"]):
        raise ValueError("The selected table's parsed shape disagrees with the Phase 0 manifest.")
    for image in images:
        payload = files[image]
        # Presence and byte content are checked here. Phase 0 decoded the same verified bytes.
        digest = hashlib.sha256(payload).hexdigest()
        stats["image_hashes"][digest] += 1
        sub.images[image] = (digest, "", True)
    matches, flags = audit.record_links(sub, table)
    if len(table.unreferenced) != int(row["unreferenced_image_files"]) or any(
        table.links[key] != value for key, value in spec["link_counts"].items()
    ):
        raise ValueError("Photo reconciliation differs from the approved Phase 0 audit.")
    records, alignment_rows = [], defaultdict(list)
    stats["standalone_images"] += len(images)
    stats["unlinked_images"] += len(table.unreferenced)
    stats["readable_images"] += int(row["image_files_readable"])
    stats["source_formats"][spec["format"]] += 1
    stats["support_rows"] += len(table.footers) + len(table.blanks)
    for number, _ in table.rows:
        fields, extras = project_fields(cells[number], header, spec["delimiter"], hyperlinks.get(number))
        if extras.get("alignment"):
            alignment_rows[extras["alignment"]].append(number)
        if extras.get("additional_cells"):
            alignment_rows["additional_cells"].append(number)
        links = [{"locator": list(target), "method": method} for target, method in matches.get(number, ())]
        reasons = flags.get(number, [])
        if "ambiguous_refs" in reasons:
            status = "ambiguous"
        elif not links:
            status = "missing"
        elif all(link["method"] in CONFIRMED for link in links) and "missing_refs" not in reasons:
            status = "confirmed"
        else:
            status = "plausible"
        stats["link_methods"].update(link["method"] for link in links)
        stats["flagged_refs"].update(reasons)
        record_id = f"r-{row['submission_id']}-{number}"
        records.append({
            **fields,
            "record_id": record_id,
            "student_id": row["student_id"],
            "submission_id": row["submission_id"],
            "source_table": audit.json_cell(list(source)),
            "source_sheet": spec["sheet"],
            "source_row": number,
            "image_status": status,
            "image_links": audit.json_cell(links),
            "image_flags": audit.json_cell(reasons),
            "source_extras": audit.json_cell(extras),
        })
        if status in {"missing", "ambiguous"}:
            stats["open_image_rows"].append(record_id)
            sub.issue(f"phase1_{status}_image_association", record_id,
                      f"Source row {number}. No verified explicit or inferred link. Flags {audit.json_cell(reasons)}.",
                      action="Retain the record and review image provenance if it becomes available")
        if len(links) > 1:
            stats["multi_image_rows"].append((record_id, len(links)))
    for locator in sorted(table.unreferenced):
        with Image.open(io.BytesIO(files[locator])) as image:
            metadata = sorted(image.info)
            has_exif = bool(image.getexif())
        evidence = (f"No explicit reference, item-ID stem, or complete numeric mapping identifies this file. "
                    f"Embedded metadata keys {metadata}. EXIF present? {has_exif}.")
        sub.issue("phase1_unlinked_image_file", " :: ".join(locator), evidence,
                  action="Retain the image. Link only with additional item-specific evidence")
    alignment_reasons = {
        "space_prefixed_quoted_description": "Recovered the quoted description and the five intact trailing fields.",
        "unquoted_prose_boundary": ("Recovered the intact trailing fields. The leading title and description cells "
                                   "remain literal. The complete fragment sequence is in source_extras."),
        "additional_cells": "Preserved populated cells outside mapped headers in source_extras.",
    }
    for alignment, rows in alignment_rows.items():
        stats["structural_rows"][alignment] += len(rows)
        sub.issue(f"phase1_{alignment}", table.reference,
                  f"{alignment_reasons[alignment]} Source rows {rows}.",
                  "info" if alignment != "unquoted_prose_boundary" else "warning",
                  action="Review provenance in Phase 2", status="open" if alignment == "unquoted_prose_boundary" else "documented")
    issues.extend(issue for issue in sub.issues if issue["issue_type"].startswith("phase1_"))
    return records


def csv_bytes(frame):
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def validate_csv(data, frame, selected):
    """Round-trip with the standard CSV reader independently of the writer."""
    with io.StringIO(data.decode("utf-8"), newline="") as stream:
        reader = csv.DictReader(stream)
        records = list(reader)
    if tuple(reader.fieldnames) != COLUMNS or len(records) != len(frame):
        raise ValueError("The exported CSV did not round-trip its expected shape.")
    for expected, actual in zip(frame.itertuples(index=False, name=None), records, strict=True):
        if tuple(str(expected_value) for expected_value in expected) != tuple(actual.values()):
            raise ValueError("A source value was changed by CSV export.")
    if len({row["record_id"] for row in records}) != len(records):
        raise ValueError("Generated record IDs are not unique.")
    actual_counts = Counter((row["student_id"], row["submission_id"]) for row in records)
    expected_counts = {(row["student_id"], row["submission_id"]): int(row["data_rows"]) for row in selected}
    if actual_counts != expected_counts:
        raise ValueError("The output did not round-trip the selected-only per-student row counts.")
    return records


def write_output(path, data, protect=False):
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError("Refusing to write to an output symlink or junction.")
    if path.exists():
        if path.read_bytes() == data:
            return
        if protect:
            raise ValueError("An existing raw baseline differs. Preserve it and review the source changes.")
    temporary = tempfile.NamedTemporaryFile(dir=path.parent, delete=False)
    try:
        with temporary:
            temporary.write(data)
        os.replace(temporary.name, path)
    finally:
        Path(temporary.name).unlink(missing_ok=True)


def updated_issue_bytes(path, issues):
    current, columns = read_csv(path)
    if tuple(columns) != audit.ISSUE_COLUMNS:
        raise ValueError("Unrecognized Phase 0 issue inventory schema.")
    original = [row for row in current if not row["issue_type"].startswith("phase1_")]
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    writer.writerows([*original, *issues])
    return out.getvalue().encode("utf-8-sig")


def summarize(records, selected, versions, attachments, stats, schema, digest):
    category = {row["category"] for row in records if row["category"].strip()}
    item_ids = Counter(row["original_item_id"] for row in records if row["original_item_id"].strip())
    trimmed_ids = {value.strip() for value in item_ids}
    status = Counter(row["image_status"] for row in records)
    link_methods = stats["link_methods"]
    original_counts = Counter(int(row["data_rows"]) for row in selected)
    hashes = stats["image_hashes"]
    n_rows, n_students, n_columns = len(records), len(selected), len(COLUMNS)
    blank_category = sum(not row["category"].strip() for row in records)
    sections = [
        "# Assignment 2 Phase 1 integration audit",
        "", "## Input and output", "",
        f"- Integrated {n_students} approved latest tables from {attachments} catalogued attachments and "
        f"{sum(versions.values())} submission versions. The {versions['superseded']} superseded versions were "
        "excluded from integration. The authoritative workbook decision in Phase 0 was carried through.",
        f"- Exported **{n_rows:,} observations**, **{n_students} students**, **{len(category)} raw category strings**, "
        f"and **{n_columns} columns**. Category counts use exact non-empty source strings. "
        f"Blank or whitespace-only category fields occur on {blank_category} row(s). Case, spelling, "
        "and spacing variants can inflate the count before cleaning.",
        f"- Per-student row counts are {', '.join(f'{n} rows for {count} student(s)' for n, count in sorted(original_counts.items()))}. "
        f"The combined count agrees with the Phase 0 manifest. Input formats were "
        f"{', '.join(f'{fmt} ({count})' for fmt, count in sorted(stats['source_formats'].items()))}.",
        f"- SHA-256 for the unchanged CSV baseline is `{digest}`.",
        "", "## Unified schema and source mappings", "",
        "| Unified column | Source headers |",
        "|---|---|",
    ]
    for column in COLUMNS:
        if column in schema:
            headers = ", ".join(f"`{h}`" for h in sorted(schema[column], key=lambda h: (h.casefold(), h)))
            sections.append(f"| `{column}` | {headers} |")
    sections += [
        "",
        f"Full column order: {', '.join(f'`{column}`' for column in COLUMNS)}.",
        "",
        "- **Source provenance.** `student_id` and `submission_id` come from the manifest. `source_table` is "
        "a JSON array starting with a path relative to the source root, followed by exact archive member paths. "
        "`source_sheet` names the worksheet when present. `source_row` is the one-based worksheet row or "
        "the first physical line of the delimited record.",
        f"- **Identifiers.** All {n_rows:,} generated IDs are unique. `record_id` uses the approved submission "
        "identifier and the source row. `original_item_id` preserves the source text and leading zeros. "
        f"There are {len(item_ids)} distinct nonblank original ID strings across {sum(item_ids.values()):,} rows, "
        f"including {sum(n > 1 for n in item_ids.values())} repeated strings. "
        f"{n_rows - sum(item_ids.values())} rows have no original ID. The Phase 0 comparison trimmed surrounding "
        f"spaces and counted {len(trimmed_ids)} distinct IDs. The export preserves the exact strings.",
        "- **Value types.** Source values are strings in UTF-8 CSV. Exact delimited text, spacing, placeholders, "
        "currency labels, and invalid-looking values were retained. Spreadsheet cells are serialized from their stored "
        "values. The intended later types are numeric price, numeric age with an explicit unit, and a 1–5 ordinal "
        "condition rating. `age_header_unit` records years only where the source header declares it. Unspecified "
        "units stay blank, and units written in the age cell stay in `age_raw`.",
        f"- **Schema gaps.** Photo references are absent from {stats['absent_fields']['photo']} selected schemas, "
        f"item IDs from {stats['absent_fields']['item_id']}, and currency from {stats['absent_fields']['currency']}. "
        "Missing columns yield empty CSV fields. Listing links retain their own field. `source_extras` stores compact "
        "JSON for additional cells, embedded hyperlinks, and the original parsed sequences of structurally aligned rows.",
        "", "## Structural integration decisions", "",
        f"- Recovered {stats['structural_rows']['space_prefixed_quoted_description']} quoted descriptions with "
        "leading layout whitespace. The closing quote and the five trailing fields establish the boundaries.",
        f"- Recovered the identifiable trailing fields on {stats['structural_rows']['unquoted_prose_boundary']} rows "
        "with unquoted prose commas. The remaining title and description fragments have no reliable boundary. "
        "The first text cells stay literal and the original fragment sequence is in `source_extras`. The local "
        "issue inventory identifies the affected source rows.",
        f"- Preserved additional populated source cells on {stats['structural_rows']['additional_cells']} row(s) and "
        f"embedded worksheet hyperlinks on {stats['hyperlink_rows']} rows. Blank worksheet rows and identified "
        "non-item notes remain in their source files. No observation was removed to reconcile an expected count.",
        "", "## Image associations", "",
        "| Record association | Rows |",
        "|---|---:|",
    ]
    for name in ("confirmed", "plausible", "ambiguous", "missing"):
        sections.append(f"| {name.capitalize()} | {status[name]:,} |")
    sections += [
        "",
        f"- Verified {stats['standalone_images']:,} submission-scoped image locators and {len(hashes):,} "
        f"distinct SHA-256 hashes. Phase 0 decoded {stats['readable_images']:,} images from the same verified "
        f"attachment bytes. The resulting dataset carries {sum(link_methods.values()):,} image links. "
        f"Unlinked standalone image files total {stats['unlinked_images']}.",
        "- `image_reference_raw` preserves the source reference. `image_links` holds JSON objects with an exact "
        "relative locator and the association method. `image_flags` records missing reference or recovery evidence "
        "even when a plausible file was found. Each locator is scoped to its original attachment, which prevents "
        "cross-submission filename collisions.",
        "- Confirmed means the recorded path or a uniquely matching complete filename identifies a file in the "
        "submission. Plausible links use a unique stem, normalized separators or extensions, an item-ID match, "
        "a complete numeric pairing, or an item-specific folder. Confirmation is about the file reference. The "
        "audit did not verify visual correspondence with the marketplace listing.",
        f"- Association methods by file link: {', '.join(f'`{method}` ({n:,})' for method, n in sorted(link_methods.items()))}.",
        f"- {stats['flagged_refs']['missing_refs']} rows still have an unmatched explicit filename. Inferred links "
        "are labeled in the CSV. The 16-row submission remains intact.",
    ]
    if stats["multi_image_rows"]:
        sections += [
            f"- {len(stats['multi_image_rows'])} row(s) carry multiple associations. The matching item-ID folder "
            f"contains {sum(n for _, n in stats['multi_image_rows'])} photos in total. The original explicit "
            "references remain in the CSV.",
        ]
    if stats["open_image_rows"]:
        sections += ["- Unresolved record IDs: " + ", ".join(f"`{r}`" for r in stats["open_image_rows"]) + "."]
    if stats["unlinked_images"]:
        sections += [
            "- The remaining image has no corresponding explicit path, filename, or item-ID key. The image "
            "metadata yielded no item-specific identifier. A single leftover image and record are insufficient "
            "evidence. Both remain available locally.",
        ]
    sections += [
        "", "## Validation and readiness", "",
        f"- Checked the bulk export hash and all {attachments} original attachment contents before and after "
        "integration. Read only the exact tables and images listed in the approved manifest during integration.",
        "- Read the exported UTF-8 CSV using the standard library. Verified the column order, generated ID "
        "uniqueness, every field's round-trip value, and each selected student's row count. The writer emits "
        "a deterministic record and column order. Identical reruns leave the existing raw baseline in place.",
        "- The issue inventory retains the Phase 0 entries and adds source-specific Phase 1 findings. "
        "**Ready for Phase 2 with documented issues.** The raw CSV is the baseline. Later cleaning belongs "
        "in a separate output.",
        "",
    ]
    return "\n".join(sections)


def integrate(root):
    root = root.resolve()
    manifest, selected, versions = manifest_inputs(root)
    attachments = verify_originals(root, manifest)
    issues, schema = [], defaultdict(set)
    stats = Counter()
    for key in ("absent_fields", "image_hashes", "source_formats", "link_methods", "flagged_refs", "structural_rows"):
        stats[key] = Counter()
    stats["open_image_rows"], stats["multi_image_rows"] = [], []
    batches = [pd.DataFrame.from_records(integrate_submission(root, row, issues, stats, schema),
                                         columns=COLUMNS) for row in selected]
    frame = pd.concat(batches, ignore_index=True).fillna("")
    stats["hyperlink_rows"] = sum("hyperlinks" in json.loads(extras) for extras in frame["source_extras"])
    data = csv_bytes(frame)
    records = validate_csv(data, frame, selected)
    if verify_originals(root, manifest) != attachments:
        raise ValueError("The source attachment inventory changed during integration.")
    issue_path = root / "Audit" / "phase0_issues.csv"
    issue_data = updated_issue_bytes(local_path(root, "Audit/phase0_issues.csv"), issues)
    summary = summarize(records, selected, versions, attachments, stats, schema, hashlib.sha256(data).hexdigest())
    write_output(root / "marketplace_raw.csv", data, protect=True)
    write_output(issue_path, issue_data)
    write_output(root / "Audit" / "phase1_summary.md", summary.encode("utf-8"))
    return len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Source root containing the Phase 0 audit and original submissions")
    args = parser.parse_args()
    try:
        rows = integrate(args.root)
    except audit.FILE_ERRORS + (csv.Error, tarfile.TarError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Phase 1 integration failed. {exc}\n")
    print(f"Validated {rows:,} marketplace records and wrote the local Phase 1 outputs.")


if __name__ == "__main__":
    main()

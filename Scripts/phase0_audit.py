"""Audit the Assignment 1 export without extracting or editing source files.

Run: python Scripts/phase0_audit.py
Requires Python 3.11+, Pillow 11.3+ (with AVIF support), and openpyxl.
RAR reading uses bsdtar (tar.exe on Windows). Outputs stay in Audit/.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import unicodedata
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from xml.etree.ElementTree import ParseError, fromstring
from zipfile import BadZipFile
from zipfile import ZipFile

from openpyxl import load_workbook
from PIL import Image


EXPECTED_STUDENTS = 120
EXPECTED_ITEMS = 15
# Reapply the authorized table choice only to these exact source contents.
APPROVED_WORKBOOK = "78fda997580f78e1112a8e98ba49bafee6e448e49ec8dbe50ce0318c968f4210"
ALTERNATE_CSV = "12f0db89ed737614952d5f0a0a45d96dae353abc5d80b64f52856b10f106e0f7"
TABULAR = {".csv", ".tsv", ".xlsx", ".xls", ".xlsm", ".ods", ".txt", ".json"}
IMAGE_EXT = {
    ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP",
    ".avif": "AVIF", ".gif": "GIF", ".bmp": "BMP", ".tif": "TIFF",
    ".tiff": "TIFF", ".jfif": "JPEG", ".heic": "HEIF", ".heif": "HEIF",
}
IMAGE_SUFFIX_LABELS = {extension[1:] for extension in IMAGE_EXT}
ID_TOKEN = re.compile(r"(?<!\d)\d{7}(?!\d)")
ITEM_PREFIX = re.compile(r"^\s*(\d{7})[_-]\d+")
ALIASES = {
    "item_id": "itemid id itemnumber",
    "photo": "itemphoto itemphotofilename itemimage itemimagefile image imagefilename imagefile photo photofilename",
    "title": "title itemtitle name itemname",
    "description": "description descreption itemdescription",
    "category": "category itemcategory",
    "age": "age ageyear ageyears itemage approximateage approximateageyears estimatedage",
    "condition": "condition condition15 conditionrating conditionrating15",
    "price": "price priceils priceusd askingprice",
    "currency": "currency currencycode",
    "student_id": "studentid studentnumber",
}
HEADER_ROLE = {alias: role for role, aliases in ALIASES.items() for alias in aliases.split()}
CORE = set(ALIASES) - {"student_id"}
PLACEHOLDERS = {"n/a", "na", "null", "none", "unknown", "not available", "-", "—"}
FILE_ERRORS = (OSError, ValueError, RuntimeError, EOFError, KeyError, BadZipFile, ParseError)
ISSUE_COLUMNS = ("student_id", "submission_id", "reference", "issue_type",
                 "evidence", "severity", "status", "next_action")


def display(value):
    return "" if value is None else str(value)


def role(value):
    return HEADER_ROLE.get(re.sub(r"[^a-z0-9]", "", display(value).lower()), "")


def json_cell(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def valid_member(name):
    # Validate names even though archives are streamed and never written to disk.
    parts = name.replace("\\", "/").split("/")
    return not name.startswith(("/", "\\")) and ":" not in name and ".." not in parts


def is_artifact(name, data):
    parts = PurePosixPath(name).parts
    return ("__MACOSX" in parts or parts[-1].lower() in {".ds_store", "desktop.ini", "thumbs.db"}
            or parts[-1].startswith((".~lock.", "~$")) or data.startswith(b"\x00\x05\x16\x07"))


@dataclass
class Table:
    locator: tuple
    sheet: str
    format: str
    encoding: str
    delimiter: str
    header_row: int
    headers: tuple
    rows: list
    blanks: list
    footers: list
    malformed: list
    parse_warning: str = ""
    source_sha256: str = ""
    zip_member_time: str = ""
    workbook_modified: str = ""
    links: Counter = field(default_factory=Counter)
    linked_images: set = field(default_factory=set)
    item_ids: list = field(default_factory=list)
    folder_links: dict = field(default_factory=dict)
    inferred_links: dict = field(default_factory=dict)
    photo_formats: Counter = field(default_factory=Counter)
    value_formats: dict = field(default_factory=dict)
    grouped_numbers: dict = field(default_factory=dict)
    unreferenced: set = field(default_factory=set)

    @property
    def labels(self):
        return tuple(role(h) for h in self.headers)

    @property
    def reference(self):
        return " :: ".join(self.locator) + (f" :: {self.sheet}" if self.sheet else "")

    def spec(self):
        return {
            "locator": list(self.locator), "sheet": self.sheet, "format": self.format,
            "encoding": self.encoding, "delimiter": self.delimiter,
            "header_row": self.header_row, "columns": list(self.headers),
            "data_rows": len(self.rows), "rows_without_item_evidence": self.footers,
            "malformed_rows": self.malformed, "parse_warning": self.parse_warning,
            "source_sha256": self.source_sha256, "zip_member_time": self.zip_member_time,
            "workbook_modified": self.workbook_modified,
            "link_counts": dict(self.links), "unreferenced_images": len(self.unreferenced),
            "value_formats": self.value_formats, "link_methods": dict(self.photo_formats),
        }


@dataclass
class Submission:
    student: str
    sources: list
    chronology: list
    status: str = ""
    reason: str = ""
    identity: str = ""
    blocked: bool = False
    issues: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    chosen: Table | None = None
    table_reason: str = ""
    images: dict = field(default_factory=dict)
    ancillary: list = field(default_factory=list)
    embedded: int = 0
    auxiliary_rows: int = 0
    table_errors: int = 0
    inventory_errors: int = 0
    identity_tokens: set = field(default_factory=set)
    image_extensions: dict = field(default_factory=lambda: defaultdict(list))
    table_disagreement: str = ""
    table_resolution: str = ""

    @property
    def key(self):
        return "+".join(Path(p).name.split("-", 1)[0] for p in self.sources)

    def issue(self, kind, reference, evidence, severity="warning", action="Phase 1 review",
              status="open"):
        self.issues.append(dict(zip(ISSUE_COLUMNS, (
            self.student, self.key, reference, kind, evidence, severity, status, action,
        ))))


def audit_image(sub, locator, data, extension, archive_error=""):
    reference = " :: ".join(locator)
    digest = hashlib.sha256(data).hexdigest() if data is not None else ""
    image_format = ""
    error = archive_error
    if data is not None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    image_format = image.format
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    for frame in range(getattr(image, "n_frames", 1)):
                        image.seek(frame)
                        image.load()
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning,
                Image.DecompressionBombError) as exc:
            error = f"{type(exc).__name__}: {exc}"
    sub.images[locator] = (digest, image_format, not error)
    if error:
        sub.issue("image_unreadable", reference, error, action="Recover or identify a decoder in Phase 1")
    elif extension and IMAGE_EXT.get(extension) != image_format:
        sub.image_extensions[extension, image_format].append(reference)
    elif not extension:
        sub.issue("image_unexpected_extension", reference, f"Detected {image_format} by content.")


def has_image_signature(data):
    return (data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a",
                             b"II*\0", b"MM\0*", b"BM"))
            or data[:4] == b"RIFF" and data[8:12] == b"WEBP"
            or data[4:12] in {b"ftypavif", b"ftypavis", b"ftypheic", b"ftypheix"})


def table_header(rows):
    for index, (_, values) in enumerate(rows[:30]):
        labels = {role(v) for v in values} - {""}
        if len(labels & CORE) >= 4 and "category" in labels and labels & {"item_id", "title", "price"}:
            return index
    return None


def present(value):
    return bool(display(value).strip())


def worksheet_table(sub, locator, sheet, fmt, encoding, delimiter, records, parse_warning=""):
    index = table_header(records)
    if index is None:
        return None
    header_row, raw_headers = records[index]
    # Leading empty columns may be intentional layout padding. Keep internal gaps.
    used = [i for i, v in enumerate(raw_headers) if present(v)]
    first, last = used[0], used[-1] + 1
    headers = tuple(display(v) for v in raw_headers[first:last])
    labels = tuple(role(v) for v in headers)
    item_fields = [i for i, label in enumerate(labels) if label in {"item_id", "photo", "title", "category", "price"}]
    rows, blanks, footers, malformed = [], [], [], []
    for row_number, raw in records[index + 1:]:
        if not any(map(present, raw)):
            blanks.append(row_number)
            continue
        values = tuple((list(raw[first:last]) + [None] * len(headers))[:len(headers)])
        if not any(present(values[i]) for i in item_fields):
            footers.append(row_number)
            continue
        out_of_columns = any(map(present, raw[:first])) or any(map(present, raw[last:]))
        if out_of_columns or (fmt != "XLSX" and len(raw) < last):
            malformed.append(row_number)
        rows.append((row_number, values))
    table = Table(locator, sheet, fmt, encoding, delimiter, header_row, headers,
                  rows, blanks, footers, malformed, parse_warning)
    preamble = [n for n, values in records[:index] if any(map(present, values))]
    if preamble:
        sub.issue("table_preamble", table.reference, f"Non-empty rows before header: {preamble}.",
                  "info", status="identified")
    if footers or malformed:
        sub.issue("table_row_structure", table.reference,
                  f"Rows without item evidence: {footers}. Item rows extending past or short of the header: {malformed}.")
    if blanks:
        sub.issue("blank_table_rows", table.reference, f"Empty rows after the header: {blanks}.",
                  "info", status="identified")
    if parse_warning:
        sub.issue("table_parse_warning", table.reference, parse_warning, "error")
    return table


def decode_table(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8-sig"), "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252"), "cp1252"


def delimited_records(text, delimiter, strict):
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=strict)
    rows = []
    while True:
        first_line = reader.line_num + 1
        try:
            values = next(reader)
        except StopIteration:
            return rows
        rows.append((first_line, values))


def read_text_table(sub, locator, data, extension):
    text, encoding = decode_table(data)
    if "\x00" in text:
        raise ValueError("Binary data or unsupported text encoding")
    for delimiter, fmt in ((",", "CSV"), ("\t", "TSV"), (";", "semicolon-delimited"), ("|", "pipe-delimited")):
        rows = delimited_records(text, delimiter, strict=False)
        if table_header(rows) is None:
            continue
        warning = ""
        try:
            rows = delimited_records(text, delimiter, strict=True)
        except csv.Error as exc:
            warning = f"Strict delimited parsing failed ({exc}). Counts use a permissive parse for audit only."
        sub.tables.append(worksheet_table(sub, locator, "", fmt, encoding, delimiter, rows, warning))
        if encoding not in {"utf-8", "utf-8-sig"} or fmt != "CSV" or extension != ".csv":
            sub.issue("table_format_variant", " :: ".join(locator),
                      f"Detected {fmt}, {encoding}, filename suffix {extension}.", "info", status="identified")
        return
    sub.ancillary.append(locator)
    # A structured provenance table is supporting material rather than an item table.
    for delimiter in ("\t", ",", ";"):
        rows = delimited_records(text, delimiter, strict=False)
        if any(len(v) >= 3 and role(v[0]) == "item_id" for _, v in rows[:10]):
            header = next(i for i, (_, v) in enumerate(rows[:10]) if len(v) >= 3 and role(v[0]) == "item_id")
            sub.auxiliary_rows += sum(any(map(present, v)) for _, v in rows[header + 1:])
            return
    if extension in {".csv", ".tsv"}:
        sub.table_errors += 1
        sub.issue("unrecognized_table", " :: ".join(locator),
                  "Decoded successfully but a marketplace or provenance header could not be established.", "error")


def read_workbook(sub, locator, data):
    modified = ""
    with ZipFile(io.BytesIO(data)) as container:
        sub.embedded += sum(name.startswith("xl/media/") and not name.endswith("/") for name in container.namelist())
        if "docProps/core.xml" in container.namelist():
            props = fromstring(container.read("docProps/core.xml"))
            modified = props.findtext("{http://purl.org/dc/terms/}modified") or ""
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    try:
        for sheet in book.worksheets:
            cell_rows = list(sheet.iter_rows())
            rows = [(n, [cell.value for cell in cells]) for n, cells in enumerate(cell_rows, 1)]
            table = worksheet_table(sub, locator, sheet.title, "XLSX", "", "", rows)
            if table is not None:
                table.workbook_modified = modified
                sub.tables.append(table)
                offset = next(i for i, v in enumerate(rows[table.header_row - 1][1]) if present(v))
                for n, values in table.rows:
                    for i, value in enumerate(values):
                        cells = cell_rows[n - 1]
                        if (offset + i < len(cells) and type(value) is int
                                and cells[offset + i].number_format == "#,##0"):
                            table.grouped_numbers[n, i] = f"{value:,}"
                formulas = [(n, i + 1) for n, values in table.rows for i, v in enumerate(values)
                            if isinstance(v, str) and v.startswith("=")]
                if formulas:
                    sub.issue("worksheet_formulas", table.reference,
                              f"Formula cell coordinates (row, column): {formulas}.", action="Review formula values in Phase 1")
            else:
                sub.ancillary.append((*locator, "sheet=" + sheet.title))
                first = next((i for i, (_, v) in enumerate(rows) if any(role(x) == "item_id" for x in v)), None)
                if first is not None:
                    sub.auxiliary_rows += sum(any(map(present, v)) for _, v in rows[first + 1:])
    finally:
        book.close()


def record_failure(sub, locator, error):
    ext = PurePosixPath(locator[-1]).suffix.lower()
    if ext in IMAGE_EXT:
        audit_image(sub, locator, None, ext, error)
    else:
        sub.inventory_errors += 1
        sub.issue("member_unreadable", " :: ".join(locator), error, "error")


def read_zip(sub, locator, stream):
    with ZipFile(stream) as archive:
        entries = [member for member in archive.infolist() if not member.is_dir()]
        if not entries:
            sub.ancillary.append(locator)
            sub.issue("empty_archive", " :: ".join(locator), "Archive contains no files.", "info")
        names = Counter(e.filename for e in entries)
        for entry in sorted(entries, key=lambda e: e.filename):
            target = (*locator, entry.filename)
            if not valid_member(entry.filename) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                record_failure(sub, target, "Unsafe archive path or symbolic link")
                continue
            if names[entry.filename] > 1:
                if names[entry.filename] != 0:
                    sub.inventory_errors += 1
                    sub.issue("duplicate_archive_path", " :: ".join(target),
                              f"{names[entry.filename]} members share this exact archive path.", "error")
                    names[entry.filename] = 0
                continue
            if names[entry.filename] == 0:
                continue
            try:
                data = archive.read(entry)
            except FILE_ERRORS + (tarfile.TarError,) as exc:
                record_failure(sub, target, str(exc))
                continue
            inspect_member(sub, target, data, datetime(*entry.date_time).isoformat())


def open_rar(path):
    # bsdtar imports the RAR into a TAR byte stream. No archive paths are extracted.
    command = ["tar.exe" if os.name == "nt" else "bsdtar", "-cf", "-", "@" + str(path)]
    result = subprocess.run(command, capture_output=True, check=True)
    return tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:")


def read_rar(sub, locator, path):
    with open_rar(path) as archive:
        members = [m for m in archive if not m.isdir()]
        names = Counter(m.name for m in members)
        for entry in sorted(members, key=lambda m: m.name):
            target = (*locator, entry.name)
            if not valid_member(entry.name) or not entry.isfile() or names[entry.name] > 1:
                record_failure(sub, target, "Unsafe, non-regular or non-unique archive member")
                continue
            with archive.extractfile(entry) as stream:
                inspect_member(sub, target, stream.read())


def inspect_member(sub, locator, data, zip_member_time=""):
    name = locator[-1]
    ext = PurePosixPath(name).suffix.lower()
    if is_artifact(name, data):
        sub.ancillary.append(locator)
        return
    if len(locator) > 1:
        sub.identity_tokens.update(ID_TOKEN.findall(name))
    previous_tables = len(sub.tables)
    try:
        if ext in IMAGE_EXT or has_image_signature(data):
            audit_image(sub, locator, data, ext)
        elif data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            with ZipFile(io.BytesIO(data)) as package:
                workbook = "xl/workbook.xml" in package.namelist()
            if workbook:
                read_workbook(sub, locator, data)
                if ext != ".xlsx":
                    sub.issue("table_format_variant", " :: ".join(locator), "XLSX content with a different suffix.")
            else:
                read_zip(sub, locator, io.BytesIO(data))
        elif ext in {".csv", ".tsv", ".txt"}:
            read_text_table(sub, locator, data, ext)
        elif ext in TABULAR:
            raise ValueError("Unrecognized or unsupported tabular format")
        else:
            sub.ancillary.append(locator)
            sub.issue("unexpected_file", " :: ".join(locator), f"Non-image, non-marketplace file ({ext or 'no suffix'}).",
                      "info", action="Preserve as supporting material", status="identified")
    except FILE_ERRORS + (tarfile.TarError,) as exc:
        if ext in TABULAR:
            sub.table_errors += 1
            sub.issue("table_unreadable", " :: ".join(locator), f"{type(exc).__name__}: {exc}", "error")
        else:
            record_failure(sub, locator, f"{type(exc).__name__}: {exc}")
    for table in sub.tables[previous_tables:]:
        if table.locator == locator:
            table.source_sha256 = hashlib.sha256(data).hexdigest()
            table.zip_member_time = zip_member_time


def audit_attachment(sub, root, rel):
    path = root / rel
    locator = (rel,)
    try:
        with path.open("rb") as stream:
            magic = stream.read(8)
            stream.seek(0)
            if magic.startswith(b"Rar!\x1a\x07"):
                read_rar(sub, locator, path)
            elif path.suffix.lower() == ".zip" and magic.startswith(b"PK"):
                read_zip(sub, locator, stream)
            else:
                inspect_member(sub, locator, stream.read())
    except FILE_ERRORS + (subprocess.SubprocessError, tarfile.TarError) as exc:
        sub.inventory_errors += 1
        sub.issue("attachment_unreadable", rel, f"{type(exc).__name__}: source could not be read",
                  "error", action="Recover the affected source")


def digest_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def discover(root, export_path, extracted_path):
    """Use the bulk ZIP as the inventory of record and verify its existing copy."""
    with ZipFile(export_path) as archive:
        entries = {}
        mirrors = {}
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            parts = PurePosixPath(entry.filename).parts
            if len(parts) != 3 or not valid_member(entry.filename) or entry.filename in mirrors:
                raise ValueError("Unexpected or duplicate bulk-export member. Review before selecting.")
            mirror = extracted_path / entry.filename
            if not mirror.is_file() or not mirror.resolve().is_relative_to(extracted_path.resolve()):
                raise ValueError("An export member has no safe, existing local copy.")
            with archive.open(entry) as stream:
                exported_digest = hashlib.file_digest(stream, "sha256").digest()
            local_digest = digest_file(mirror)
            if exported_digest != local_digest:
                raise ValueError("The existing extracted attachment differs from the bulk export.")
            mirrors[entry.filename] = local_digest
            entries[mirror.relative_to(root).as_posix()] = entry
    extracted_files = {p.relative_to(extracted_path).as_posix()
                       for p in extracted_path.rglob("*") if p.is_file()}
    if extracted_files != set(mirrors):
        raise ValueError("The extracted export contains extra or missing files. Review its inventory.")
    return entries, mirrors


def form_versions(entries):
    folders = defaultdict(list)
    for path in sorted(entries):
        folders[PurePosixPath(path).parent].append(path)
    revisions = []
    ids = [PurePosixPath(path).name.split("-", 1)[0] for path in entries]
    valid_sequence = all(re.fullmatch(r"\d{7}", x) for x in ids) and len(set(ids)) == len(ids)
    sequence = sorted(entries, key=lambda p: PurePosixPath(p).name)
    regressions = sum(entries[a].date_time > entries[b].date_time for a, b in zip(sequence, sequence[1:]))
    order_supported = valid_sequence and not regressions
    for folder, attachments in sorted(folders.items()):
        identity = folder.name if re.fullmatch(r"\d{7}", folder.name) else ""
        # A same-timestamp dataset.csv and images.zip pair has complementary roles.
        by_label = {PurePosixPath(p).name.split("-", 1)[-1].casefold(): p for p in attachments}
        pair = [by_label[k] for k in ("dataset.csv", "images.zip") if k in by_label]
        if len(pair) == 2 and entries[pair[0]].date_time == entries[pair[1]].date_time:
            groups = [sorted(pair)] + [[p] for p in attachments if p not in pair]
        else:
            groups = [[p] for p in attachments]
        candidates = [Submission(identity, group, [entries[p].date_time for p in group]) for group in groups]
        ordered = sorted(candidates, key=lambda s: (max(s.chronology), s.key))
        distinct_dates = len({max(s.chronology) for s in ordered}) == len(ordered)
        for candidate in ordered:
            if not identity:
                candidate.status, candidate.reason = "unresolved", "Export folder lacks a seven-digit student identifier."
            elif len(ordered) == 1:
                candidate.status = "selected"
                candidate.reason = ("Only version. Same export timestamp and complementary dataset/images attachments."
                                    if len(candidate.sources) > 1 else "Only attachment version in the student export folder.")
            elif not (order_supported and distinct_dates):
                candidate.status = "unresolved"
                candidate.reason = "Distinct versions lack corroborated, strictly ordered export chronology."
            elif candidate is ordered[-1]:
                candidate.status = "selected"
                candidate.reason = "Latest bulk ZIP member timestamp, corroborated by the highest attachment number."
            else:
                candidate.status = "superseded"
                candidate.reason = "Earlier bulk ZIP member timestamp and lower attachment number."
            revisions.append(candidate)
    return revisions, valid_sequence, regressions


def audit_identity(sub):
    names = [PurePosixPath(p).name.split("-", 1)[-1] for p in sub.sources]
    attachment_tokens = {token for name in names for token in ID_TOKEN.findall(name)}
    values = defaultdict(list)
    item_tokens = defaultdict(list)
    for table in sub.tables:
        if "student_id" in table.labels:
            col = table.labels.index("student_id")
            for row, cells in table.rows:
                if present(cells[col]):
                    values[display(cells[col]).strip()].append(row)
        if "item_id" in table.labels:
            col = table.labels.index("item_id")
            for row, cells in table.rows:
                match = ITEM_PREFIX.match(display(cells[col]))
                if match:
                    item_tokens[match[1]].append(row)
    corroboration = [name for name, tokens in (("attachment label", attachment_tokens),
                      ("member path", sub.identity_tokens), ("student ID column", values),
                      ("item ID prefix", item_tokens)) if sub.student and sub.student in tokens]
    sub.identity = "Numeric export folder" + (f" corroborated by {', '.join(corroboration)}" if corroboration else "")
    conflicts = ((attachment_tokens and sub.student not in attachment_tokens)
                 or bool(set(values) - {sub.student})
                 or (item_tokens and sub.student not in item_tokens and max(map(len, item_tokens.values())) >= 3))
    if conflicts:
        sub.status, sub.reason = "unresolved", "Explicit attachment or consistent table identity conflicts with export folder."
    if not corroboration:
        sub.issue("identity_export_only", sub.sources[0], "Identity comes from the numeric parent in the matched bulk export.",
                  "info", status="identified")
    if sub.status == "unresolved":
        sub.issue("selection_unresolved", sub.sources[0], sub.reason, "blocker", action="Confirm identity or version")
    if sub.student in item_tokens and set(item_tokens) - {sub.student}:
        rows = sorted({row for token, refs in item_tokens.items() if token != sub.student for row in refs})
        sub.issue("item_id_prefix_conflict", sub.sources[0], f"Different numeric item ID prefix at source rows {rows}.",
                  action="Investigate in Phase 2")


NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z")


def value_kind(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return f"Excel {type(value).__name__}"
    if isinstance(value, (datetime,)):
        return "Excel date/time"
    stripped = display(value).strip()
    if NUMBER.fullmatch(stripped):
        return "integer text" if "." not in stripped else "decimal text"
    if isinstance(value, str) and value.startswith("="):
        return "formula"
    return "text"


def table_fields(sub, table):
    labels = table.labels
    missing_roles = sorted(CORE - set(labels))
    extra = [h or "(blank)" for h, label in zip(table.headers, labels) if not label]
    collisions = sorted(k for k, n in Counter(label for label in labels if label).items() if n > 1)
    if missing_roles or extra or collisions:
        sub.issue("schema_variant", table.reference,
                  f"Missing expected fields: {missing_roles}. Extra/unmapped headers: {extra}. Repeated fields: {collisions}.")
    missing, spaced, invalid, qualifiers = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(Counter)
    for i, header in enumerate(table.headers):
        label = labels[i]
        formats = Counter()
        for number, row in table.rows:
            value = display(row[i])
            stripped = value.strip()
            if stripped.casefold() in PLACEHOLDERS or not stripped:
                # A dash or placeholder is only a preliminary flag.
                if label:
                    missing[header].append(number)
                continue
            formats[value_kind(row[i])] += 1
            if label in {"item_id", "photo", "age", "condition", "price", "currency"} and value != stripped:
                spaced[header].append(number)
            if label in {"age", "condition", "price"}:
                if NUMBER.fullmatch(stripped):
                    n = Decimal(stripped)
                    if ((label in {"age", "price"} and n < 0)
                            or (label == "condition" and (n < 1 or n > 5 or n != int(n)))):
                        invalid[header].append(number)
                else:
                    text = re.sub(r"\d+(?:[.,]\d+)?", "#", stripped.casefold())
                    if "http" not in text and len(text) < 32:
                        qualifiers[header][text] += 1
        table.value_formats[f"{i + 1}:{header}"] = dict(formats)
    if missing:
        sub.issue("missing_value_evidence", table.reference, json_cell(dict(missing)), action="Quantify in Phase 2")
    if spaced or qualifiers:
        sub.issue("value_format_variants", table.reference,
                  f"Outer whitespace at rows {json_cell(dict(spaced))}. "
                  f"Non-plain numeric patterns {json_cell(dict(qualifiers))}.", "info", action="Review in Phases 1 and 2")
    if invalid:
        sub.issue("invalid_looking_numeric_values", table.reference, json_cell(dict(invalid)), action="Investigate in Phase 2")


def compare_tables(table, workbook_display=False):
    """Compare data representations without transforming the source or emitting values."""
    keys = [label or f"extra:{header.strip()}" for label, header in zip(table.labels, table.headers)]
    indices = sorted(range(len(keys)), key=keys.__getitem__)
    values = []
    for n, row in table.rows:
        cells = []
        for i in indices:
            value = display(row[i]).replace("\r\n", "\n").replace("\r", "\n")
            if keys[i] in {"age", "condition", "price"} and NUMBER.fullmatch(value):
                value = format(Decimal(value).normalize(), "f")
            cells.append(table.grouped_numbers.get((n, i), value) if workbook_display else value)
        values.append(tuple(cells))
    return tuple(keys[i] for i in indices), Counter(values)


def table_differences(first, second):
    if first.labels != second.labels or len(first.rows) != len(second.rows) or first.item_ids != second.item_ids:
        return "Candidate schemas, row counts, or item ID sequences differ."
    differences = defaultdict(list)
    for (row, a), (_, b) in zip(first.rows, second.rows):
        for label, x, y in zip(first.labels, a, b):
            if display(x) != display(y):
                if label in {"age", "price", "condition"} and all(NUMBER.fullmatch(display(v)) for v in (x, y)):
                    if Decimal(display(x)) == Decimal(display(y)):
                        continue
                differences[label].append(row)
    return "Differing fields and first table's source rows: " + json_cell(dict(differences)) + "."


def approved_source(sub, candidates):
    if len(candidates) != 2:
        return False
    csv_table, workbook = candidates
    if ((csv_table.format, csv_table.source_sha256) != ("CSV", ALTERNATE_CSV)
            or (workbook.format, workbook.source_sha256) != ("XLSX", APPROVED_WORKBOOK)
            or any(t.parse_warning or t.malformed for t in candidates)):
        return False
    sub.chosen = workbook
    sub.table_disagreement = table_differences(csv_table, workbook)
    sub.table_reason = (
        "Excel is authoritative under the approved fallback. It records ILS consistently "
        "where the CSV has one AED entry. The CSV has no independent revision marker."
    )
    sub.table_resolution = (
        f"ZIP member clocks show {csv_table.zip_member_time or 'unknown'} for CSV and "
        f"{workbook.zip_member_time or 'unknown'} for Excel. The workbook records its own "
        f"modification time as {workbook.workbook_modified or 'unknown'}. ZIP clocks have no stored "
        "timezone. The timestamps support a later workbook save. The CSV lacks an independent revision record. "
        "Source row 7 differs in currency (CSV AED, Excel ILS). Source row 13 differs in age (CSV blank, "
        "Excel Unknown). Excel is authoritative and both original files are preserved."
    )
    sub.issue("marketplace_table_discrepancy", workbook.reference, sub.table_resolution, "info",
              action="Use the workbook as the Phase 1 source", status="resolved")
    return True


def choose_table(sub):
    if not sub.tables:
        sub.blocked = True
        sub.table_reason = "No usable marketplace table identified."
        sub.issue("marketplace_table_missing", sub.sources[0], sub.table_reason, "blocker",
                  action="Obtain the table or confirm coverage")
        return
    if len(sub.tables) == 1:
        sub.chosen = sub.tables[0]
        sub.table_reason = "Only marketplace table. Supporting files and sheets are logged separately."
    else:
        ordered = sorted(sub.tables, key=lambda t: (t.format == "XLSX", t.reference))
        first, *others = ordered
        first_key = compare_tables(first)
        direct_equivalence = all(compare_tables(other) == first_key for other in others)
        equivalent = direct_equivalence or all(compare_tables(other, workbook_display=True) == first_key for other in others)
        equivalent &= not any(t.malformed or t.parse_warning for t in ordered)
        if equivalent:
            sub.chosen = first
            sub.table_reason = "Candidate tables have equivalent fields and row values. Delimited export preferred when available."
            if not direct_equivalence:
                sub.table_reason += " Excel's explicit thousands display format reproduces the delimited export."
            sub.issue("equivalent_table_copies", first.reference, sub.table_reason, "info", status="resolved")
        elif not approved_source(sub, ordered):
            sub.blocked = True
            sub.table_reason = "Marketplace candidates differ in fields, row values or parsing quality."
            sub.table_disagreement = " ".join(table_differences(first, other) for other in others)
            sub.issue("ambiguous_marketplace_tables", sub.sources[0],
                      " | ".join(f"{t.reference} ({len(t.rows)} rows)" for t in ordered) +
                      " | " + sub.table_disagreement,
                      "blocker", action="Confirm the authoritative table in this selected version")
    if sub.chosen and sub.chosen.parse_warning:
        sub.blocked = True
    if sub.table_errors or sub.inventory_errors:
        sub.blocked = True


def image_key(value):
    return unicodedata.normalize("NFC", value).casefold()


def compact_stem(value):
    stem = PurePosixPath(value).name
    while PurePosixPath(stem).suffix.lower() in IMAGE_EXT:
        stem = PurePosixPath(stem).stem
    return "".join(c for c in image_key(stem)
                   if c not in "_-" and not c.isspace() and unicodedata.category(c) != "Cc")


def item_number(value):
    match = re.fullmatch(r"[^\W\d_]*([0-9]+)", compact_stem(value))
    return int(match[1]) if match else None


def sequence_links(table, images, id_col):
    """Infer a local numeric key only when all rows and files form a bijection."""
    if id_col is None or not images or len(table.rows) != len(images):
        return {}
    ids = {n: item_number(display(row[id_col])) for n, row in table.rows}
    files = {item_number(PurePosixPath(k[-1]).name): k for k in images}
    if None in ids.values() or set(ids.values()) != set(files) or len(files) != len(images):
        return {}
    return {n: files[number] for n, number in ids.items()}


def match_photo(photo, table, images, names, stems, compact):
    """Use exact relative paths first, then only unique local name matches."""
    relative = photo.replace("\\", "/").removeprefix("./")
    leaf = PurePosixPath(relative)
    table_dir = PurePosixPath(table.locator[-1]).parent
    exact = {(str(table_dir / relative)), relative}
    matches = [key for key in images if key[:-1] == table.locator[:-1] and key[-1] in exact]
    if matches:
        return matches, "exact_path"
    candidate = names.get(image_key(leaf.name), [])
    if len(candidate) != 1:
        # Preserve any distinguishing suffix path, including subdirectories.
        suffix = "/" + image_key(relative)
        qualified = [key for key in candidate if image_key(key[-1]).endswith(suffix)]
        if qualified:
            candidate = qualified
    if candidate:
        return candidate, "filename"
    if candidate := stems.get(image_key(leaf.stem), []):
        return candidate, "stem"
    return compact.get(compact_stem(leaf.name), []), "normalized_stem"


def record_links(sub, table):
    names, stems, folders, compact = (defaultdict(list) for _ in range(4))
    for key in sorted(sub.images):
        member = PurePosixPath(key[-1])
        names[image_key(member.name)].append(key)
        stems[image_key(member.stem)].append(key)
        compact[compact_stem(member.name)].append(key)
        for parent in member.parents:
            folders[image_key(parent.name)].append(key)
    labels = table.labels
    photo_col = labels.index("photo") if "photo" in labels else None
    id_col = labels.index("item_id") if "item_id" in labels else None
    sequence = sequence_links(table, sub.images, id_col)
    uses, issues, matches = defaultdict(set), defaultdict(list), defaultdict(list)
    for row_number, row in table.rows:
        item_id = display(row[id_col]).strip() if id_col is not None else ""
        if item_id and item_id.casefold() not in PLACEHOLDERS:
            table.item_ids.append((row_number, item_id))
        photo = display(row[photo_col]).strip() if photo_col is not None else ""
        if photo.casefold() in PLACEHOLDERS or photo.lower().removeprefix(".") in IMAGE_SUFFIX_LABELS:
            if photo.casefold() not in PLACEHOLDERS:
                issues["photo_format_label_only"].append(row_number)
            photo = ""
        unresolved = False
        if not photo:
            table.links["rows_without_photo"] += 1
            issues["rows_without_photo"].append(row_number)
            unresolved = True
        elif re.match(r"(?:https?://|www\.)", photo, re.I):
            table.links["external_refs"] += 1
            issues["external_refs"].append(row_number)
            unresolved = True
        else:
            # Split only when the cell explicitly lists multiple image filenames.
            photos = re.split(r"(?i)(?<=[a-z0-9])\s*[;,\n]\s*(?=[^;,\n]+\.(?:jpe?g|png|avif|webp)\b)", photo)
            for value in photos:
                table.links["local_refs"] += 1
                targets, method = match_photo(value, table, sub.images, names, stems, compact)
                if len(targets) == 1:
                    target = targets[0]
                    uses[target].add(row_number)
                    matches[row_number].append((target, method))
                    table.links["linked_refs"] += 1
                    table.links["readable_linked_refs"] += int(sub.images[target][2])
                    table.photo_formats[method] += 1
                    if method in {"stem", "normalized_stem"}:
                        tag = "stem_linked_refs" if method == "stem" else "normalized_stem_linked_refs"
                        table.links[tag] += 1
                        issues[tag].append(row_number)
                    continue
                kind = "ambiguous_refs" if targets else "missing_refs"
                table.links[kind] += 1
                issues[kind].append(row_number)
                unresolved |= len(photos) == 1 and not targets
                if len(photos) == 1 and not targets and item_id:
                    leaf = PurePosixPath(value.replace("\\", "/"))
                    if image_key(leaf.stem) == image_key(item_id) and image_key(item_id) in folders:
                        group = folders[image_key(item_id)]
                        if len({key[:-1] + (str(PurePosixPath(key[-1]).parent),) for key in group}) == 1:
                            table.folder_links[row_number] = group
                            for target in group:
                                uses[target].add(row_number)
                                matches[row_number].append((target, "item_id_folder"))
        # Numeric inference preserves the missing explicit reference as an issue.
        if unresolved and item_id and row_number not in table.folder_links:
            candidates = stems.get(image_key(item_id), []) or compact.get(compact_stem(item_id), [])
            method = "item_id_stem"
            if not candidates and row_number in sequence:
                candidates = [sequence[row_number]]
                method = "item_id_sequence"
            if len(candidates) == 1:
                target = candidates[0]
                uses[target].add(row_number)
                table.inferred_links[row_number] = target
                matches[row_number].append((target, method))
    table.linked_images = set(uses)
    table.links["inferred_links"] = len(table.inferred_links) + sum(map(len, table.folder_links.values()))
    table.links["inferred_rows"] = len(table.inferred_links) + len(table.folder_links)
    table.links["linked_rows"] = len(set().union(*uses.values())) if uses else 0
    table.unreferenced = set(sub.images) - table.linked_images
    descriptions = {
        "rows_without_photo": "No explicit photo reference at rows",
        "photo_format_label_only": "Photo column gives a file format without any filename at rows",
        "external_refs": "External photo reference (not fetched) at rows",
        "stem_linked_refs": "Unique stem matched; literal filename absent at rows",
        "normalized_stem_linked_refs": "Unique stem matched after ignoring separators, whitespace, control characters or repeated extensions at rows",
        "missing_refs": "No direct or unique stem match at rows",
        "ambiguous_refs": "Multiple possible image targets at rows",
    }
    for key, rows in sorted(issues.items()):
        sub.issue(key, table.reference, f"{descriptions[key]} {sorted(set(rows))}.",
                  "info" if key in {"stem_linked_refs", "normalized_stem_linked_refs"} else "warning")
    if table.folder_links:
        details = {row: [" :: ".join(key) for key in group] for row, group in table.folder_links.items()}
        sub.issue("item_image_folder", table.reference, f"Matching item-specific folder at row(s) {json_cell(details)}.")
    if table.inferred_links:
        details = {row: " :: ".join(key) for row, key in table.inferred_links.items()}
        sub.issue("item_id_image_inference", table.reference,
                  f"Unique item-ID stem or complete one-to-one numeric key: {json_cell(details)}.")
    multiple = {" :: ".join(key): sorted(rows) for key, rows in uses.items() if len(rows) > 1}
    if multiple:
        table.links["images_used_by_multiple_rows"] = len(multiple)
        sub.issue("one_image_multiple_rows", table.reference, json_cell(multiple))
    if table.unreferenced:
        sub.issue("unreferenced_images", table.reference,
                  json_cell([" :: ".join(key) for key in sorted(table.unreferenced)]))
    local_ids = defaultdict(list)
    for number, item in table.item_ids:
        local_ids[item].append(number)
    repeated = [numbers for numbers in local_ids.values() if len(numbers) > 1]
    if repeated:
        sub.issue("duplicate_item_ids_within_table", table.reference, f"Repeated ID row sets: {repeated}.",
                  action="Investigate in Phase 2")
    flags = defaultdict(list)
    for reason, rows in sorted(issues.items()):
        for row in sorted(set(rows)):
            flags[row].append(reason)
    return matches, flags


def candidate_basis(sub):
    if sub.chosen:
        return [sub.chosen]
    return sub.tables


def audit_cross_submission(submissions, label):
    hashes, names, item_ids = defaultdict(list), defaultdict(list), defaultdict(list)
    for sub in submissions:
        for locator, (digest, _, _) in sorted(sub.images.items()):
            if digest:
                hashes[digest].append((sub, locator))
            names[image_key(PurePosixPath(locator[-1]).name)].append((sub, locator))
        tables = candidate_basis(sub)
        if tables and all(t.item_ids == tables[0].item_ids for t in tables[1:]):
            for row, item in tables[0].item_ids:
                item_ids[item].append((sub, (tables[0].reference, str(row))))
    duplicate_groups = [refs for refs in hashes.values() if len(refs) > 1]
    collision_groups = [refs for refs in names.values() if len(refs) > 1]
    item_collision_groups = [refs for refs in item_ids.values() if len({s.key for s, _ in refs}) > 1]
    if label == "selected":
        for kind, groups in (("byte_identical_image_group", duplicate_groups),
                             ("image_basename_collision", collision_groups),
                             ("item_id_collision_across_submissions", item_collision_groups)):
            for group in groups:
                first, locator = group[0]
                first.issue(kind, " :: ".join(locator),
                            json_cell([" :: ".join(loc) for _, loc in group]),
                            action="Investigate in Phase 2" if kind != "image_basename_collision"
                            else "Use submission-scoped paths in Phase 1")
    return {
        "image_digests": len(hashes),
        "hash_groups": len(duplicate_groups),
        "hash_members": sum(map(len, duplicate_groups)),
        "basename_groups": len(collision_groups),
        "item_id_values": len(item_ids),
        "item_id_collisions": len(item_collision_groups),
    }


def range_sum(submissions, measure):
    """Report an interval whenever plausible tables give different counts."""
    ranges = [[measure(t) for t in candidate_basis(s)] for s in submissions]
    known = [r for r in ranges if r]
    return count_range(sum(map(min, known)), sum(map(max, known)), len(ranges) - len(known))


def count_range(low, high, unknown=0):
    label = f"{low:,}" if low == high else f"{low:,}–{high:,}"
    return f"{label} (+ {unknown} unknown)" if unknown else label


def table_count(sub, measure):
    values = {measure(t) for t in candidate_basis(sub)}
    return next(iter(values)) if len(values) == 1 else None


def audit_version(sub):
    audit_identity(sub)
    for (extension, detected), refs in sorted(sub.image_extensions.items()):
        sub.issue("image_extension", sub.sources[0], f"{len(refs)} {extension} files actually contain {detected}. "
                  + json_cell(refs))
    if sub.ancillary:
        sub.issue("supporting_or_system_entries", sub.sources[0],
                  json_cell([" :: ".join(locator) for locator in sub.ancillary]),
                  "info", action="Preserve and keep outside the marketplace tables and image counts", status="identified")
    for table in sub.tables:
        table_fields(sub, table)
        record_links(sub, table)
    choose_table(sub)
    observed_rows = sorted({len(t.rows) for t in sub.tables})
    link_details = [f"{t.links['linked_refs']} direct/filename links, {t.links['inferred_links']} "
                    f"inferred files, {t.links['missing_refs']} missing refs, {len(t.unreferenced)} "
                    "unreferenced files" for t in candidate_basis(sub)]
    if len(sub.images) != EXPECTED_ITEMS or observed_rows != [EXPECTED_ITEMS]:
        sub.issue("count_discrepancy", sub.sources[0],
                  f"Expected {EXPECTED_ITEMS} rows and images. Candidate row counts {observed_rows}. "
                  f"Image files {len(sub.images)}. Link coverage: {link_details}.")


def manifest_row(root, export_path, extracted_path, sub):
    table = sub.chosen
    basis = candidate_basis(sub)
    duplicate_ids = table_count(sub, lambda t: len(t.item_ids) - len({item for _, item in t.item_ids}))
    rows = table_count(sub, lambda t: len(t.rows))
    distinct_ids = table_count(sub, lambda t: len({item for _, item in t.item_ids}))
    table_status = "usable" if table else "ambiguous" if sub.tables else "non-usable"
    return {
        "student_id": sub.student,
        "submission_id": sub.key,
        "original_submission_paths": json_cell(sub.sources),
        "bulk_export_path": export_path.relative_to(root).as_posix(),
        "bulk_export_members": json_cell([(root / p).relative_to(extracted_path).as_posix() for p in sub.sources]),
        "submission_timestamp": "",
        "timestamp_source": "Bulk ZIP member DOS time (export chronology only, timezone unrecorded)",
        "export_attachment_timestamps": json_cell([datetime(*v).isoformat() for v in sub.chronology]),
        "selection_status": sub.status,
        "identity_evidence": sub.identity,
        "selection_reason": sub.reason,
        "table_status": table_status,
        "table_selection_reason": sub.table_reason,
        "table_candidate_disagreement": sub.table_disagreement,
        "table_resolution_evidence": sub.table_resolution,
        "tabular_data_locator": json_cell(list(table.locator)) if table else "",
        "table_sheet": table.sheet if table else "",
        "table_format": table.format if table else "",
        "table_encoding": table.encoding if table else "",
        "table_delimiter": table.delimiter if table else "",
        "table_header_row": table.header_row if table else "",
        "table_candidates": json_cell([t.spec() for t in sub.tables]),
        "image_file_locators": json_cell([list(k) for k in sorted(sub.images)]),
        "image_formats": json_cell(dict(Counter(fmt or "unknown" for _, fmt, _ in sub.images.values()))),
        "data_rows": rows,
        "distinct_nonblank_item_ids": distinct_ids,
        "repeated_item_ids": duplicate_ids,
        "image_files": len(sub.images),
        "image_files_readable": sum(ok for _, _, ok in sub.images.values()),
        "image_files_unreadable": sum(not ok for _, _, ok in sub.images.values()),
        "image_files_with_extension_mismatch": sum(map(len, sub.image_extensions.values())),
        "embedded_workbook_media": sub.embedded,
        "auxiliary_table_rows": sub.auxiliary_rows,
        "explicit_local_photo_references": table_count(sub, lambda t: t.links["local_refs"]),
        "linked_photo_references": table_count(sub, lambda t: t.links["linked_refs"]),
        "readable_linked_photo_references": table_count(sub, lambda t: t.links["readable_linked_refs"]),
        "missing_photo_references": table_count(sub, lambda t: t.links["missing_refs"]),
        "ambiguous_photo_references": table_count(sub, lambda t: t.links["ambiguous_refs"]),
        "unreferenced_image_files": table_count(sub, lambda t: len(t.unreferenced)),
        "inferred_item_image_links": table_count(sub, lambda t: t.links["inferred_links"]),
        "rows_with_image_link": table_count(sub, lambda t: t.links["linked_rows"]),
        "ancillary_locators": json_cell([list(k) for k in sorted(sub.ancillary)]),
        "basic_audit_status": ("blocked" if sub.blocked else "issues" if sub.issues else "ok"),
        "phase1_input_eligible": "yes" if sub.status == "selected" and not sub.blocked else "no",
        "metric_basis": ("chosen table" if table else "candidate consensus only" if basis else "unknown"),
    }


def metrics(versions, cross):
    def link_metric(key):
        return range_sum(versions, lambda t: t.links[key])

    return {
        "Marketplace data rows, one representation per version": range_sum(versions, lambda t: len(t.rows)),
        "Marketplace candidate rows, including alternate tables": sum(len(t.rows) for s in versions for t in s.tables),
        "Supporting provenance table rows identified": sum(s.auxiliary_rows for s in versions),
        "Standalone image files": sum(len(s.images) for s in versions),
        "Readable standalone images": sum(ok for s in versions for _, _, ok in s.images.values()),
        "Unreadable standalone image files": sum(not ok for s in versions for _, _, ok in s.images.values()),
        "Images with extension differing from decoded format": sum(
            len(refs) for s in versions for refs in s.image_extensions.values()),
        "Unreadable or unrecognized table files": sum(s.table_errors for s in versions),
        "Other unreadable or ambiguous archive entries": sum(s.inventory_errors for s in versions),
        "Embedded workbook media entries": sum(s.embedded for s in versions),
        "Explicit local photo references": link_metric("local_refs"),
        "Resolved local photo references": link_metric("linked_refs"),
        "Resolved references to readable images": link_metric("readable_linked_refs"),
        "Of resolved references, linked by unique stem": link_metric("stem_linked_refs"),
        "Of resolved references, linked by normalized stem": link_metric("normalized_stem_linked_refs"),
        "Missing local references after filename/stem lookup": link_metric("missing_refs"),
        "Ambiguous local photo references": link_metric("ambiguous_refs"),
        "External photo references": link_metric("external_refs"),
        "Rows without explicit photo": link_metric("rows_without_photo"),
        "Inferred item-to-file links": link_metric("inferred_links"),
        "Rows with at least one direct or inferred file link": link_metric("linked_rows"),
        "Files linked from multiple rows": link_metric("images_used_by_multiple_rows"),
        "Image files without a direct or inferred link": range_sum(versions, lambda t: len(t.unreferenced)),
        "Distinct standalone image SHA-256 hashes": cross["image_digests"],
        "Byte-identical image groups": cross["hash_groups"],
        "Image files in byte-identical groups": cross["hash_members"],
        "Case-insensitive basename collision groups": cross["basename_groups"],
        "Rows with a nonblank item ID": range_sum(versions, lambda t: len(t.item_ids)),
        "Distinct observed nonblank item ID strings (unambiguous ID lists)": cross["item_id_values"],
        "Item ID strings shared across versions in scope": cross["item_id_collisions"],
    }


def summary(subs, attachment_count, sequence_ok, regressions, fingerprint,
            all_cross, selected_cross):
    selected = [s for s in subs if s.status == "selected"]
    by_id = Counter(s.student for s in subs if s.student)
    status = Counter(s.status for s in subs)
    blocked = [s for s in selected if s.blocked]
    title = [
        "# Assignment 2 Phase 0 audit", "", "## A. Dataset overview", "",
        f"- {len(by_id)} student IDs identified against an expected {EXPECTED_STUDENTS}.",
        f"- {attachment_count} original attachments make up {len(subs)} submission versions. "
        f"{sum(v > 1 for v in by_id.values())} students submitted multiple versions.",
        f"- {len(selected)} latest versions selected and {status['superseded']} superseded. "
        f"Version decisions pending: {status['unresolved']}. Unidentified versions: {sum(not s.student for s in subs)}.",
        "- The numeric export groups were cross-checked against attachment labels, member paths and item or student ID "
        "fields when available. No independent class roster was supplied. The folder count verifies coverage against the "
        "reported headcount.",
        f"- All {attachment_count} extracted attachments matched the original bulk ZIP members by path and SHA-256. "
        "Each was counted once. A second SHA-256 check confirmed the bulk ZIP and attachments retained the same contents.",
        f"- The bulk ZIP SHA-256 is `{fingerprint}`.",
        "", "## B. Dataset counts", "",
        "| Count | All versions | Selected versions |", "|---|---:|---:|",
    ]
    for (name, left), right in zip(metrics(subs, all_cross).items(), metrics(selected, selected_cross).values()):
        left = f"{left:,}" if isinstance(left, int) else left
        right = f"{right:,}" if isinstance(right, int) else right
        title.append(f"| {name} | {left} | {right} |")
    count_format = (
        "\nRanges cover alternative marketplace tables. Rows are parsed, non-empty item records, excluding headers, "
        "blank rows, and entries without item evidence. The manifest identifies candidate, preamble and footer evidence. "
        "Candidate-row totals include alternate exports of the same items. Workbook media entries and standalone images "
        "use distinct counts. System artifacts are listed in the issues CSV.\n\n"
        "Photo references count cell entries naming a local file, including multiple names in one cell when present. "
        "Resolution uses exact archive paths or unique basename matches. Unique stems and separator or repeated "
        "extension variants are flagged. Item ID inference uses a unique full stem or a complete one-to-one number "
        "match within a submission. A missing explicit filename can coexist with an inferred item-to-file link. "
        "Unreferenced files are those without either "
        "a resolved local name or an inferred association. SHA-256 groups count byte equality among standalone images. "
        "The audit did not measure visual similarity or verify the photographed object against the listing. "
        "Distinct item ID strings are a preliminary check because student-specific IDs can be missing or repeated."
    )
    title += [count_format, "", "## C. Schema overview", ""]
    bases = [t for s in selected for t in candidate_basis(s)]
    fields = defaultdict(Counter)
    shapes = defaultdict(Counter)
    for table in bases:
        for pos, (header, label) in enumerate(zip(table.headers, table.labels), 1):
            fields[label or "unmapped"][header.strip() or "(blank)"] += 1
            if label:
                shapes[label].update(table.value_formats.get(f"{pos}:{header}", {}))
    title += [
        f"Observed formats across {len(bases)} chosen or unresolved candidate tables: "
        + ", ".join(f"{fmt} ({n})" for fmt, n in sorted(Counter(t.format for t in bases).items())) + ".",
        "", "| Field | Headers observed | Files or sheets lacking the field |",
        "|---|---|---:|",
    ]
    for k in (*ALIASES, "unmapped"):
        if k == "student_id" and not fields[k]:
            continue
        labels = ", ".join(f"`{v}`" for v in sorted(fields[k])) or "—"
        missing = sum(k not in table.labels for table in bases) if k != "unmapped" else "—"
        title.append(f"| {k.replace('_', ' ')} | {labels} | {missing} |")
    for label in ("item_id", "age", "condition", "price", "currency", "photo"):
        title.append(f"- **{label.replace('_', ' ').capitalize()}**. " +
                     ", ".join(f"{kind} ({n})" for kind, n in sorted(shapes[label].items())) + ".")
    version_rows = [(s, sorted({len(t.rows) for t in s.tables})) for s in selected]
    anomalies = [f"| {s.key} | {', '.join(map(str, counts)) or 'unknown'} | {len(s.images)} | "
                 f"{table_count(s, lambda t: t.links['linked_refs'])} | {table_count(s, lambda t: t.links['missing_refs'])} | "
                 f"{table_count(s, lambda t: len(t.unreferenced))} |"
                 for s, counts in version_rows if counts != [EXPECTED_ITEMS] or len(s.images) != EXPECTED_ITEMS]
    images = sum(len(s.images) for s in selected)
    expected = EXPECTED_STUDENTS * EXPECTED_ITEMS
    title += [
        "", "## D. Important findings", "",
        f"- The expected class baseline is {expected:,} rows and {expected:,} standalone images. "
        f"The audit verified **{images:,} standalone image files**, a difference of **{images - 1801:+,}** from the reported 1,801.",
        f"- The selected set has **{selected_cross['image_digests']:,} distinct image hashes** across {images:,} "
        f"physical files. A total of {selected_cross['hash_members']} files belong to "
        f"{selected_cross['hash_groups']} byte-identical groups. The counting method behind the original report is unknown.",
        "- Price, currency, age, and condition were inspected as recorded. The source uses numeric spreadsheet cells "
        "and numeric or qualified text. Age headers mix unspecified units with explicit years, and age values include "
        "other unit wording. The issues CSV records representative formats and row locations for Phase 1 and Phase 2.",
        "", "| Attachment reference | Candidate item rows | Images | Resolved refs | Missing refs | Unreferenced files |",
        "|---|---:|---:|---:|---:|---:|", *anomalies, "",
    ]
    for sub, counts in version_rows:
        table = sub.chosen
        if len(sub.images) == 16 and counts == [16] and table and table.links["linked_refs"] == 16:
            distinct = len({digest for digest, _, _ in sub.images.values() if digest})
            title += ["", f"- The 16-image submission (attachment `{sub.key}`) has 16 marketplace rows and "
                      f"16 resolved references, with {distinct} distinct image hashes within the submission. "
                      "The extra file corresponds to an extra item row."]
        if len(sub.images) > EXPECTED_ITEMS and table and table.folder_links:
            for row, group in table.folder_links.items():
                hashes = len({sub.images[locator][0] for locator in group})
                title.append(f"- Attachment `{sub.key}` has {len(sub.images)} files and {len(table.rows)} item rows. "
                             f"Worksheet row {row} names an absent single file. Its matching item-specific folder "
                             f"contains {len(group)} images with {hashes} distinct hashes. The folder supports an "
                             "association with that row, pending review of the individual photos.")
    title += [
        "", "## E. Decisions and unresolved issues", "",
        "- **Chronology.** Bulk ZIP member timestamps and numbered attachment labels agree. "
        f"All attachment numbers unique and seven digits: {'yes' if sequence_ok else 'no'}. "
        f"Timestamp regressions in increasing attachment order: {regressions}. ZIP time is recorded as "
        "export evidence. Official submission-system times and timezone were unavailable. The extracted file "
        "timestamps and submission completeness played no part in selection.",
        "- **Split submission.** The simultaneously exported `dataset.csv` and `images.zip` contain complementary "
        "data and images for the same export group. The manifest records both paths under one version.",
        "- **Table selection.** The audit compares field meanings, row contents, newline encodings and plain numeric "
        "representations to recognize equivalent CSV and Excel exports. Explicit Excel thousands formatting can "
        "explain a match. Non-equivalent marketplace candidates stay "
        "visible for review. Ancillary provenance files and workbook sheets stay outside the marketplace count.",
    ]
    title.extend(f"- **Resolved table discrepancy for attachment `{s.key}`.** {s.table_resolution}" for s in selected
                 if s.table_resolution)
    if blocked:
        issue_scope = "One selected version has" if len(blocked) == 1 else f"{len(blocked)} selected versions have"
        title += [
            f"- **Decision required.** {issue_scope} a blocking input issue. Review "
            "`ambiguous_marketplace_tables` or the relevant parse/inventory issue in the issues CSV. "
            "The manifest leaves the table locator blank when the correct source is uncertain.",
        ]
        title.extend(f"  - Attachment `{s.key}`. {s.table_reason} {s.table_disagreement}" for s in blocked)
    title += [
        "- **Later review.** Investigate missing, inferred and mismatched photo links in Phase 1. Check missing "
        "values, duplicate IDs, byte-identical images and questionable values in Phase 2. Preserve the original records.",
        "", "## F. Readiness assessment", "",
        ("**Blocked for Phase 1.** Resolve the selected input issues and any unresolved version decisions first."
         if blocked or status["unresolved"] else
         "**Ready for Phase 1 with documented issues.** Phase 1 can begin upon approval of this audit."),
        "", "The audit inspected the three-page assignment brief and the 76-page lecture chapter. It uses the "
        "lecture's distinction between structured and unstructured data, schema integration, and checks for "
        "incomplete, noisy and inconsistent data. Phase 0 produced no integrated dataset, cleaning or EDA.", "",
    ]
    return "\n".join(title)


def write_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--export", help="Bulk ZIP filename inside the source root")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.export:
        export = (root / args.export).resolve()
    else:
        matches = [path for path in root.glob("*.zip") if path.with_suffix("").is_dir()]
        if len(matches) != 1:
            parser.error("Specify --export or place exactly one bulk ZIP and its matching extracted directory in --root")
        export = matches[0].resolve()
    extracted = export.with_suffix("")
    if not export.is_relative_to(root):
        parser.error("The export must be inside the project root")
    entries, mirrors = discover(root, export, extracted)
    original_digest = digest_file(export)
    subs, valid_sequence, regressions = form_versions(entries)
    for sub in subs:
        for source in sub.sources:
            audit_attachment(sub, root, source)
        audit_version(sub)
    selected = [s for s in subs if s.status == "selected"]
    unresolved_ids = {s.student for s in subs if s.status == "unresolved"}
    for sub in selected:
        if sub.student in unresolved_ids:
            sub.status = "unresolved"
            sub.reason = "Another version in the same export folder has unresolved identity or order."
            sub.issue("selection_unresolved", sub.sources[0], sub.reason, "blocker", action="Confirm identity or version")
    selected = [s for s in subs if s.status == "selected"]
    assert len({s.student for s in selected}) == len(selected)
    assert sum(len(s.sources) for s in subs) == len(entries)
    for sub in subs:
        for table in sub.tables:
            assert table.links["local_refs"] == sum(table.links[k] for k in ("linked_refs", "missing_refs", "ambiguous_refs"))
            assert len(sub.images) == len(table.linked_images) + len(table.unreferenced)
    all_cross = audit_cross_submission(subs, "all")
    selected_cross = audit_cross_submission(selected, "selected")
    if digest_file(export) != original_digest or any(
        digest_file(extracted / relative) != digest for relative, digest in mirrors.items()
    ):
        raise RuntimeError("A source changed during the audit. Output was not written.")
    manifest = [manifest_row(root, export, extracted, sub) for sub in subs]
    issues = [issue for sub in subs for issue in sub.issues]
    report = summary(subs, len(entries), valid_sequence, regressions, original_digest.hex(),
                     all_cross, selected_cross)
    out = root / "Audit"
    if out.resolve() != out:
        raise ValueError("Audit output directory must be a regular project directory.")
    out.mkdir(exist_ok=True)
    write_csv(out / "phase0_submission_manifest.csv", manifest, list(manifest[0]))
    write_csv(out / "phase0_issues.csv", issues, ISSUE_COLUMNS)
    (out / "phase0_summary.md").write_text(report, encoding="utf-8")
    print(f"Audited {len(entries)} attachments in {len(subs)} versions. "
          f"Selected {len(selected)}. Wrote three files to Audit/.")


if __name__ == "__main__":
    main()

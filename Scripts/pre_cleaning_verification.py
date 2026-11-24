"""Reconcile Phases 0–2 and generate a local, resumable pre-cleaning review."""

import argparse
import csv
import hashlib
import io
import json
import math
import re
import statistics
import textwrap
from collections import Counter, defaultdict
from decimal import Decimal
from itertools import combinations
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont, ImageOps

import phase0_audit as audit
import phase1_integration as integration
import phase2_quality_assessment as quality


APPROVED_COMMAS = {"2,000", "70,000", "93,000", "245,000", "270,000", "350,000"}
APPROVED_AGE_TYPO = "3 moths"
SNAPSHOT_DATE = "2026-11-25"
QUOTE_DATE = "2026-11-24"
BOI = "https://boi.org.il/PublicApi/GetExchangeRates"
ECB = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
UAE = "https://centralbank.ae/umbraco/Surface/Exchange/GetExchangeRateAllCurrency"
LIBYA = "https://cbl.gov.ly/en/currency-exchange-rates/"
TAIWAN = "https://www.cbc.gov.tw/tw/lp-645-1-1-60.html"

# Public reference observations as published at the checkpoint's retrieval.
# Preserve quote factors, directions and exact dates separately from derived rates.
DIRECT = dict(AUD="2.2201", CHF="3.9864", EGP="0.0617", EUR="3.6627", GBP="4.3757",
              JOD="4.7173", SEK="0.3262", USD="3.345")
FX_CROSSES = {
    "AED": ("3.345", "3.6725", "USD", "Bank of Israel / Central Bank of the UAE", BOI, UAE),
    "INR": ("3.6618", "101.8670", "EUR", "European Central Bank", ECB, ECB),
    "IQD": ("0.002422", "1.100111", "AED", "Central Bank of the UAE", UAE, UAE),
    "LYD": ("3.345", "6.4848", "USD", "Bank of Israel / Central Bank of Libya", BOI, LIBYA),
    "SAR": ("0.978655", "1.100111", "AED", "Central Bank of the UAE", UAE, UAE),
    "SGD": ("3.6618", "1.4141", "EUR", "European Central Bank", ECB, ECB),
    "TWD": ("3.345", "32.939", "USD", "Bank of Israel / Central Bank of Taiwan", BOI, TAIWAN),
}


def rates(currencies):
    rows = []
    for code in sorted(currencies):
        if code == "ILS":
            numerator, denominator, source, url, other = "1", "1", "Identity", "", ""
            formula, date = "Identity", SNAPSHOT_DATE
        elif code in DIRECT:
            numerator, denominator = DIRECT[code], "1"
            source, url, other = "Bank of Israel", BOI, ""
            formula, date = f"{numerator} ILS per {code}", QUOTE_DATE
        else:
            numerator, denominator, bridge, source, url, other = FX_CROSSES[code]
            if bridge == "AED":
                formula = f"{numerator} AED/{code} ÷ {denominator} AED/ILS"
            else:
                formula = f"{numerator} ILS/{bridge} ÷ {denominator} {code}/{bridge}"
            date = QUOTE_DATE
        result = Decimal(numerator) / Decimal(denominator)
        if not result.is_finite() or result <= 0:
            raise ValueError(f"Invalid conversion rate for {code}.")
        rows.append(dict(currency_code=code, ils_per_unit=str(result), direction=f"1 {code} to ILS",
                         rate_date=date, retrieval_date=SNAPSHOT_DATE, source=source, source_url=url,
                         second_source_url=other, numerator=numerator, denominator=denominator, calculation=formula))
    return rows


def require(condition, message):
    if not condition:
        raise ValueError(message)


def independent_inventory(root, manifest, selected):
    """Check the export itself, using a different grouping and chronology path."""
    export_name, = {r["bulk_export_path"] for r in manifest}
    with ZipFile(root / export_name) as bundle:
        expected = {key for r in manifest for key in json.loads(r["bulk_export_members"])}
        members = {i.filename: i.date_time for i in bundle.infolist() if not i.is_dir()}
    require(expected == members.keys(), "The manifest attachment inventory differs from the export.")
    groups = defaultdict(list)
    for member, date in members.items():
        path = PurePosixPath(member)
        number, filename = path.name.split("-", 1)
        groups[path.parent.name].append((date, number, filename))
    chronology = sorted((n, date) for entries in groups.values() for date, n, _ in entries)
    require(len({n for n, _ in chronology}) == len(chronology)
            and [v for _, v in chronology] == sorted(v for _, v in chronology), "Export chronology failed.")
    chosen = {r["student_id"]: r for r in selected}
    require(groups.keys() == chosen.keys(), "A student group was omitted.")
    version_count = 0
    for student, entries in groups.items():
        latest = max(entries)
        split = len(entries) == 2 and entries[0][0] == entries[1][0] and {
            name.casefold() for _, _, name in entries
        } == {"dataset.csv", "images.zip"}
        expected_latest = {n for _, n, _ in entries} if split else {latest[1]}
        require(set(chosen[student]["submission_id"].split("+")) == expected_latest,
                "Selection does not match the independently reconstructed latest version.")
        version_count += 1 if split else len(entries)
    require(version_count == len(manifest), "Submission version count differs.")
    # The explicit Phase 0 authority decision is bound to source bytes.
    authorized = [r for r in selected if r["table_resolution_evidence"]]
    require(len(authorized) == 1, "Approved workbook decision missing or duplicated.")
    _, approved = integration.selected_table(authorized[0])
    originals = {t["source_sha256"] for t in json.loads(authorized[0]["table_candidates"])}
    require(approved["format"] == "XLSX" and approved["source_sha256"] == audit.APPROVED_WORKBOOK
            and audit.ALTERNATE_CSV in originals, "Approved Excel source drifted.")
    return len(members), len(groups), version_count


def independent_sources(root, records, selected):
    """Independently read source layouts and account for unexported physical rows."""
    by_submission = defaultdict(dict)
    for row in records:
        by_submission[row["submission_id"]][int(row["source_row"])] = row
    result, excluded = Counter(), []
    for source in selected:
        locator, spec = integration.selected_table(source)
        payload = integration.read_selected_files(root, json.loads(source["original_submission_paths"]),
                                                  [locator])[locator]
        wanted = by_submission[source["submission_id"]]
        if spec["format"] == "XLSX":
            with io.BytesIO(payload) as stream:
                book = load_workbook(stream, read_only=True, data_only=False)
                rows = dict(enumerate(book[spec["sheet"]].values, 1))
                book.close()
        else:
            reader = csv.reader(io.StringIO(payload.decode(spec["encoding"]), newline=""),
                                delimiter=spec["delimiter"], strict=True)
            rows = {}
            while True:
                start = reader.line_num + 1
                values = next(reader, None)
                if values is None:
                    break
                rows[start] = values
        header_row = spec["header_row"]
        header = rows[header_row]
        for number, values in rows.items():
            if number == header_row or not any(str(v).strip() for v in values if v is not None):
                continue
            if number not in wanted:
                nonblank = [(i + 1, str(v)) for i, v in enumerate(values) if v is not None and str(v).strip()]
                excluded.append((source["submission_id"], number, nonblank))
                continue
            row = wanted[number]
            require(json.loads(row["source_table"]) == list(locator) and row["source_sheet"] == spec["sheet"],
                    "Exported source locator differs from original selection.")
            # Align by source headers and original worksheet/CSV positions. For broken
            # rows, compare the original fragments and independently anchored suffix.
            extra = json.loads(row["source_extras"])
            stored = extra.get("parsed_source_fields")
            if stored:
                require(stored == list(values), "Malformed row fragments differ from original CSV.")
                require(tuple(row[c] for c in integration.RECOVERED_TAIL) == tuple(values[-5:]),
                        "A structurally recovered suffix differs from its source.")
                result[extra["alignment"]] += 1
            for index, name in enumerate(header):
                field = integration.SOURCE_COLUMNS.get(integration.field_role(name))
                if not field or (stored and field in integration.RECOVERED_TAIL):
                    continue
                if stored and field == "description" and extra["alignment"] == "space_prefixed_quoted_description":
                    text = spec["delimiter"].join(values)
                    parsed = next(csv.reader([text], delimiter=spec["delimiter"], skipinitialspace=True, strict=True))
                    require(len(parsed) == len(header) and parsed[index].strip() == row[field].strip(),
                            "Quoted description differs on independent CSV reparse.")
                    continue
                value = values[index] if index < len(values) else None
                require(row[field] == ("" if value is None else str(value)),
                        f"Independent source field differs for {field}.")
            result["rows"] += 1
        require(wanted.keys() <= rows.keys(), "An exported source row does not exist.")
    require(result["rows"] == len(records), "Source rows do not reconcile.")
    return result, excluded


def compare_scopes(scopes, price, ages, info):
    for scope in scopes:
        attribute, unit, label = scope["attribute"], scope["unit"], scope["scope"]
        cohort = ages if attribute == "age_raw" else price[unit]
        values = [value for row, value in cohort if label == "All eligible" or info[row["record_id"]]["family"] == label]
        require(scope["n"] == len(values), "IQR scope count differs.")
        if "q1" not in scope:
            continue
        q1, median, q3 = statistics.quantiles(values, n=4, method="inclusive")
        mean, sd = statistics.mean(values), statistics.stdev(values)
        gap = q3 - q1
        low, high = q1 - 1.5 * gap, q3 + 1.5 * gap
        expected = {"q1": q1, "median": median, "q3": q3, "iqr": gap, "mean": mean, "sd": sd,
                    "lower": low, "upper": high, "skew": 3 * (mean - median) / sd if sd else None,
                    "low": sum(v < low for v in values), "high": sum(v > high for v in values)}
        require(all(scope[k] == v if v is None else math.isclose(scope[k], v, rel_tol=1e-10, abs_tol=1e-11)
                    for k, v in expected.items()), "Independent IQR, skewness, or descriptive statistics differ.")


def approved_diagnostics(records, info, fx):
    revised = {key: value.copy() for key, value in info.items()}
    applied_commas = Counter()
    age_corrections = 0
    for row in records:
        value = revised[row["record_id"]]
        if row["price_raw"] in APPROVED_COMMAS and value["price_kind"] == "ambiguous_separator":
            value.update(price=Decimal(row["price_raw"].replace(",", "")), price_kind="supported_grouping")
            applied_commas[row["price_raw"]] += 1
        if row["age_raw"] == APPROVED_AGE_TYPO:
            value.update(age=Decimal("0.25"), age_kind="months", age_evidence="user-approved typo")
            age_corrections += 1
    require(set(applied_commas) == APPROVED_COMMAS and all(n == 1 for n in applied_commas.values())
            and age_corrections == 1, "The approved interpretations no longer match their source inventory.")
    comparable_prices = {
        key: float(value["price"] * fx[value["currency"]]) for key, value in revised.items()
        if value["price_kind"] in {"plain", "supported_grouping", "zero_documented"} and value["currency"] in fx
    }
    valid_ages = {key: float(v["age"]) for key, v in revised.items() if v["age"] is not None and v["age"] >= 0}
    paired = comparable_prices.keys() & valid_ages.keys()
    complete = [row for row in records if row["record_id"] in paired
                and revised[row["record_id"]]["condition"] is not None
                and all(not quality.missing_kind(k, row[k]) for k in ("title", "description", "category"))]
    observed_ages = list(valid_ages.values())
    comparisons = []
    pooled_age = [valid_ages[key] for key in sorted(paired)]
    pooled_price = [comparable_prices[key] for key in sorted(paired)]
    for label, fill in (("available cases", None), ("global mean", statistics.mean(observed_ages)),
                        ("global median", statistics.median(observed_ages))):
        ages, prices = (pooled_age, pooled_price) if fill is None else (
            [valid_ages.get(key, fill) for key in sorted(comparable_prices)],
            [comparable_prices[key] for key in sorted(comparable_prices)],
        )
        comparisons.append((label, len(ages), statistics.stdev(ages), statistics.correlation(ages, prices)))
    return revised, len(comparable_prices), len(valid_ages), len(complete), comparisons


def load_judgments(path, keys):
    if not path.exists():
        return {}
    rows, _ = integration.read_csv(path)
    result = {tuple(row[key] for key in keys): row for row in rows}
    require(len(result) == len(rows), f"Repeated judgment in {path.name}.")
    return result


def sheet(path, cards, columns, item_size):
    """Private local previews with aspect ratio retained and a readable index."""
    width, height = item_size
    rows = (len(cards) + columns - 1) // columns
    page = Image.new("RGB", (columns * width, rows * height), "#f6f5f1")
    draw = ImageDraw.Draw(page)
    try:
        regular = ImageFont.truetype("arial.ttf", 15)
        bold = ImageFont.truetype("arialbd.ttf", 17)
    except OSError:
        regular = ImageFont.load_default(size=15)
        bold = ImageFont.load_default(size=17)
    for index, (caption, subtitle, payload) in enumerate(cards):
        x, y = (index % columns) * width, (index // columns) * height
        with Image.open(io.BytesIO(payload)) as raw:
            photo = ImageOps.exif_transpose(raw).convert("RGB")
            photo.thumbnail((width - 14, height - 72), Image.Resampling.LANCZOS)
            page.paste(photo, (x + (width - photo.width) // 2, y + (height - 65 - photo.height) // 2))
        draw.text((x + 7, y + height - 61), caption, fill="#173945", font=bold)
        draw.multiline_text((x + 7, y + height - 40),
                            "\n".join(textwrap.wrap(subtitle, width=max(19, width // 8))[:2]),
                            fill="#192832", font=regular, spacing=1)
    page.save(path, quality=91)


def visual_packets(root, records, selected, candidate_pairs, gallery):
    """Generate an inventory independent of manual judgments, and resume by index."""
    links = defaultdict(list)
    for row in records:
        for entry in json.loads(row["image_links"]):
            links[tuple(entry["locator"])].append((row, entry["method"]))
    private = root / "Working" / "PreCleaning"
    private.mkdir(parents=True, exist_ok=True)
    annotations = load_judgments(private / "visual_judgments.csv", ("image_id",))
    pair_notes = load_judgments(private / "duplicate_judgments.csv", ("first", "second"))
    photos, objects, ids_by_record = [], {}, defaultdict(list)
    for source in selected:
        locators = [tuple(loc) for loc in json.loads(source["image_file_locators"])]
        payloads = integration.read_selected_files(root, json.loads(source["original_submission_paths"]), locators)
        for locator in sorted(locators):
            data = payloads[locator]
            image_id = f"I{len(photos) + 1:04d}"
            linked = links[locator]
            row = linked[0][0] if len(linked) == 1 else None
            if row:
                ids_by_record[row["record_id"]].append(image_id)
            note = annotations.get((image_id,), {})
            if note:
                require(note["verdict"] in {"visually consistent", "visually inconsistent", "uncertain",
                                           "insufficient visual information", "unlinked image"}
                        and note["observed_type"] and note["evidence"], "An image judgment lacks visual evidence.")
            photos.append(dict(image_id=image_id, locator=audit.json_cell(list(locator)),
                               record_ids=audit.json_cell([r["record_id"] for r, _ in linked]),
                               title=row["title"] if row else "", category=row["category"] if row else "",
                               description=row["description"] if row else "",
                               structural_method="; ".join(method for _, method in linked),
                               structural_status=row["image_status"] if row else "unlinked",
                               sha256=hashlib.sha256(data).hexdigest(),
                               review_status="reviewed" if note else "not yet reviewed",
                               observed_type=note.get("observed_type", ""),
                               verdict=note.get("verdict", ""), evidence=note.get("evidence", ""),
                               action=note.get("action", "")))
            with Image.open(io.BytesIO(data)) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB")
                w, h = image.size
                preview = image.copy()
                preview.thumbnail((620, 550), Image.Resampling.LANCZOS)
                thumbnail = io.BytesIO()
                preview.save(thumbnail, format="JPEG", quality=93)
                grey = image.convert("L")
                center = grey.crop((w // 10, h // 10, w - w // 10, h - h // 10))

                def dhash(picture):
                    pixels = picture.resize((9, 8), Image.Resampling.LANCZOS).tobytes()
                    return sum((pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
                               for y in range(8) for x in range(8))

                signature = (dhash(grey), dhash(center), tuple(image.resize((1, 1)).getpixel((0, 0))))
            objects[image_id] = (thumbnail.getvalue(), signature)
    require(set(annotations) <= {(r["image_id"],) for r in photos}, "Unknown image ID in visual judgments.")
    lookup = {r["image_id"]: r for r in photos}
    pairs = defaultdict(set)
    for a, b in combinations(photos, 2):
        first, second = a["image_id"], b["image_id"]
        if a["sha256"] == b["sha256"]:
            pairs[first, second].add("exact bytes")
            continue
        fa, ca, ra = objects[first][1]
        fb, cb, rb = objects[second][1]
        full = (fa ^ fb).bit_count()
        center = (ca ^ cb).bit_count()
        gray_color_difference = sum(abs(x - y) for x, y in zip(ra, rb))
        if gray_color_difference <= 60 and (
            (full <= 4 and center <= 9) or ((fa ^ cb).bit_count() <= 3 or (ca ^ fb).bit_count() <= 3)
        ):
            pairs[first, second].add("dataset-wide dHash candidate")
    for records_pair in candidate_pairs:
        for first in ids_by_record[records_pair[0]]:
            for second in ids_by_record[records_pair[1]]:
                pairs[tuple(sorted((first, second)))].add("Phase 2 candidate record pair")
    for group in ids_by_record.values():
        for pair in combinations(sorted(group), 2):
            pairs[pair].add("multiple photos for one item")
    for pair in pair_notes:
        require(len(set(pair)) == 2 and tuple(sorted(pair)) == pair and set(pair) <= lookup.keys(),
                "Invalid image IDs in a manually proposed duplicate pair.")
        if pair not in pairs:
            pairs[pair].add("visual review candidate")
    require(set(pair_notes) <= pairs.keys(), "Unknown duplicate pair in review judgments.")
    result = []
    by_record = {r["record_id"]: r for r in records}
    for number, ((first, second), reasons) in enumerate(sorted(
        pairs.items(), key=lambda pair: ("Phase 2 candidate record pair" not in pair[1],
                                        "exact bytes" not in pair[1], pair[0])
    ), 1):
        note = pair_notes.get((first, second), {})
        first_rows, second_rows = ([by_record[key] for key in json.loads(lookup[image]["record_ids"])]
                                   for image in (first, second))
        comparisons = [[{field: row[field] for field in ("title", "description", "price_raw", "currency_raw",
                                                         "age_raw", "condition_raw", "category")}
                        for row in group] for group in (first_rows, second_rows)]
        first_keys, second_keys = ({quality.recorded_listing(row)[0] for row in group
                                    if quality.recorded_listing(row)[0]} for group in (first_rows, second_rows))
        result.append(dict(pair=f"P{number:03d}", first=first, second=second,
                           record_ids_first=lookup[first]["record_ids"], record_ids_second=lookup[second]["record_ids"],
                           item_context=audit.json_cell(comparisons),
                           listing_evidence=("same saved listing address" if first_keys & second_keys else
                                             "different saved addresses" if first_keys and second_keys else
                                             "no pair of saved listing addresses"),
                           evidence_basis=audit.json_cell(sorted(reasons)),
                           review_status="reviewed" if note else "not yet reviewed",
                           visual_finding=note.get("visual_finding", ""),
                           evidence=note.get("evidence", ""),
                           proposed_action=note.get("action", "Retain pending sufficient identity evidence")))
    for photo in photos:
        note = annotations.get((photo["image_id"],), {})
        photo["suggested_category"] = note.get("suggested_category", "")
        photo["proposed_replacement_image"] = note.get("proposed_record_image", "")
        if target := photo["proposed_replacement_image"]:
            require(target in lookup and target != photo["image_id"], "Invalid proposed visual reassignment.")
        photo["proposed_record_id"] = ""
        if photo["verdict"] == "unlinked image" and photo["observed_type"] == "wooden bread box":
            # The source photo and the unmatched record are in the same submission.
            attachment = json.loads(photo["locator"])[0]
            matches = [r["record_id"] for r in records if r["image_status"] == "missing"
                       and quality.text_key(r["title"]) == "wooden bread box"
                       and json.loads(r["source_table"])[0] == attachment]
            if len(matches) == 1:
                photo["proposed_record_id"] = matches[0]
    if gallery:
        contact = private / "ContactSheets"
        contact.mkdir(exist_ok=True)
        for first in range(0, len(photos), 24):
            cards = [(r["image_id"], f"{r['title']} · {r['category']}", objects[r["image_id"]][0])
                     for r in photos[first:first + 24]]
            sheet(contact / f"images_{first + 1:04d}.jpg", cards, 6, (250, 239))
        for first in range(0, len(result), 5):
            cards = []
            for pair in result[first:first + 5]:
                for direction in ("first", "second"):
                    item = lookup[pair[direction]]
                    cards.append((f"{pair['pair']} · {item['image_id']}", item["title"], objects[item["image_id"]][0]))
            sheet(contact / f"pairs_{first + 1:03d}.jpg", cards, 2, (388, 255))
        review_labels = quality.category_mapping(records)
        _, context_candidates = quality.category_assessment(records, review_labels, [])
        context_ids = {r["record_id"] for rows in context_candidates.values() for r in rows}
        focused = [photo for photo in photos if photo["structural_status"] == "unlinked"
                   or (photo["category"] in review_labels and
                       review_labels[photo["category"]]["status"] == "review")
                   or context_ids.intersection(json.loads(photo["record_ids"]))
                   or any(len(ids_by_record[key]) > 1 for key in json.loads(photo["record_ids"]))]
        for first in range(0, len(focused), 16):
            cards = [(p["image_id"], f"{p['title']} · {p['category']}", objects[p["image_id"]][0])
                     for p in focused[first:first + 16]]
            sheet(contact / f"context_{first + 1:03d}.jpg", cards, 4, (304, 235))
    return photos, result


def outlier_packet(records, before, after, info, year, images):
    index = {row["record_id"]: row for row in records}
    photos = defaultdict(list)
    for photo in images:
        for key in json.loads(photo["record_ids"]):
            photos[key].append(photo)
    results = []
    for attribute, key in sorted(before.keys() | after.keys()):
        r = index[key]
        references = photos[key]
        evidence = after.get((attribute, key), before.get((attribute, key)))
        value = evidence[0][2]
        context = quality.outlier_context(attribute, r, value, info[key]["family"], year)
        supportive = "supports a plausible" in context
        title_years = set(map(int, re.findall(r"\b(?:18|19|20)\d{2}\b", r["title"])))
        dated_edition = (attribute == "age_raw" and info[key]["family"] == "Books"
                         and len(title_years) == 1
                         and re.search(r"\b(?:edition|published)\b", r["description"], re.I))
        if dated_edition:
            edition_year = next(iter(title_years))
            if edition_year <= year and abs((year - edition_year) - value) > 8:
                context = (f"Title identifies a {edition_year} edition, about {year - edition_year} years "
                           f"before the export year. The annotated age is {value:g}. The copy could be a reprint.")
        if any(photo["verdict"] == "visually inconsistent" for photo in references):
            verdict = "unresolved item image mismatch"
        elif context.startswith("Title identifies"):
            verdict = "dated edition conflicts with age"
        elif supportive:
            verdict = "plausible from source text"
        else:
            verdict = "unresolved"
        results.append(dict(record_id=key, attribute=attribute, original_value=r[attribute], diagnostic_value=value,
                            unit=info[key]["currency"] if attribute == "price_raw" else "years",
                            title=r["title"], description=r["description"], category=r["category"],
                            previous_scopes=audit.json_cell(before.get((attribute, key), [])),
                            revised_scopes=audit.json_cell(after.get((attribute, key), [])),
                            image_ids=audit.json_cell([photo["image_id"] for photo in references]),
                            image_verdicts=audit.json_cell([photo["verdict"] for photo in references if photo["verdict"]]),
                            verdict=verdict, evidence=context, review_status="source-context rule",
                            proposed_treatment="Retain the value pending stronger evidence"))
    return results


def proposal(verified, outlier_rows):
    records, missing = verified["records"], verified["missing"]
    size = len(records)
    gaps = {name: sum(items.values()) for name, (items, _) in missing.items()}
    problems = verified["problems"]
    duplicates = verified["duplicates"]
    revised = verified["revised"]
    categories = verified["categories"]
    issues = Counter((r["attribute"], r["verdict"]) for r in outlier_rows if r["revised_scopes"] != "[]")
    image_status = Counter(photo["verdict"] for photo in verified["images"] if photo["verdict"])
    counts_changed = Counter(row["record_id"] for row in records
                             if categories[row["category"]]["status"] == "proposed"
                             and row["category"] != categories[row["category"]]["proposed_category"])
    result = []

    def add(label, n, evidence, options, treatment, rationale, effect, analysis, reference, uncertainty, approval="Phase 3 approval"):
        result.append((label, f"{n:,} ({100*n/size:.2f}%)", evidence, options, treatment, rationale, effect,
                       analysis, reference, uncertainty, approval))

    def gap(attribute, label, evidence, treatment, analysis, options="Drop row, recover from source, or use available cases"):
        add(label, gaps[attribute], evidence, options, treatment,
            "Unrelated fields remain usable. A substitute needs evidence.", "Preserve all rows", analysis,
            "Slides 20–22; A2 §3", "The missingness mechanism is unknown.")

    gap("age_raw", "Missing age", "Blank cells and Unknown variants cluster by submission.",
        "Use observed valid ages per analysis and report n. Recover only directly supported values.",
        "Avoid artificial age spikes and attenuation. Check sensitivity by submission.",
        "Complete cases, mean/median, group median, prediction, available cases")
    gap("price_raw", "Missing price", "Blank, whitespace and explicit unknown occur.",
        "Keep missing and use known amounts for pricing analyses.", "Report price-specific sample sizes.",
        "Drop row, recover from listings, median, available cases")
    gap("currency_raw", "Missing currency", "One table omits the field. Assignment 1 establishes no default.",
        "Keep the code and converted price missing unless the row has reliable evidence.", "Exclude from converted comparisons.")
    gap("condition_raw", "Missing condition", "Blanks and Unknown occur.",
        "Keep missing. Do not infer a rating from appearance.", "Use observed ordinal scores and report n.",
        "Mode, subjective visual rating, available cases")
    gap("category", "Missing category", "One category was originally blank.",
        "Review item context and use Unknown for reporting if it remains unresolved.", "Keep Unknown distinct from product categories.")
    gap("description", "Missing description", "Blank and explicit placeholders occur.",
        "Leave text unavailable. Preserve title and other attributes.", "Restrict text comparisons to usable descriptions.")
    gap("image_links", "Missing image association", "One raw item has no associated file.",
        "Retain the item and leave image evidence unavailable.", "Tabular analysis can include this observation.")
    add("Ambiguous currency", len(problems.get(("currency_raw", "ambiguous_label"), [])),
        "A bare dollar label does not identify a currency. Source text supplied no explicit code.",
        "Guess USD, use a submission default, or leave unresolved", "Require item-specific currency evidence.",
        "Dollar labels and mixed submission currencies make a default unreliable.", "Keep original amounts and labels.",
        "Unresolved rows do not receive an ILS value.", "Slide 26; A1 §4", "Documented market or listing evidence may help.")
    add("Invalid condition", len(problems.get(("condition_raw", "outside_scale"), [])),
        "A recorded score of 9 exceeds the 1–5 scale.", "Clamp, infer, drop, or keep analytical value missing",
        "Recover only with direct evidence. Otherwise leave the analytical rating missing.", "Clamping invents a rank.",
        "Retain the raw score and flag.", "Exclude from ordinal summaries only.", "A1 §5; A2 §3", "Intended score is unknown.")
    add("Condition label representations", sum(v["condition_kind"] in {"assignment_label", "number_and_label", "integer_format"}
                                                for v in revised.values()),
        "Published rubric defines scores for all five named levels.", "Keep mixed text, or use official ordinal codes",
        "Apply the rubric to exact labels and matching pairs.", "The assignment explicitly supplies the codebook.",
        "Populate a separate ordinal field.", "Comparable condition counts and plots.", "A1 §5", "Scores remain subjective.")
    add("Verified duplicate observations", quality.count_rows(duplicates["exact"]),
        "No exact seven-field duplicates were detected. Photo reuse alone does not establish listing identity.",
        "Retain, select a representative, or combine complementary fields", "Only deduplicate on verified same-observation evidence.",
        "Separate products or listings must remain separate.", "Current evidence does not support deletion.",
        "Potential review pairs remain available.", "Slide 26; A2 §3", "Listing identity is unresolved.")
    add("Unresolved duplicate candidates", len({key for row in verified["pairs"] if "multiple photos for one item" not in row["evidence_basis"]
                                                for column in ("record_ids_first", "record_ids_second")
                                                for key in json.loads(row[column])}),
        "Exact photographs, compatible item attributes, or perceptual similarity.", "Retain, merge, or pick a representative",
        "Retain until source listing or capture identity is established.", "Similarity may reflect reused or stock images.",
        "Track pair verdicts without deleting observations.", "Avoid false duplicate removals.", "Slide 26; A2 §3",
        "Visual and listing evidence is incomplete.")
    add("Category spelling and aliases", len(counts_changed), "Explicit map retains specific product types.",
        "Keep raw labels, force a fixed taxonomy, or use two levels", "Use conservative specific labels and a separate broader group.",
        "Broader cohorts gain sample size while specific meanings remain visible.", "Keep raw, specific and group fields.",
        "Use broader groups for sparse comparisons and specific labels for context.", "Slides 26–27; A1 §3",
        "Broad and conflicting assignments still need review.")
    add("Price formatting", sum(v["price_kind"] == "supported_grouping" for v in revised.values()),
        "Six exact forms approved by the user. Other grouping has direct formatting evidence.",
        "Strip all commas, reject all commas, or parse evidenced forms", "Parse only documented grouping.",
        "Identical comma punctuation can have different locale meanings.", "Retain raw text and add a parsed amount.",
        "Restores valid prices to compatible analyses.", "Slides 20, 26", "None for the six approved forms.", "Interpretation approved")
    add("Age-unit inconsistencies", sum(v["age_kind"] in {"months", "years_text"} for v in revised.values()),
        "Explicit month/year text, course years default, and approved 3 moths typo.",
        "Leave mixed units, infer unsupported units, or record evidence-based years", "Use stated units and Assignment 1 default.",
        "Makes ages comparable while retaining source meaning.", "Add age in years and unit evidence.",
        "Preserves fractional ages.", "A1 §§2, 4; slide 26", "Estimated ages still have measurement error.", "Typo approved")
    for attribute, label in (("price_raw", "price"), ("age_raw", "age")):
        plausible = issues[attribute, "plausible from source text"]
        uncertain = sum(n for (field, _), n in issues.items() if field == attribute) - plausible
        for count, prefix in ((plausible, "Plausible genuine"), (uncertain, "Suspicious or unresolved")):
            add(f"{prefix} {label} outliers", count,
                "IQR and context from original titles, descriptions, units and category.",
                "Retain, correct proven errors, clip, bin, smooth, cluster, or delete",
                "Retain pending corroboration. Use medians, IQR and sensitivity summaries.",
                "Long tails are expected. Range-based edits distort real market variation.",
                "Store quality flags separately.", "Show robust and conventional summaries with n.",
                "Slides 23–24, 41, 44, 46, 69–70", "Individual value and provenance review is pending where flagged.")
    add("Malformed title or description", verified["source_stats"]["unquoted_prose_boundary"],
        "The raw file preserves exact fragments and verified trailing fields.", "Invent a boundary, drop, or recover from source",
        "Condition text-only use on provenance. Retain all recoverable item fields.",
        "The original text boundary cannot be verified from unlabeled fragments.", "Keep fragments and a text-quality flag.",
        "Numerical analysis can still use the verified suffix.", "Slides 20, 26", "Original prose boundaries unresolved.")
    add("Visually inconsistent association", image_status["visually inconsistent"], "Recorded visual judgments only.",
        "Relink, detach, or retain the raw association with a flag", "Require item-specific evidence before relinking.",
        "A plausible replacement must be supported independently.", "Preserve raw links and add review status.",
        "Exclude unresolved links from image-dependent analysis.", "A1 §7; A2 §2", "Counts are limited to completed visual review.")
    add("Currency conversion reference", verified["price_n"], "Resolved currency and usable raw price, including a documented zero.",
        "Use within-currency comparisons or one fixed ILS conversion snapshot", "Store original and ILS amounts separately.",
        "A dated published snapshot enables comparisons and repeatability.", "Multiply Decimal values by ILS per unit.",
        "Conversion represents retrieval-date equivalents and is not a historical valuation.", "Slide 26; A1 §4",
        "The reference rates may be older than the retrieval date.", "Conversion approved")
    add("Original item ID missing or reused", len({r["record_id"] for values in duplicates["shared_ids"].values() for r in values}
                                                  | {r["record_id"] for r in records if not r["original_item_id"].strip()}),
        "Generated IDs are deterministic; original values may be local labels or absent.",
        "Invent IDs, force raw uniqueness, or retain a separate unique key", "Use record_id and preserve original identifiers.",
        "The original ID alone cannot establish item identity.", "No raw field is overwritten.",
        "Joins use the generated key.", "A2 §§2–3", "Some marketplace listing identities remain unknown.")
    return result


def write_reports(root, checked, outlier_rows):
    n = len(checked["records"])
    j = Counter(r["verdict"] for r in checked["images"] if r["review_status"] == "reviewed")
    duplicate_coverage = Counter(r["review_status"] for r in checked["pairs"])
    duplicate_findings = Counter(r["visual_finding"] for r in checked["pairs"] if r["visual_finding"])
    confirmed_mismatches = sum(p["verdict"] == "visually inconsistent" and p["structural_status"] == "confirmed"
                               for p in checked["images"])
    assignments = {key for p in checked["images"] if p["suggested_category"] for key in json.loads(p["record_ids"])}
    dated_editions = [row for row in outlier_rows if row["verdict"] == "dated edition conflicts with age"]
    full = sum(j.values()) == len(checked["images"]) and not duplicate_coverage["not yet reviewed"]
    unrelated = sum(r["structural_status"] == "unlinked" for r in checked["images"])
    dates_by_currency = Counter(row["rate_date"] for row in checked["fx_reference"] if row["currency_code"] != "ILS")
    old = Counter(k[0] for k in checked["outliers"])
    new = Counter(k[0] for k in checked["revised_outliers"])
    findings = [
        "# Pre-cleaning checkpoint", "", "## Baseline and source verification", "",
        f"- Reconciled {checked['counts'][0]} original attachments, {checked['counts'][2]} versions and "
        f"{checked['counts'][1]} student groups. The export's dated attachment records and numbered sequence "
        "corroborate selection order. The source system's submission timestamps remain unavailable.",
        f"- Verified {n:,} rows against the selected source tables with separate CSV and workbook reads. "
        "The integrated records retain source IDs, fields, currency and age header evidence, hyperlinks and "
        "structural exceptions. The approved workbook remains authoritative and the extra item row remains present.",
        f"- Inspected {len(checked['excluded'])} nonempty omitted source rows. They contain student-identification "
        "notes or metadata without marketplace item fields. Blank rows and actual headers were counted separately.",
        f"- Original attachment bytes and the raw baseline passed before and after verification. "
        f"Raw SHA-256 is `{checked['digest']}`.",
        "", "## Quantitative verification and revised interpretation", "",
        f"- Reconciled all {len(integration.COLUMNS)} missingness counts and rates, category frequencies and "
        "the Phase 2 price, currency, age and condition frequency table. No baseline repair was required.",
        f"- Independently recomputed the original {len(checked['scopes'])} IQR scopes and "
        f"{len(checked['revised_scopes'])} scopes after the approved interpretations. Checked quartiles, mean, "
        "median, sample SD, Pearson skewness and each tail count. Outliers are assessed within original currency or in years.",
        f"- Phase 2 reported {old['price_raw']} price and {old['age_raw']} age candidates. The approved exact "
        f"comma forms and age typo yield {new['price_raw']} and {new['age_raw']} candidates. The outlier inventory "
        "retains both results, source text and the filing status of photo evidence.",
        "- The original charts use paid-price cohorts in ILS and USD plus ages in years. Boxplot fences are "
        "calculated on original values. The log-spaced display exposes long tails and the age display accommodates zero.",
        "", "## Actual visual coverage", "",
        f"- Accounted for {len(checked['images']):,} file locators and "
        f"{len({r['sha256'] for r in checked['images']}):,} distinct byte hashes. "
        f"{sum(j.values()):,} files have logged visual judgments. "
        f"{len(checked['images']) - sum(j.values()):,} files remain unreviewed. "
        f"{unrelated} file(s) have no established structural association.",
        "- Recorded visual verdicts are " + quality.display_counts(j) + ".",
        f"- {confirmed_mismatches} original file-reference confirmations have a visual mismatch. "
        "The initial check matched written names correctly. Visual review now separates those source-reference "
        "errors from mapping code. Proposed same-submission replacements and product-category suggestions are local.",
        f"- Product context supports {len(assignments)} proposed category changes. Keep specific cleaned categories "
        "and a separate broad group. The visual map keeps the raw values and marks all proposals for approval.",
        "- The previously unlinked file visibly shows a wooden box labeled Bread. A matching record from the same "
        "submission has the only unresolved image association. This now supports a plausible link. The source lacks "
        "an exact filename match or unique identifier, so approval is pending.",
        f"- Compared files using full-frame and central-crop difference hashes with a mean-color gate. "
        f"The candidate list has {len(checked['pairs'])} image pairs including earlier duplicate candidates and "
        "the multiple-photo item. Near hashes identify candidates and can miss more aggressive crops or alternate viewpoints.",
        f"- Actually inspected {duplicate_coverage['reviewed']} pairs side by side. "
        f"{duplicate_coverage['not yet reviewed']} pairs remain. Recorded findings are "
        + quality.display_counts(duplicate_findings) + ". A reused photograph alone cannot establish listing identity.",
        f"- The outlier inventory supplies source-context evidence for {len(outlier_rows)} record/attribute cases. "
        "Rules flag historical and high-value asset context. Individual semantic decisions that lack direct evidence "
        "remain provisional. No item is removed on the basis of IQR, visual resemblance, or image availability.",
        f"- {len(dated_editions)} flagged book age(s) disagree materially with the stated edition year. "
        "Reprints or an estimate referring to time owned could explain the gap. Keep the original age and seek "
        "copy-specific evidence before replacing it.",
        "", "## Fixed ILS conversion snapshot", "",
        f"- Covers {len(checked['fx_reference'])} resolved codes, including the ILS identity rate. "
        f"Checked source publications on {SNAPSHOT_DATE} local time. "
        f"Published nonidentity rates by date are {quality.display_counts(dates_by_currency)}.",
        "- Prefer direct Bank of Israel reference rates. Cross ECB quotes through EUR, UAE quotes through AED or "
        "USD, and the Libya and Taiwan quotes through USD. Each rate records its direction, operands, date, and source. "
        "This is a fixed contemporary equivalent, with no claim about historical item collection values or executable trades.",
        f"- {checked['price_n']:,} rows have sufficient price and currency evidence for a future ILS value. "
        f"{checked['unresolved_currency']} rows have unresolved currency identity. Price, title and description "
        f"contain {checked['currency_clues']} explicit currency cues among those rows. A blank or generic dollar "
        "label stays unresolved without independent evidence. The course gives no default currency.",
        "", "## Treatment sensitivity", "",
        f"- The proposed numerical interpretations yield {checked['age_n']:,} usable ages. "
        f"Complete-case retention across key item fields would leave {checked['complete_n']:,} of {n:,} rows. "
        "Available-case denominators preserve other usable observations. Missing ages cluster, and the mechanism is unknown.",
        "", "| Age treatment in records with a usable ILS amount | n | Age sample SD | Pearson age/price r |",
        "|---|---:|---:|---:|",
    ]
    for label, size, sd, correlation in checked["sensitivity"]:
        findings.append(f"| {label} | {size:,} | {sd:.3f} | {correlation:.4f} |")
    findings += [
        "", "The in-memory comparison quantifies how filling available-price rows with one age value changes variance "
        "and correlation. It does not establish the true relationship for missing ages. Removing all incomplete rows "
        "can select against affected submissions. Removing age loses a required analysis. Group imputations preserve "
        "some between-group differences but still suppress within-group variation. Predictive filling would require "
        "defensible missingness assumptions and validation. Use per-analysis availability and record denominators.",
        "", "The preferred strategy uses separate raw and analytical fields, conservative category aliases and broader "
        "groups, a dated ILS field, year-valued ages, Assignment 1 ordinal codes, and separate quality flags. "
        "Choose medians, IQRs and explicit sensitivity summaries for long tails. Binning, regression smoothing, clustering, "
        "clipping, normalization, and one-hot encoding serve no required cleaning purpose here. An optional grouping for "
        "display can remain separate from the continuous analysis.",
        "", "Relevant lecture slides are 18–22 for completeness and missing treatment, 23–24 for noise and smoothing, "
        "26 for data value conflicts and redundancy, 27–34 for transformations, 38–46 for descriptive statistics "
        "and skewness, and 68–71 for histograms, boxplots and IQR. Assignment 1 §§2, 4, 5 and 7 define units, codes "
        "and linkage expectations. Assignment 2 §§2–4 define the integration, quality and EDA requirements.",
        "", "## Readiness", "",
        "**The required visual checkpoint is incomplete. Phase 3 remains blocked.**" if not full else
        "**The visual review ledger is complete. Phase 3 still requires explicit approval.**",
        "The decision table records proposals and approval status. The remaining visual, category-context and "
        "outlier cases require individual review or an explicit decision to proceed with their uncertainty.",
        "",
    ]
    table = ["# Proposed Phase 3 cleaning decisions", "",
             "Percentages use all integrated records. Counts can overlap. A proposed treatment does not modify the raw baseline.",
             "", "| Issue | Affected | Evidence | Alternatives | Recommended treatment | Reason | Dataset effect | Analysis effect | Reference | Uncertainty | Approval |",
             "|---|---:|---|---|---|---|---|---|---|---|---|"]
    table += ["| " + " | ".join(quality.markdown(value) for value in decision) + " |"
              for decision in proposal(checked, outlier_rows)]
    for name, lines in (("pre_cleaning_review.md", findings), ("pre_cleaning_decisions.md", table)):
        integration.write_output(root / "Audit" / name, "\n".join(lines).encode("utf-8"))


def run(root, gallery=False):
    root = root.resolve()
    raw, digest, frame, manifest, selected = quality.load_baseline(root)
    original = integration.verify_originals(root, manifest)
    counts = independent_inventory(root, manifest, selected)
    records = frame.to_dict("records")
    source_stats, excluded = independent_sources(root, records, selected)
    source_review = integration.validate_source_records(root, records, selected)
    categories = quality.category_mapping(records)
    old_categories, _ = integration.read_csv(root / "Audit" / "phase2_category_mapping.csv")
    require({r["raw_category"]: int(r["records"]) for r in old_categories}
            == {name: value["records"] for name, value in categories.items()}, "Category counts differ.")
    inventory = []
    missing, _, _ = quality.missing_assessment(records, selected, inventory)
    prior_report = (root / "Audit" / "phase2_summary.md").read_text(encoding="utf-8")
    for column in frame:
        raw_values = Counter(frame[column])
        independent = sum(n for value, n in raw_values.items() if quality.missing_kind(column, value))
        require(independent == sum(missing[column][0].values()), "Independent missing counts differ.")
        line, = [line.split("|") for line in prior_report.splitlines() if line.startswith(f"| `{column}` |")]
        require(int(line[8].replace(",", "")) == independent and
                line[9].strip() == f"{100 * independent / len(records):.2f}%", "Reported missing percentages differ.")
    info, frequencies, problems = quality.value_assessment(records, selected, categories, inventory)
    old_frequencies, _ = integration.read_csv(root / "Audit" / "phase2_value_frequencies.csv")
    require({(r["attribute"], r["raw_label_or_form"], r["diagnostic_interpretation"], r["status"]): int(r["records"])
             for r in old_frequencies} == frequencies, "Prior value-frequency analysis differs.")
    duplicates = quality.duplicate_records(records, info, inventory)
    unresolved_currency = [row for row in records if not info[row["record_id"]]["currency"]]
    currency_clues = sum(bool(re.search(
        r"\b(?:USD|CAD|AUD|ILS|NIS|EUR|GBP|(?:US|Canadian|Australian) dollars?|shekels?)\b|[₪$€£]",
        " ".join(row[field] for field in ("title", "description", "price_raw")), re.I
    )) for row in unresolved_currency)
    prior_issues, _ = integration.read_csv(root / "Audit" / "phase2_issues.csv")
    year = quality.structural_assessment(records, selected, [])["reference_year"]
    scopes, outliers, prices, ages, *_ = quality.outlier_assessment(records, info, problems, [], year)
    compare_scopes(scopes, prices, ages, info)
    previous = {(i["attribute"], json.loads(i["record_ids"])[0]) for i in prior_issues
                if i["issue_type"] == "iqr_outlier_candidate"}
    require(previous == outliers.keys(), "Previously reported IQR candidates differ.")
    fx_reference = rates({value["currency"] for value in info.values() if value["currency"]})
    fx = {r["currency_code"]: Decimal(r["ils_per_unit"]) for r in fx_reference}
    revised, price_n, age_n, complete_n, sensitivity = approved_diagnostics(records, info, fx)
    revised_scopes, revised_outliers, prices, ages, *_ = quality.outlier_assessment(records, revised, problems, [], year)
    compare_scopes(revised_scopes, prices, ages, revised)
    images, pairs = visual_packets(root, records, selected, duplicates["candidates"], gallery)
    require(len(images) == sum(int(row["image_files"]) for row in selected), "Missing selected image inventory.")
    original_photo_groups = Counter(photo["sha256"] for photo in images)
    seen_pairs = {frozenset(json.loads(pair["record_ids_first"]) + json.loads(pair["record_ids_second"]))
                  for pair in pairs if "Phase 2 candidate record pair" in pair["evidence_basis"]}
    require(all(frozenset(pair) in seen_pairs for pair in duplicates["candidates"]),
            "The duplicate image queue omitted a Phase 2 item pair.")
    require(sum(n > 1 for n in original_photo_groups.values()) ==
            sum(i["issue_type"] == "byte_identical_images" for i in prior_issues),
            "Selected exact-image group count differs from Phase 2.")
    require(audit.digest_file(raw).hex() == digest and integration.verify_originals(root, manifest) == original,
            "Original data changed during verification.")
    outlier_rows = outlier_packet(records, outliers, revised_outliers, revised, year, images)
    for name, rows in (("pre_cleaning_visual_review.csv", images), ("pre_cleaning_duplicate_review.csv", pairs),
                       ("pre_cleaning_exchange_rates.csv", fx_reference), ("pre_cleaning_outlier_review.csv", outlier_rows)):
        integration.write_output(root / "Audit" / name, quality.csv_output(rows, list(rows[0])))
    result = dict(counts=counts, source_stats=source_stats, source_review=source_review, excluded=excluded,
                  records=records, missing=missing, problems=problems, digest=digest, categories=categories,
                  duplicates=duplicates, scopes=scopes, outliers=outliers, revised_scopes=revised_scopes,
                  revised_outliers=revised_outliers, revised=revised, price_n=price_n, age_n=age_n,
                  complete_n=complete_n, sensitivity=sensitivity, images=images, pairs=pairs,
                  fx_reference=fx_reference, unresolved_currency=len(unresolved_currency), currency_clues=currency_clues)
    write_reports(root, result, outlier_rows)
    require(audit.digest_file(raw).hex() == digest, "The raw file changed before verification completed.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--contact-sheets", action="store_true", help="Render private contact sheets for local review")
    args = parser.parse_args()
    result = run(args.root, args.contact_sheets)
    print("Attachments, students, versions", result["counts"])
    print("Source checks", dict(result["source_stats"]), "non-item rows", len(result["excluded"]))
    print("Images and candidate pairs", len(result["images"]), len(result["pairs"]))
    print("Updated price, age and complete-case coverage",
          result["price_n"], result["age_n"], result["complete_n"])


if __name__ == "__main__":
    main()

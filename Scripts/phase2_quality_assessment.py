"""Assess the immutable marketplace CSV. All parsed values are diagnostic only."""

import argparse
import hashlib
import io
import json
import math
import re
import subprocess
import tarfile
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urlsplit

import pandas as pd
from PIL import Image, ImageOps

import phase0_audit as audit
import phase1_integration as integration


ANALYTICAL = ("title", "description", "category", "age_raw", "condition_raw", "price_raw", "currency_raw")
SOURCE_FIELDS = integration.SOURCE_COLUMNS
PLACEHOLDERS = {"unknown", "unkown", "n/a", "n.a.", "na", "none", "null", "not available",
                "not applicable", "unspecified", "-", "—", "?"}
OPTIONAL = {"source_sheet", "age_header_unit", "listing_link_raw", "image_flags", "source_extras"}
JSON_EMPTY = {"image_links": "[]", "image_flags": "[]", "source_extras": "{}"}
CONDITIONS = {"very poor": 1, "poor": 2, "fair": 3, "good": 4, "like new": 5}
CODES = set("AED AUD CAD CHF EGP EUR GBP ILS INR IQD JOD LYD SAR SEK SGD TWD USD".split())
CURRENCY_ALIASES = {"NIS": "ILS", "SHEKEL": "ILS", "₪": "ILS"}
PRICE_TOKEN = re.compile(r"(?<!\w)(?:US\s*\$|USD|ILS|NIS|EUR|GBP|AED)(?!\w)|[₪€£$]", re.I)
FREE_OFFER = re.compile(r"\b(?:offered free|free to (?:collect|a good home)|given away free)\b", re.I)
AGE_PATTERN = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(years?|months?|moths)", re.I)
AGE_MENTION = re.compile(r"\b(?:used for|owned for|item (?:is|age[: ]+)|bought|purchased)\s*"
                         r"(\d+(?:\.\d+)?)\s*(years?|months?)\b", re.I)
NONFINITE = re.compile(r"[+-]?(?:nan|inf(?:inity)?|∞)", re.I)
MIN_CURRENCY_N = 10
MIN_CATEGORY_N = 25
ISSUE_COLUMNS = ("reference", "record_ids", "attribute", "original_value", "issue_type",
                 "evidence", "confidence", "recommended_treatment")

# Assignment 1 sections 2, 4 and 5 define years, currency collection, and this
# condition scale. Suggested category names are examples, not a closed list.
CATEGORY_ALIASES = {
    "Books": ("book", "books"),
    "Clothing": ("clothes", "clothing"),
    "Clothing and accessories": ("clothing and accessories",),
    "Bags and accessories": ("bags and accessories",),
    "Home decor": ("home decor",),
    "Cars": ("car", "cars"),
    "Bicycles": ("bicycle",),
    "Mobile phones": ("mobile phones", "phones"),
    "Musical instruments": ("musical instrument", "musical instruments"),
    "Kitchen and household items": ("kitchen and household", "kitchen and household item",
                                   "kitchen and household items"),
    "Kitchen items": ("kitchen", "kitchen items"),
    "Sports equipment": ("sports equipment", "sports equipments"),
    "Toys and games": ("toys and games", "games and toys"),
    "Other used products": ("other", "other used products"),
}
FAMILIES = {
    "Electronics": ("Electronics", "Electronics and Tech", "Electronics and Accessories",
                    "Computer Monitors", "Keyboards", "Laptops", "Cameras & Photography", "Camera",
                    "Mobile phones", "Phone Accessories", "Mobile & Tablet Accessories", "Smartphone",
                    "Smartwatch", "Video Game Console"),
    "Books": ("Books", "Science Textbooks"),
    "Clothing and accessories": ("Clothing and accessories", "Clothing", "Clothing & Footwear", "Footwear",
                                "Shoes", "Watches & Jewelry", "Bags", "Bags and accessories",
                                "Wallets & Small Leather Goods"),
    "Furniture": ("Furniture", "Dining Tables and Chair Sets", "Wardrobes and Storage Cabinets"),
    "Kitchen and household items": ("Kitchen and household items", "Kitchen items", "Household & Everyday Items",
                                   "Household Appliances", "Gas Cookers and Ovens", "Microwave Ovens",
                                   "Refrigerators"),
    "Sports equipment": ("Sports equipment", "Fitness Equipment"),
    "Cycling": ("Bicycles", "Electric Bicycles"),
    "Vehicles": ("Vehicles", "Cars", "motorcycles"),
    "Musical instruments": ("Musical instruments", "Acoustic Guitars"),
    "Tools": ("Tools", "Cordless Drills"),
    "Toys and games": ("Toys and games", "Toys", "Chess", "Video Game"),
    "Stationery and office supplies": ("Stationery and Office Supplies", "Office and school supplies", "Stationery"),
    "Personal care": ("Personal Care", "Beauty and personal care", "Health & Personal Care"),
}
AMBIGUOUS_CATEGORIES = {"accessories", "art and decor", "decor", "electronics and gaming", "furniture and home decor",
                        "games", "health", "office and household", "sports"}


def text_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def category_key(value):
    plain = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    return text_key(plain.replace("&", " and "))


def missing_kind(column, value):
    if not value:
        return "empty"
    if not value.strip():
        return "whitespace"
    if column in {*ANALYTICAL, "original_item_id", "image_reference_raw", "listing_link_raw"}:
        if text_key(value) in PLACEHOLDERS:
            return "placeholder"
        if column == "image_reference_raw" and value.strip().casefold().removeprefix(".") in audit.IMAGE_SUFFIX_LABELS:
            return "format_only"
    if value == JSON_EMPTY.get(column):
        return "empty_json"
    return ""


def issue(inventory, kind, attribute, rows, evidence, confidence, treatment, value=None, reference=None):
    ids = sorted({r["record_id"] for r in rows})
    if value is None and rows and attribute in rows[0]:
        values = Counter(r[attribute] for r in rows)
        value = next(iter(values)) if len(values) == 1 else audit.json_cell(dict(values))
    inventory.append(dict(zip(ISSUE_COLUMNS, (
        reference or f"q-{len(inventory) + 1:04d}", audit.json_cell(ids), attribute, value or "", kind,
        evidence, confidence, treatment,
    ))))


def load_baseline(root):
    raw = integration.local_path(root, "marketplace_raw.csv")
    digest = audit.digest_file(raw).hex()
    report = integration.local_path(root, "Audit/phase1_summary.md").read_text(encoding="utf-8")
    expected = re.search(r"SHA-256 for the unchanged CSV baseline is `([a-f0-9]{64})`", report)
    if not expected or digest != expected[1]:
        raise ValueError("The raw CSV does not match the approved Phase 1 SHA-256.")
    frame = pd.read_csv(raw, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8")
    if tuple(frame.columns) != integration.COLUMNS or not frame["record_id"].is_unique:
        raise ValueError("The raw CSV schema or generated record IDs failed validation.")
    manifest, selected, _ = integration.manifest_inputs(root)
    counts = Counter(zip(frame["student_id"], frame["submission_id"]))
    expected_counts = {(r["student_id"], r["submission_id"]): int(r["data_rows"]) for r in selected}
    if counts != expected_counts:
        raise ValueError("The raw rows do not match the selected submissions and counts.")
    return raw, digest, frame, manifest, selected


def category_mapping(records):
    counts = Counter(r["category"] for r in records)
    groups = defaultdict(list)
    for label in counts:
        groups[category_key(label)].append(label)
    manual = {alias: label for label, aliases in CATEGORY_ALIASES.items() for alias in aliases}
    families = {category_key(label): family for family, labels in FAMILIES.items() for label in labels}
    mapping = {}
    for value, count in sorted(counts.items(), key=lambda item: (category_key(item[0]), item[0])):
        key = category_key(value)
        label = manual.get(key) or min(groups[key], key=lambda v: (-counts[v], v != v.strip(), v)).strip()
        if not key or text_key(value) in PLACEHOLDERS:
            status, reason, label = "missing", "No category supplied", ""
        elif key in AMBIGUOUS_CATEGORIES or label == "Other used products":
            status, reason = "review", "Broad, overlapping, or catch-all label. Retain and review context"
        elif len(groups[key]) > 1 or key in manual:
            status, reason = "proposed", "Case, spacing, accent, punctuation, or equivalent label"
        else:
            status, reason = "retain", "Preserve category or more specific subcategory"
        family = families.get(category_key(label), label) if status in {"retain", "proposed"} else ""
        mapping[value] = {
            "raw_category": value, "records": count, "proposed_category": label,
            "diagnostic_family": family, "status": status, "reason": reason,
        }
    return mapping


def missing_assessment(records, selections, inventory):
    absent = {}
    for sub in selections:
        _, spec = integration.selected_table(sub)
        roles = {integration.field_role(header) for header in spec["columns"]}
        absent[sub["submission_id"]] = {field for role, field in SOURCE_FIELDS.items() if role not in roles}
    counts, groups_by_column, affected = {}, {}, defaultdict(set)
    for column in integration.COLUMNS:
        groups = defaultdict(list)
        for r in records:
            if kind := missing_kind(column, r[column]):
                groups[kind].append(r)
        found = [row for subset in groups.values() for row in subset]
        absent_count = sum(column in absent[r["submission_id"]] for r in found)
        counts[column] = (Counter({kind: len(subset) for kind, subset in groups.items()}), absent_count)
        groups_by_column[column] = found
        if found and column not in OPTIONAL and column != "image_links":
            for r in found:
                affected[r["record_id"]].add(column)
            issue(inventory, "missing_information", column, found,
                  f"Missing forms {audit.json_cell(dict(counts[column][0]))}. "
                  f"{absent_count} rows come from tables lacking this field.",
                  "observed",
                  "Keep the observation. Use available valid values for analyses requiring this field")
    return counts, groups_by_column, affected


def currency_value(raw):
    if missing_kind("currency_raw", raw):
        return "", "missing"
    form = raw.strip().upper()
    if code := CURRENCY_ALIASES.get(form, form if form in CODES else ""):
        return code, "recorded_code" if raw == code else "equivalent_label"
    return "", "ambiguous_label" if form in {"DOLLAR", "$", "DOLLARS"} else "unsupported_label"


def parse_price(raw, grouping_verified):
    if missing_kind("price_raw", raw):
        return None, "missing"
    value = raw.strip()
    if NONFINITE.fullmatch(value):
        return None, "nonfinite"
    if audit.NUMBER.fullmatch(value):
        number, form = Decimal(value), "plain"
    elif re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*|(?:,\d{3})+)", value) or (
        grouping_verified and re.fullmatch(r"[+-]?\d{1,3},\d{3}", value)
    ):
        number, form = Decimal(value.replace(",", "")), "supported_grouping"
    elif re.fullmatch(r"[+-]?\d{1,3},\d{3}", value):
        return None, "ambiguous_separator"
    elif PRICE_TOKEN.search(value):
        return None, "embedded_currency"
    else:
        return None, "unparseable"
    if number < 0:
        return number, "negative"
    return number, "zero_review" if number == 0 else form


def parse_age(record):
    raw = record["age_raw"]
    if missing_kind("age_raw", raw):
        return None, "missing", ""
    value = raw.strip()
    if NONFINITE.fullmatch(value):
        return None, "nonfinite", ""
    if audit.NUMBER.fullmatch(value):
        amount = Decimal(value)
        evidence = "header years" if record["age_header_unit"] == "years" else "assignment years"
        return amount, "negative" if amount < 0 else "numeric", evidence
    if match := AGE_PATTERN.fullmatch(value):
        amount = Decimal(match[1])
        unit = match[2].casefold()
        if unit == "moths":
            return None, "unit_typo_review", "literal unit: moths"
        if amount < 0:
            return amount, "negative", unit
        if unit.startswith("month"):
            return amount / 12, "months", "explicit months"
        return amount, "years_text", "explicit years"
    if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:[-–]|to)\s*\d+(?:\.\d+)?(?:\s+\w+)?", value, re.I):
        return None, "age_range_review", ""
    return None, "unparseable", ""


def parse_condition(raw):
    if missing_kind("condition_raw", raw):
        return None, "missing"
    value = text_key(raw)
    if value in CONDITIONS:
        return CONDITIONS[value], "assignment_label"
    if label := re.fullmatch(r"([+-]?\d+)\s*[-–—:]\s*(.+)", value):
        n = int(label[1])
        if not 1 <= n <= 5:
            return None, "outside_scale"
        return (n, "number_and_label") if CONDITIONS.get(label[2]) == n else (None, "label_conflict")
    if NONFINITE.fullmatch(value):
        return None, "nonfinite"
    if not audit.NUMBER.fullmatch(value):
        return None, "unparseable"
    n = Decimal(value)
    if n < 1 or n > 5:
        return None, "outside_scale"
    if n != n.to_integral_value():
        return None, "fractional"
    return int(n), "integer" if raw == str(int(n)) else "integer_format"


def value_assessment(records, selected, categories, inventory):
    comma_verified = {r["submission_id"] for r in selected
                      if "thousands display format reproduces" in r["table_selection_reason"]}
    info, frequencies, problems = {}, Counter(), defaultdict(list)
    for row in records:
        key = row["record_id"]
        currency, currency_kind = currency_value(row["currency_raw"])
        price, price_kind = parse_price(row["price_raw"], row["submission_id"] in comma_verified)
        if price_kind == "zero_review" and FREE_OFFER.search(row["description"]):
            price_kind = "zero_documented"
        age, age_kind, age_evidence = parse_age(row)
        condition, condition_kind = parse_condition(row["condition_raw"])
        family = categories[row["category"]]["diagnostic_family"]
        info[key] = {
            "currency": currency, "currency_kind": currency_kind, "price": price, "price_kind": price_kind,
            "age": age, "age_kind": age_kind, "age_evidence": age_evidence, "condition": condition,
            "condition_kind": condition_kind, "family": family,
        }
        frequencies["currency", row["currency_raw"], currency, currency_kind] += 1
        frequencies["condition", row["condition_raw"], "" if condition is None else str(condition), condition_kind] += 1
        frequencies["age", age_kind, age_evidence, "parse_status"] += 1
        frequencies["price", price_kind, "", "parse_status"] += 1
        if currency_kind in {"ambiguous_label", "unsupported_label"}:
            problems["currency_raw", currency_kind].append(row)
        if price_kind not in {"missing", "plain", "supported_grouping"}:
            problems["price_raw", price_kind].append(row)
        if age_kind not in {"missing", "numeric", "months", "years_text"}:
            problems["age_raw", age_kind].append(row)
        if age_kind == "months" and row["age_header_unit"] == "years":
            problems["age_raw", "header_cell_unit_conflict"].append(row)
        if age is not None and age >= 0:
            mentions = {Decimal(number) / (12 if unit.casefold().startswith("month") else 1)
                        for number, unit in AGE_MENTION.findall(row["description"])}
            if len(mentions) == 1:
                stated = next(iter(mentions))
                if abs(stated - age) > max(Decimal("0.25"), stated * Decimal("0.10")):
                    problems["age_raw", "description_age_disagreement"].append(row)
        if condition is None and condition_kind != "missing":
            problems["condition_raw", condition_kind].append(row)
        if price_kind == "embedded_currency":
            tokens = {token.upper().replace(" ", "") for token in PRICE_TOKEN.findall(row["price_raw"])}
            implied = {"US$": "USD", "₪": "ILS", "£": "GBP", "€": "EUR"}
            codes = {implied.get(token, CURRENCY_ALIASES.get(token, token)) for token in tokens} - {"$"}
            if currency and codes - {currency}:
                problems["currency_raw", "price_currency_conflict"].append(row)
    treatment = {
        "ambiguous_label": "Keep currency unresolved until the exact code is independently established",
        "unsupported_label": "Look for a documented source currency code",
        "ambiguous_separator": "Check original locale, listing, or corroborating export before parsing",
        "embedded_currency": "Separate amount and explicit currency only where both are clear",
        "price_currency_conflict": "Resolve the conflicting labels from reliable source evidence",
        "zero_review": "Retain zero. Verify whether free, negotiable, or an entry error",
        "zero_documented": "Retain the documented free offer and distinguish it from paid asking prices",
        "unit_typo_review": "Review the probable months typo before including the value in years",
        "header_cell_unit_conflict": "Prefer the explicit cell unit and retain its source provenance",
        "description_age_disagreement": "Check that the narrative refers to this item's age before making a correction",
        "age_range_review": "Keep the range until a defensible analytical representation is approved",
        "outside_scale": "Recover a score from original evidence or leave the analytical rating missing",
        "fractional": "Check the source before choosing an integer score",
        "label_conflict": "Verify the intended score against the source and Assignment 1 scale",
    }
    for (attribute, problem), group in sorted(problems.items()):
        context = ""
        if problem in {"zero_review", "zero_documented", "ambiguous_separator",
                       "description_age_disagreement", "age_range_review"}:
            context = " Source context " + audit.json_cell([
                {"record_id": r["record_id"], "title": r["title"], "category": r["category"],
                 "currency": r["currency_raw"],
                 "free_offer_phrase": FREE_OFFER.findall(r["description"]) if problem == "zero_documented" else [],
                 "age_phrases": AGE_MENTION.findall(r["description"]) if problem == "description_age_disagreement" else []}
                for r in group
            ]) + "."
        issue(inventory, problem, attribute, group, f"Observed form {problem.replace('_', ' ')}.{context}",
              ("invalid" if problem in {"negative", "nonfinite", "outside_scale", "fractional"}
               else "documented" if problem == "zero_documented" else "review"),
              treatment.get(problem, "Verify the original representation before using it analytically"))
    return info, frequencies, problems


def category_assessment(records, categories, inventory):
    unresolved = [row for row in records if categories[row["category"]]["status"] == "review"]
    if unresolved:
        issue(inventory, "category_label_review", "category", unresolved,
              "Broad, overlapping, or catch-all labels. Review the row's product context.",
              "review", "Retain the original meaning where product evidence is inconclusive")
    # A few specific title cues flag review candidates rather than assigning labels.
    cues = {
        "Vehicles": r"\b(?:mercedes[- ]benz|jeep wrangler|toyota (?:corolla|camry)|bmw \d{3}[a-z]?)\b",
        "Books": r"\b(?:paperback textbook|hardcover textbook|hardback novel|paperback novel)\b",
        "Musical instruments": r"\b(?:acoustic guitar|electric guitar|digital piano)\b",
    }
    conflicts = defaultdict(list)
    for row in records:
        title = text_key(row["title"])
        if re.search(r"\b(?:toy|miniature|case|accessory|cover|parts|poster|manual|scale model)\b", title):
            continue
        for family, pattern in cues.items():
            if re.search(pattern, title) and categories[row["category"]]["diagnostic_family"] != family:
                conflicts[family].append(row)
    for family, group in sorted(conflicts.items()):
        evidence = audit.json_cell({r["record_id"]: r["title"] for r in group})
        issue(inventory, "category_context_review", "category", group, f"Specific title cues suggest {family}. {evidence}",
              "candidate", "Use product context to review the category before changing it")
    return unresolved, conflicts


def groups_by(records, key):
    groups = defaultdict(list)
    for row in records:
        value = key(row)
        if value is not None and value != "":
            groups[value].append(row)
    return {value: rows for value, rows in groups.items() if len(rows) > 1}


def normalized_id(raw):
    value = text_key(raw)
    return re.sub(r"\d+", lambda m: m[0].lstrip("0") or "0", value)


def listing_key(raw):
    try:
        features = urlsplit(raw.strip())
        if features.scheme.lower() not in {"http", "https"} or not features.hostname:
            return ""
        query = tuple(sorted((k, v) for k, v in parse_qsl(features.query, keep_blank_values=True)
                             if not k.casefold().startswith("utm_")))
        return features.hostname.casefold(), features.path.rstrip("/") or "/", query
    except ValueError:
        return ""


def recorded_listing(row):
    raw = row["listing_link_raw"]
    if missing_kind("listing_link_raw", raw):
        return "", ""
    keys = {listing_key(h.get("target") or "") for h in json.loads(row["source_extras"]).get("hyperlinks", [])}
    keys.discard("")
    if display := listing_key(raw):
        keys.add(display)
        return (display, "literal URL") if len(keys) == 1 else ("", "conflicting URL evidence")
    if len(keys) == 1:
        return keys.pop(), "worksheet hyperlink target"
    return "", "conflicting URL evidence" if keys else "unparseable display and target"


def item_tokens(value):
    return set(re.findall(r"\w+", text_key(value))) - {
        "used", "second", "hand", "good", "new", "with", "and", "the", "for", "in", "a",
    }


def duplicate_records(records, info, inventory):
    identified = [r for r in records if not missing_kind("original_item_id", r["original_item_id"])]
    local = groups_by(identified, lambda r: (r["submission_id"], r["original_item_id"]))
    global_ids = {value: group for value, group in groups_by(identified, lambda r: r["original_item_id"]).items()
                  if len({r["student_id"] for r in group}) > 1}
    variant_ids = {value: group for value, group in groups_by(
        identified, lambda r: (r["submission_id"], normalized_id(r["original_item_id"]))
    ).items() if len({r["original_item_id"] for r in group}) > 1}
    cross_variants = {value: group for value, group in groups_by(
        identified, lambda r: normalized_id(r["original_item_id"])
    ).items() if len({r["student_id"] for r in group}) > 1 and len({r["original_item_id"] for r in group}) > 1}
    for groups, kind in ((local, "original_id_repeated_within_submission"),
                         (global_ids, "original_id_reused_across_students"),
                         (variant_ids, "original_id_format_collision_within_submission"),
                         (cross_variants, "original_id_format_reuse_across_students")):
        for group in groups.values():
            issue(inventory, kind, "original_item_id", group,
                  "Identity check uses the recorded ID. Formatting candidates also compare case, spaces, and zero padding.",
                  "observed", "Use record_id for identity. Keep the original ID and review local collisions")
    exact = groups_by(records, lambda r: tuple(r[column] for column in ANALYTICAL)
                      if r["title"].strip() and r["description"].strip() else None)
    normalized = groups_by(records, lambda r: (text_key(r["title"]), text_key(r["description"]))
                           if r["title"].strip() and r["description"].strip() else None)
    listings = {r["record_id"]: recorded_listing(r) for r in records}
    by_url = groups_by(records, lambda r: listings[r["record_id"]][0])
    title_only = groups_by(records, lambda r: text_key(r["title"]))
    for groups, kind, confidence in ((exact, "exact_item_attribute_duplicate", "exact selected fields"),
                                     (normalized, "repeated_normalized_title_and_description", "candidate"),
                                     (by_url, "repeated_listing_link", "same listing address")):
        for group in groups.values():
            issue(inventory, kind, "record", group, "Compared item attributes or recorded listing address without provenance.",
                  confidence, "Review identity, source links, and images before excluding any observation")

    buckets = defaultdict(list)
    for r in records:
        d = info[r["record_id"]]
        amount = d["price"]
        if d["price_kind"] == "ambiguous_separator":
            # The grouped alternative is considered only as duplicate-candidate evidence.
            amount = Decimal(r["price_raw"].replace(",", "").strip())
        if amount is not None and amount > 0 and d["currency"] and d["family"]:
            buckets[(d["family"], d["currency"], amount)].append(r)
    candidates = {}
    for group in buckets.values():
        for first, second in combinations(group, 2):
            a, b = item_tokens(first["title"]), item_tokens(second["title"])
            shared, union = a & b, a | b
            if not union or not shared:
                continue
            overlap = len(shared) / len(union)
            description = SequenceMatcher(None, text_key(first["description"]), text_key(second["description"]),
                                          autojunk=False).ratio()
            model_token = any(len(word) >= 3 and any(char.isdigit() for char in word) for word in shared)
            if (overlap >= .45 and model_token) or (overlap >= .60 and description >= .40):
                key = tuple(sorted((first["record_id"], second["record_id"])))
                candidates[key] = (first, second, overlap, description)
    for problem in ("conflicting URL evidence", "unparseable display and target"):
        invalid_links = [row for row in records if listings[row["record_id"]][1] == problem]
        if invalid_links:
            issue(inventory, "listing_evidence_review", "listing_link_raw", invalid_links, problem,
                  "review", "Keep the original link and review its source")
    return {
        "local_ids": local, "shared_ids": global_ids, "variants_local": variant_ids,
        "variants_cross": cross_variants, "exact": exact, "normalized": normalized,
        "listing": by_url, "title_only": title_only, "candidates": candidates,
        "listing_forms": Counter(form for _, form in listings.values() if form),
    }


def fingerprint_photo(data):
    with Image.open(io.BytesIO(data)) as image:
        pixels = ImageOps.exif_transpose(image).convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    return sum((pixels[r * 9 + c] > pixels[r * 9 + c + 1]) << (r * 8 + c)
               for r in range(8) for c in range(8))


def image_assessment(root, records, selected, duplicates, info, inventory):
    by_image, by_record = defaultdict(list), defaultdict(list)
    for row in records:
        for link in json.loads(row["image_links"]):
            image = tuple(link["locator"])
            by_image[image].append(row)
            by_record[row["record_id"]].append(image)
    # Similarity is useful only for already compatible item-record candidates.
    candidate_images = {loc for pair in duplicates["candidates"] for key in pair for loc in by_record[key]}
    hashes, visual, owners = {}, {}, {}
    for sub in selected:
        locators = [tuple(loc) for loc in json.loads(sub["image_file_locators"])]
        files = integration.read_selected_files(root, json.loads(sub["original_submission_paths"]), locators)
        for loc, data in files.items():
            if loc in hashes:
                raise ValueError("Duplicate locator in selected image inventory.")
            hashes[loc] = hashlib.sha256(data).hexdigest()
            owners[loc] = sub["submission_id"]
            if loc in candidate_images:
                visual[loc] = fingerprint_photo(data)
    if by_image.keys() - hashes.keys():
        raise ValueError("An exported image locator is missing from the selected image inventory.")
    digests = defaultdict(list)
    for loc, digest in hashes.items():
        digests[digest].append(loc)
    exact = [locators for locators in digests.values() if len(locators) > 1]
    audit_issues, _ = integration.read_csv(integration.local_path(root, "Audit/phase0_issues.csv"))
    reference = {frozenset(json.loads(i["evidence"])) for i in audit_issues
                 if i["issue_type"] == "byte_identical_image_group"}
    actual = {frozenset(" :: ".join(loc) for loc in group) for group in exact}
    if actual != reference:
        raise ValueError("Selected image duplicate groups differ from the Phase 0 inventory.")
    same_photo_pairs, shared_records = set(), set()
    for group in exact:
        unique = {r["record_id"]: r for loc in group for r in by_image[loc]}
        rows = [unique[key] for key in sorted(unique)]
        same_photo_pairs.update(combinations(sorted(unique), 2))
        shared_records.update(unique)
        details = [{
            "record_id": r["record_id"], "title": r["title"], "category": r["category"],
            "price": r["price_raw"], "currency": r["currency_raw"], "age": r["age_raw"],
            "condition": r["condition_raw"],
        } for r in rows]
        price_currency = {(info[r["record_id"]]["price"], info[r["record_id"]]["currency"]) for r in rows}
        agreeing = len(rows) > 1 and len(price_currency) == 1 and all(price_currency.pop())
        issue(inventory, "byte_identical_images", "image_links", rows,
              f"Identical SHA-256 across {len(group)} filenames. Amount and currency agree? {agreeing}. "
              f"Associated source items {audit.json_cell(details)}. Shared photographs and compatible attributes "
              "support duplicate-item review. They cannot establish the listing identity on their own.",
              "exact file match, item identity unresolved",
              "Review source listing or capture evidence. Retain both files and observations for now",
              value=audit.json_cell([list(loc) for loc in group]))
    reused = {loc: group for loc, group in by_image.items() if len(group) > 1}
    for loc, group in reused.items():
        issue(inventory, "image_referenced_by_multiple_records", "image_links", group,
              "Multiple rows point to the same selected locator.", "observed",
              "Verify the intended use of this photograph", value=audit.json_cell(list(loc)))
    perceptual = 0
    reviewed_pairs = 0
    details = []
    for pair, (first, second, overlap, description) in duplicates["candidates"].items():
        if pair in same_photo_pairs:
            continue
        comparisons = [(visual[a] ^ visual[b]).bit_count() for a in by_record[pair[0]] for b in by_record[pair[1]]
                       if hashes[a] != hashes[b]]
        distance = min(comparisons, default=None)
        reviewed_pairs += distance is not None
        similar = distance is not None and distance <= 5
        perceptual += similar
        evidence = (f"Comparable family, currency and recorded/possible grouped price. Title-token overlap "
                    f"{overlap:.2f}, description similarity {description:.2f}, "
                    f"minimum unequal-file dHash distance {distance if distance is not None else 'unavailable'}/64. "
                    f"Item titles {audit.json_cell([first['title'], second['title']])}.")
        issue(inventory, "possible_duplicate_item_record", "record", [first, second], evidence,
              "candidate with perceptual support" if similar else "candidate from item attributes",
              "Compare reliable listing identifiers or original capture context before excluding rows",
              value=audit.json_cell([first["price_raw"], second["price_raw"]]))
        details.append((first, second, distance, similar))
    statuses = Counter(r["image_status"] for r in records)
    unlinked = hashes.keys() - by_image.keys()
    missing = [r for r in records if r["image_status"] == "missing"]
    if unlinked:
        issue(inventory, "unlinked_image_files", "image_links", [],
              f"{len(unlinked)} verified selected image file(s) have no justified item association.",
              "unresolved", "Preserve original photos and require item-specific linkage evidence",
              value=audit.json_cell([list(loc) for loc in sorted(unlinked)]))
    if missing:
        issue(inventory, "missing_image_association", "image_status", missing,
              "Phase 1 exhausted the recorded name, item-ID, and available image metadata evidence.",
              "unresolved", "Retain otherwise useful rows. Leave image-dependent analysis unavailable")
    plausible = [r for r in records if r["image_status"] in {"plausible", "ambiguous"}]
    if plausible:
        issue(inventory, "image_reference_confidence", "image_status", plausible,
              "Association uses filename repair, numbering, or item-folder evidence. Existing row-level methods remain in the raw CSV.",
              "not visually verified", "Carry association confidence forward and avoid assuming visual correspondence")
    return {
        "statuses": statuses, "files": len(hashes), "unique_hashes": len(digests), "exact": exact,
        "duplicate_records": len(shared_records), "reused": len(reused), "unlinked": len(unlinked),
        "cross_submission_groups": sum(len({owners[loc] for loc in group}) > 1 for group in exact),
        "linked": len(by_image), "multi_photo_rows": sum(len(group) > 1 for group in by_record.values()),
        "perceptual": perceptual, "reviewed_pairs": reviewed_pairs, "candidates": details,
    }


def outlier_context(attribute, row, amount, family, reference_year):
    title = text_key(row["title"])
    details = text_key(row["description"])
    antique = r"\b(?:antique|edwardian|victorian|19th century|pre[- ]?1900|circa 18\d{2})\b"
    if attribute == "age_raw" and amount >= 70 and re.search(antique, title + " " + details):
        return "Historical wording supports a plausible extreme age"
    if attribute == "age_raw" and amount >= 20:
        if year := re.search(r"\(((?:19|20)\d{2})\)", title):
            if abs(reference_year - int(year[1]) - amount) <= 2:
                return "The year in the title supports a plausible extreme age"
    if attribute == "price_raw" and (family == "Vehicles" or re.search(r"\b(?:farm|mercedes[- ]benz|jeep wrangler)\b", title)):
        return "High-value asset context supports a plausible extreme price"
    if attribute == "age_raw" and amount >= 100:
        return "Century-scale age needs source context or collection-year verification"
    return "Check listing and variant context before treating the observation as erroneous"


def outlier_assessment(records, info, problems, inventory, reference_year):
    price, age = defaultdict(list), []
    price_excluded, age_excluded = Counter(), Counter()
    conflicted_age = {r["record_id"] for r in problems.get(("age_raw", "description_age_disagreement"), ())}
    for row in records:
        record_id = row["record_id"]
        d = info[record_id]
        if d["price_kind"] not in {"plain", "supported_grouping"}:
            price_excluded[d["price_kind"]] += 1
        elif not d["currency"]:
            price_excluded["currency_" + d["currency_kind"]] += 1
        else:
            price[d["currency"]].append((row, float(d["price"])))
        if d["age"] is None or d["age"] < 0:
            age_excluded[d["age_kind"]] += 1
        elif record_id in conflicted_age:
            age_excluded["description_age_disagreement"] += 1
        else:
            age.append((row, float(d["age"])))
    scopes, candidates = [], defaultdict(list)

    def evaluate(attribute, unit, label, rows, minimum):
        values = pd.Series([value for _, value in rows], dtype="float64")
        stats = {"attribute": attribute, "unit": unit, "scope": label, "n": len(rows)}
        if len(rows) >= minimum:
            q1, q3 = values.quantile([.25, .75], interpolation="linear")
            iqr = q3 - q1
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            mean, median, sd = values.mean(), values.median(), values.std(ddof=1)
            low, high = 0, 0
            for row, number in rows:
                if number < lower or number > upper:
                    direction = "lower" if number < lower else "upper"
                    low += direction == "lower"
                    high += direction == "upper"
                    candidates[(attribute, row["record_id"])].append((label, direction, number, lower, upper))
            stats.update(q1=q1, q3=q3, iqr=iqr, lower=lower, upper=upper, mean=mean, median=median, sd=sd,
                         skew=3 * (mean - median) / sd if sd > 0 else None, low=low, high=high)
        scopes.append(stats)

    def by_family(rows):
        out = defaultdict(list)
        for row, amount in rows:
            if family := info[row["record_id"]]["family"]:
                out[family].append((row, amount))
        return out

    for currency, rows in sorted(price.items()):
        evaluate("price_raw", currency, "All eligible", rows, MIN_CURRENCY_N)
        for label, group in sorted(by_family(rows).items()):
            if len(group) >= MIN_CATEGORY_N:
                evaluate("price_raw", currency, label, group, MIN_CATEGORY_N)
    evaluate("age_raw", "years", "All eligible", age, MIN_CURRENCY_N)
    for label, group in sorted(by_family(age).items()):
        if len(group) >= MIN_CATEGORY_N:
            evaluate("age_raw", "years", label, group, MIN_CATEGORY_N)
    row_index = {r["record_id"]: r for r in records}
    context_counts = Counter()
    for (attribute, record_id), evidence in sorted(candidates.items()):
        row = row_index[record_id]
        amount = evidence[0][2]
        context = outlier_context(attribute, row, amount, info[record_id]["family"], reference_year)
        context_counts[(attribute, context)] += 1
        bounds = [{"scope": scope, "direction": direction, "amount": value,
                   "fences": [float(lower), float(upper)]} for scope, direction, value, lower, upper in evidence]
        issue(inventory, "iqr_outlier_candidate", attribute, [row],
              f"{context}. Title {row['title']!r}. Category {row['category']!r}. "
              f"Description excerpt {row['description'][:180]!r}. "
              f"Comparison unit {info[record_id]['currency'] if attribute == 'price_raw' else 'years'}. "
              f"Scopes {audit.json_cell(bounds)}.",
              "diagnostic candidate", "Retain pending contextual review. Correct only with reliable evidence")
    if (sum(price_excluded.values()) + sum(map(len, price.values())) != len(records)
            or sum(age_excluded.values()) + len(age) != len(records)):
        raise ValueError("Outlier eligibility and exclusions do not reconcile.")
    return scopes, candidates, price, age, price_excluded, age_excluded, context_counts


def structural_assessment(records, selections, inventory):
    counts = Counter()
    for row in records:
        details = json.loads(row["source_extras"])
        if kind := details.get("alignment"):
            counts[kind] += 1
        for kind in ("additional_cells", "hyperlinks"):
            counts[kind] += kind in details
    unresolved = [r for r in records if json.loads(r["source_extras"]).get("alignment") == "unquoted_prose_boundary"]
    if unresolved:
        issue(inventory, "unresolved_title_description_boundary", "source_extras", unresolved,
              "Phase 1 verified the identifiable trailing fields and preserved the original fragment sequence.",
              "unresolved", "Use reliable source text if available. Keep the fragments and avoid inventing boundaries",
              value="See parsed_source_fields in the immutable source_extras column")
    absent_currency_subs = set()
    for row in selections:
        _, spec = integration.selected_table(row)
        if not any(integration.field_role(h) == "currency" for h in spec["columns"]):
            absent_currency_subs.add(row["submission_id"])
    missing_currency_rows = [r for r in records if r["submission_id"] in absent_currency_subs]
    counts["currency_column_absent"] = len(missing_currency_rows)
    counts["currency_column_absent_tables"] = len(absent_currency_subs)
    counts["absent_currency_text_cues"] = sum(
        bool(PRICE_TOKEN.search(" ".join(r[k] for k in ("title", "description", "price_raw"))))
        for r in missing_currency_rows
    )
    counts["absent_currency_listings"] = sum(bool(r["listing_link_raw"].strip()) for r in missing_currency_rows)
    row_counts = Counter(r["submission_id"] for r in records)
    counts["rows_over_expected"] = sum(value > audit.EXPECTED_ITEMS for value in row_counts.values())
    counts["image_counts_over_expected"] = sum(int(r["image_files"]) > audit.EXPECTED_ITEMS for r in selections)
    counts["header_age_years"] = sum(r["age_header_unit"] == "years" for r in records)
    counts["reference_year"] = max(int(time[:4]) for row in selections
                                   for time in json.loads(row["export_attachment_timestamps"]))
    return counts


def count_rows(groups):
    return len({r["record_id"] for group in groups.values() for r in group})


def display_counts(counts):
    return ", ".join(f"{str(label).replace('_', ' ')} ({n:,})" for label, n in sorted(counts.items()) if n) or "none"


def markdown(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def report(records, digest, attachments, categories, category_reviews, missing, quality, duplicates,
           images, structure, outliers, inventory):
    counts, missing_rows, analytical_gaps = missing
    info, _, problems = quality
    scopes, candidates, prices, ages, price_excluded, age_excluded, contexts = outliers
    notes = Counter(i["issue_type"] for i in inventory)
    affected = {record_id for i in inventory for record_id in json.loads(i["record_ids"])}
    nonblank_ids = {r["original_item_id"] for r in records if not missing_kind("original_item_id", r["original_item_id"])}
    known = {r["record_id"] for group in prices.values() for r, _ in group}
    age_known = {r["record_id"] for r, _ in ages}
    condition_known = {key for key, v in info.items() if v["condition"] is not None}
    category_known = {r["record_id"] for r in records if not missing_kind("category", r["category"])}
    raw_categories = sum(bool(label.strip()) for label in categories)
    with_spaces = sum(r["category"] != r["category"].strip() for r in records)
    category_reviews, conflicts = category_reviews
    status_categories = Counter()
    for value in categories.values():
        status_categories[value["status"]] += value["records"]
    by_student = Counter(r["submission_id"] for r in missing_rows["age_raw"])
    missing_age_groups = [
        sum(r["submission_id"] == sub for r in records) - count for sub, count in by_student.items()
    ]
    by_category = Counter(r["category"] for r in missing_rows["age_raw"])
    category_totals = Counter(r["category"] for r in records)
    age_placeholders = Counter(r["age_raw"] for r in missing_rows["age_raw"]
                               if missing_kind("age_raw", r["age_raw"]) == "placeholder")
    highest_category = sorted(by_category, key=lambda label: (-by_category[label], label))[:3]
    n = len(records)
    source_ids = len({r["student_id"] for r in records})
    text = [
        "# Assignment 2 Phase 2 data quality assessment", "", "## Baseline and scope", "",
        f"- Verified {n:,} observations, {source_ids} students, {len(integration.COLUMNS)} columns and "
        f"{len({r['record_id'] for r in records}):,} unique record IDs. The raw data contain "
        f"{raw_categories} nonblank category labels and {len(nonblank_ids)} distinct nonblank exact original IDs.",
        f"- The raw CSV matched Phase 1 SHA-256 before and after the assessment. The digest is `{digest}`. "
        f"Verified all {attachments} original attachments against their export and hashed the {images['files']:,} "
        "selected standalone images. Parsed values were used only in memory.",
        "- Assignment 2 §3 defines the required assessment. Assignment 1 §§2 and 4 specify approximate age in "
        "years and require a recorded currency, with no default. Assignment 1 §5 defines the five condition labels. "
        "The lecture informs missing-value treatment, sample standard deviation, Pearson's second skewness and IQR review.",
        "", "## Missing and incomplete values", "",
        "| Column | Total | Empty | Whitespace | Placeholder | Empty metadata or format only | "
        "Absent source column | Missing / absent | Percent | Available | Interpretation |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for column in integration.COLUMNS:
        forms, absent = counts[column]
        missing_n = sum(forms.values())
        kind = ("Analytical attribute" if column in ANALYTICAL else "Optional or not applicable" if column in OPTIONAL
                else "Image evidence" if column.startswith("image_") else "Identifier or provenance")
        text.append(f"| `{column}` | {n:,} | {forms['empty']:,} | {forms['whitespace']:,} | "
                    f"{forms['placeholder']:,} | {forms['empty_json'] + forms['format_only']:,} | {absent:,} | "
                    f"{missing_n:,} | {100 * missing_n / n:.2f}% | {n - missing_n:,} | {kind} |")
    text += [
        "", "Absent source columns are a subset of the missing/absent count. Optional fields include CSV worksheet "
        "names, optional links, and empty JSON for flags or extra cells. A raw photo field may be absent while an "
        "associated file is available. The image status distinguishes these cases. Zero stays a recorded value.",
        f"- {sum(bool(set(fields) & set(ANALYTICAL)) for fields in analytical_gaps.values()):,} rows have a missing analytical field. "
        f"Missing age affects {len(by_student)} submissions. A maximum of {max(by_student.values(), default=0)} ages "
        f"are missing in one submission. {sum(value == 0 for value in missing_age_groups)} affected submissions have no age values.",
        f"- Recorded age placeholders are {display_counts(age_placeholders)}.",
        "- Highest missing ages by exact raw category are " + ", ".join(
            f"`{markdown(label) or '(blank)'}` {by_category[label]}/{category_totals[label]}" for label in highest_category
        ) + ".",
        f"- Available analytically comparable price and age pairs total {len(known & age_known):,}. "
        f"Price and valid condition pairs total {len(known & condition_known):,}, and price and nonblank category "
        f"pairs total {len(known & category_known):,}. These availability counts still require currency-specific comparison.",
        "", "## Duplicate assessment", "",
        "| Evidence | Groups | Affected records |",
        "|---|---:|---:|",
    ]
    for title, name in (
        ("Exact original ID within a submission", "local_ids"),
        ("Exact original ID across students", "shared_ids"),
        ("Likely ID formatting collision within a submission", "variants_local"),
        ("Different representations of the same normalized ID across students", "variants_cross"),
        ("Exact values across the seven item attributes", "exact"),
        ("Same normalized title and description", "normalized"),
        ("Same recorded listing address or workbook hyperlink target", "listing"),
        ("Shared normalized title only (insufficient evidence)", "title_only"),
    ):
        group = duplicates[name]
        text.append(f"| {title} | {len(group)} | {count_rows(group):,} |")
    text += [
        "",
        f"- Byte-identical photo files form {len(images['exact'])} groups of "
        f"{sum(map(len, images['exact']))} files across {images['duplicate_records']} item records. "
        f"{images['cross_submission_groups']} groups cross submissions. {images['reused']} individual paths "
        "were linked to multiple records. Exact photo reuse with agreeing item context and prices merits review, "
        "but does not by itself establish the same listing.",
        f"- Found {len(images['candidates'])} additional item pairs with compatible category family, currency, "
        "amount or a possible grouping interpretation, and strong text or model-token evidence. "
        f"Used 64-bit adjacent-pixel dHash only on these candidate pairs. {images['reviewed_pairs']} pairs had "
        f"nonidentical files to compare, and {images['perceptual']} met the distance threshold of 5 bits. "
        "Review listing identity before excluding observations. Similar models can be legitimate separate items.",
        f"- Optional listing links by source form are {display_counts(duplicates['listing_forms'])}. "
        "The comparison uses saved worksheet targets where the cell has display text. No links were fetched.",
        "", "## Representation and validity findings", "",
        f"- **Category.** The proposed map covers all {n:,} records "
        f"({display_counts(status_categories)}). {with_spaces} rows have outer spaces. Case, accents, "
        "spacing, equivalent conjunctions, and reviewed singular/plural or synonym pairs share a proposal. "
        "Specific product subcategories stay distinct. Category families pool related labels only for diagnostics. "
        f"{len(category_reviews)} rows have broad or overlapping labels and "
        f"{count_rows(conflicts)} have product-title cues warranting category review.",
        f"- **Currency.** Recorded forms and their proposed code mappings are in the value-frequency table. "
        f"Resolved diagnostic currencies are {display_counts(Counter(v['currency'] for v in info.values() if v['currency']))}. "
        "ILS, NIS, Shekel and ₪ are equivalent labels. Dollar alone leaves the currency unresolved. "
        f"The {structure['currency_column_absent_tables']} table(s) without a currency column contribute "
        f"{structure['currency_column_absent']} rows. In those rows the text or price fields contain "
        f"{structure['absent_currency_text_cues']} explicit code/symbol cues and "
        f"{structure['absent_currency_listings']} listing links. Phase 1 found no currency in price headers.",
        f"- **Age.** {structure['header_age_years']} rows have a header declaring years. For plain numbers in "
        f"other headers ({n - structure['header_age_years']:,} total rows with unspecified headers), "
        "Assignment 1 supplies the intended unit. Explicit units in cells take precedence. Only definite month "
        "values were expressed in years for diagnostics. Ranges, ambiguous units and narrative conflicts are "
        f"reviewed separately. Observed assessment forms are {display_counts(Counter(v['age_kind'] for v in info.values()))}.",
        f"- **Condition.** Assessed forms are {display_counts(Counter(v['condition_kind'] for v in info.values()))}. "
        "Standalone condition labels and number/label pairs were checked against Assignment 1's rubric.",
        f"- **Price.** Assessed forms are {display_counts(Counter(v['price_kind'] for v in info.values()))}. "
        "Mixed grouping and decimal punctuation is usable when unambiguous or corroborated by the original "
        "workbook format. An otherwise uncorroborated single comma stays unresolved. "
        "A zero with explicit free-offer wording is valid and stays separate from paid-price diagnostics.",
        "", "| Review flag | Attribute | Records |", "|---|---|---:|",
    ]
    for attribute, kinds in (
        ("price_raw", ("negative", "nonfinite", "unparseable", "embedded_currency", "ambiguous_separator",
                       "zero_review", "zero_documented")),
        ("age_raw", ("negative", "nonfinite", "unparseable", "age_range_review", "unit_typo_review",
                     "header_cell_unit_conflict", "description_age_disagreement")),
        ("condition_raw", ("outside_scale", "fractional", "label_conflict", "unparseable", "nonfinite")),
        ("currency_raw", ("ambiguous_label", "unsupported_label", "price_currency_conflict")),
    ):
        for kind in kinds:
            text.append(f"| {kind.replace('_', ' ')} | `{attribute}` | {len(problems.get((attribute, kind), ())) } |")
    text += [
        "", "## IQR outlier diagnostics", "",
        f"Price includes {len(known):,} eligible rows. Exclusions are {display_counts(price_excluded)}. "
        f"Age includes {len(ages):,} eligible rows. Exclusions are {display_counts(age_excluded)}. "
        "Each excluded row is counted under its first blocking reason. "
        f"{sum(len(group) for group in prices.values() if len(group) < MIN_CURRENCY_N)} price rows "
        "have an interpretable amount and currency but fall in currency samples too small for fences. "
        f"Price cohorts use each currency separately. Overall fences require at least {MIN_CURRENCY_N} values, "
        f"and category-family fences require at least {MIN_CATEGORY_N} within the same unit. Age cohorts use years. "
        "Quartiles use linear interpolation, fences use 1.5 × IQR, and sample SD uses n−1. Pearson's second "
        "coefficient is omitted for zero SD or an unassessed cohort.",
        "", "| Attribute | Unit | Scope | n | Mean | Median | SD | Pearson S | Q1 | Q3 | IQR | "
        "Lower fence | Upper fence | Low flags | High flags |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scope in scopes:
        values = [scope["attribute"].removesuffix("_raw"), scope["unit"], markdown(scope["scope"]), str(scope["n"])]
        values.extend("—" if scope.get(key) is None else f"{scope[key]:,.6g}"
                      for key in ("mean", "median", "sd", "skew", "q1", "q3", "iqr", "lower", "upper", "low", "high"))
        text.append("| " + " | ".join(values) + " |")
    n_price = sum(attribute == "price_raw" for attribute, _ in candidates)
    n_age = sum(attribute == "age_raw" for attribute, _ in candidates)
    text += [
        "",
        f"- Unique candidates across overall and family fences total {n_price} price rows and {n_age} age rows. "
        "A row can contribute to several fences. Each record/attribute pair has one issue entry with its applicable scopes.",
    ]
    for (attribute, context), count in sorted(contexts.items()):
        text.append(f"- {attribute.removesuffix('_raw').capitalize()} context for {count} candidates. {context}.")
    row_index = {row["record_id"]: row for row in records}
    for attribute in ("price_raw", "age_raw"):
        context_examples = [(evidence[0][2], row_index[key]) for (field, key), evidence in candidates.items()
                            if field == attribute and outlier_context(field, row_index[key], evidence[0][2],
                                                                      info[key]["family"], structure["reference_year"]
                                                                      ).startswith(("Historical", "High-value"))]
        if context_examples:
            amount, example = max(context_examples, key=lambda pair: pair[0])
            unit = info[example["record_id"]]["currency"] if attribute == "price_raw" else "years"
            text.append(f"- Example retained for review. {markdown(example['title'])!r} at {amount:,.6g} {unit}.")
    text += [
        "- An outlier flag is evidence for investigation. Retain plausible extreme ages and high-value assets. "
        "The issue inventory preserves original values, item titles, comparison units and fences for contextual review.",
        "", "## Image and structural findings", "",
        f"- Verified {images['files']:,} image files with {images['unique_hashes']:,} distinct byte hashes. "
        f"Associations by record are {display_counts(images['statuses'])}. {images['unlinked']} file(s) remain unlinked, "
        f"and {images['multi_photo_rows']} row(s) have multiple photo links. Confirmed means file-reference confirmation. "
        "Visual correspondence with a listing has not been verified.",
        f"- {structure['rows_over_expected']} submission(s) exceed the requested item count and "
        f"{structure['image_counts_over_expected']} exceed the expected image count. "
        f"{structure['space_prefixed_quoted_description']} repaired quoted rows were structurally verified in Phase 1. "
        f"{structure['unquoted_prose_boundary']} rows still have uncertain text boundaries and retain their fragments. "
        "The unresolved image does not block analysis of available item attributes.",
        "", "## Proposed Phase 3 treatment", "",
        "| Issue | Evidence | Preferred treatment and reason | Remaining uncertainty |",
        "|---|---|---|---|",
        f"| Missing data | {sum(counts['age_raw'][0].values())} ages and {sum(counts['price_raw'][0].values())} prices missing | "
        "Preserve missingness. Use available valid values per analysis and report sample sizes. Concentration in "
        "certain submissions makes blanket imputation particularly weak. Use an explicit Unknown label only for "
        "categorical reporting where useful. | Missingness mechanisms are unverified. |",
        f"| Identifier reuse | {len(duplicates['shared_ids'])} exact ID groups across students | "
        "Retain generated IDs and Original IDs. Check repeat groups separately from record duplication. | Local naming is not marketplace identity. |",
        f"| Duplicate evidence | {len(images['exact'])} identical-photo groups, {len(images['candidates'])} further candidate pairs | "
        "Require convincing listing or capture evidence before excluding records. Preserve file and source provenance. | Same item versus reused photo is unresolved. |",
        "| Categories | Full mapping and review statuses in the category CSV | Apply only equivalent labels after "
        "approval. Keep original labels, distinct subcategories, and uncertain assignments traceable. | Review broad and context-conflict labels. |",
        f"| Currency | {sum(counts['currency_raw'][0].values())} missing and "
        f"{len(problems.get(('currency_raw', 'ambiguous_label'), ()))} ambiguous | Normalize evidenced labels, and "
        "compare within currency. If a pooled comparison is required, use ILS with documented published rates for "
        "the collection date and direction, retaining source amounts and codes. | Missing codes and undocumented dates limit conversion. |",
        "| Age and condition | Assignment 1 gives years and the condition scale | Use explicit cell units or the "
        "verified course default for years. Apply the documented label rubric. Resolve unsupported or invalid scores "
        "from evidence or leave the analytical value unavailable. | Text-unit typo, narrative conflicts, or abnormal ratings need verification. |",
        f"| Extreme values | {n_price} price and {n_age} age IQR candidates | Retain plausible extremes. Compare "
        "in compatible groups and correct only with source evidence. | Some extreme prices and unusual estimated ages remain unverified. |",
        "| Incomplete text or images | Source fragments and per-file association confidence | Keep records; preserve "
        "uncertain text and linkage status. | Further labeling requires original evidence. |",
        "", f"The inventory has {len(inventory)} issue entries covering {len(affected):,} distinct records. "
        "Counts overlap across attributes and rules. Entries without a record refer to unlinked files.",
        "Issue types and counts are " + display_counts(notes) + ".",
        "", "**Ready for Phase 3 review.** The recommended treatments are proposals. Ambiguous currency, separator, "
        "duplicate, and text cases need source evidence or an approved decision to leave them unresolved.", "",
    ]
    return "\n".join(text)


def diagnostics(prices, ages):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    currencies = sorted(prices, key=lambda code: (-len(prices[code]), code))[:2]
    panels = [(f"Price ({code})", [amount for _, amount in prices[code]]) for code in currencies]
    panels.append(("Age (years)", [amount for _, amount in ages]))
    fig, axes = plt.subplots(len(panels), 2, squeeze=False, figsize=(11, 8),
                            gridspec_kw={"width_ratios": [1.5, 1]}, layout="constrained")
    fig.suptitle("Phase 2 · Outlier diagnostics", fontsize=16, fontweight="bold")
    for (label, values), (histogram, box) in zip(panels, axes, strict=True):
        low = min((x for x in values if x > 0), default=1.0)
        high = max(values)
        if high > low:
            left, right = math.log10(low), math.log10(high)
            bins = [10 ** (left + i * (right - left) / 24) for i in range(25)]
            bins[0], bins[-1] = low, high
            if 0 in values:
                bins = [0, *bins]
        else:
            bins = 10
        histogram.hist(values, bins=bins, color="#176c78", edgecolor="white", linewidth=.45)
        histogram.set_title(f"{label} histogram  ·  n={len(values):,}", loc="left", fontsize=11)
        histogram.set_ylabel("Records")
        box.boxplot(values, orientation="horizontal", whis=1.5, patch_artist=True,
                    boxprops={"facecolor": "#a8d3ce", "edgecolor": "#176c78"},
                    medianprops={"color": "#17394a", "linewidth": 1.5},
                    flierprops={"marker": ".", "markersize": 3, "markeredgecolor": "#9b542e"})
        box.set_title(f"{label} boxplot", loc="left", fontsize=11)
        box.set_yticks([])
        for axis in (histogram, box):
            axis.set_xscale("symlog", linthresh=low)
            axis.set_xlabel(f"{label} · log-spaced axis")
            axis.spines[["top", "right"]].set_visible(False)
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=145, metadata={"Software": "Phase 2 data quality diagnostics"})
    plt.close(fig)
    return out.getvalue()


def csv_output(rows, columns):
    return pd.DataFrame.from_records(list(rows), columns=columns).to_csv(index=False, lineterminator="\n").encode("utf-8")


def assess(root):
    root = root.resolve()
    raw, digest, frame, manifest, selected = load_baseline(root)
    attachments = integration.verify_originals(root, manifest)
    records = frame.to_dict("records")
    inventory = []
    categories = category_mapping(records)
    missing = missing_assessment(records, selected, inventory)
    category_reviews = category_assessment(records, categories, inventory)
    quality = value_assessment(records, selected, categories, inventory)
    info, frequencies, problems = quality
    duplicates = duplicate_records(records, info, inventory)
    images = image_assessment(root, records, selected, duplicates, info, inventory)
    if images["files"] != sum(int(row["image_files"]) for row in selected):
        raise ValueError("The selected image count differs from the manifest.")
    structure = structural_assessment(records, selected, inventory)
    outliers = outlier_assessment(records, info, problems, inventory, structure["reference_year"])
    summary = report(records, digest, attachments, categories, category_reviews, missing, quality,
                     duplicates, images, structure, outliers, inventory)
    figures = diagnostics(outliers[2], outliers[3])
    frequency_rows = [{"attribute": attribute, "raw_label_or_form": value, "diagnostic_interpretation": meaning,
                       "status": status, "records": count}
                      for (attribute, value, meaning, status), count in sorted(frequencies.items())]
    if audit.digest_file(raw).hex() != digest or integration.verify_originals(root, manifest) != attachments:
        raise ValueError("Raw data or an original attachment changed during assessment.")
    outputs = {
        "phase2_summary.md": summary.encode("utf-8"),
        "phase2_issues.csv": csv_output(inventory, ISSUE_COLUMNS),
        "phase2_category_mapping.csv": csv_output(categories.values(),
                                                 ("raw_category", "records", "proposed_category",
                                                  "diagnostic_family", "status", "reason")),
        "phase2_value_frequencies.csv": csv_output(frequency_rows,
                                                  ("attribute", "raw_label_or_form",
                                                   "diagnostic_interpretation", "status", "records")),
        "phase2_diagnostics.png": figures,
    }
    for name, content in outputs.items():
        integration.write_output(root / "Audit" / name, content)
    if audit.digest_file(raw).hex() != digest:
        raise ValueError("The raw CSV changed before assessment completed.")
    return len(records), len(inventory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Source root with the raw CSV, original attachments and audit files")
    args = parser.parse_args()
    try:
        observations, issues = assess(args.root)
    except audit.FILE_ERRORS + (tarfile.TarError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Phase 2 assessment failed. {exc}\n")
    print(f"Assessed {observations:,} original records. Wrote {issues} local issue entries and supporting audit outputs.")


if __name__ == "__main__":
    main()

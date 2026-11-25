"""Produce the Phase 3 analytical CSV from the immutable source and local decisions."""
import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
import statistics as stats
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

import phase0_audit as audit
import phase1_integration as integration
import phase2_quality_assessment as quality
import pre_cleaning_verification as review

FIELDS = ("age_years", "condition_rating", "price_ils")
METHOD_FIELDS = dict(zip(FIELDS, ("age_method", "condition_method", "price_method")))
SOURCE_NUMERICS = dict(zip(FIELDS, ("age_raw", "condition_raw", "price_raw")))
METHODS = {
    "age_years": ("global_mean", "global_median", "group_median", "category_mean", "category_median",
                  "comparable_median"),
    "condition_rating": ("global_mode", "global_median", "group_mode", "category_mode", "category_median",
                         "comparable_mode"),
    "price_ils": ("global_median_benchmark", "group_median_benchmark", "category_median", "comparable_median"),
}
MEASURED = {"observed", "converted", "corrected", "recovered_source"}
STRONG_PHOTOS = {"exact", "copy", "same item likely", "same item, different view"}
SEED = 5341
LOG_COLUMNS = ("record_id", "attribute", "action", "original_value", "final_value", "evidence",
               "related_record_ids")
CLEAN_COLUMNS = (
    "title_clean", "description_clean", "category_clean", "category_group", "age_years", "age_method",
    "condition_rating", "condition_method", "price_original_amount", "currency_original_code", "price_ils",
    "price_method", "price_currency", "image_links_clean", "image_status_clean", "duplicate_group",
    "quality_flags",
)
# Subtypes keep comparable prices within recognizable products, even when source
# categories combine, for example, computer accessories and complete computers.
SUBTYPES = {
    "car part": r"steering wheel|car floor mats|automotive (?:tool|accessor)|car tools",
    "phone accessory": r"phone (?:case|charger|cover)|(?:charger|case|cover) (?:for |with )?(?:iphone|smartphone)|"
                       r"(?:iphone|smartphone) (?:case|charger|cover)|tempered glass.*iphone",
    "tablet accessory": r"stylus|apple pencil|(?:keyboard|cover|case) (?:for |with )?(?:ipad|tablet)",
    "computer accessory": r"laptop (?:desk|stand|bag|sleeve|charger)|(?:bag|sleeve|stand|charger) for (?:laptop|macbook)",
    "powered scooter": r"electric scooter|inokim|monokim|سكوتر.*(?:فلت|60)",
    "motorcycle": r"motorcycle|motor scooter|hyosung|kawasaki|vespa|motorbike",
    "electric bicycle": r"electric (?:fat.tire |folding )?(?:bicycle|bike)|e.bike",
    "bicycle": r"bicycle|mountain bike|road bike|\bBMX\b|دراجة",
    "luxury sport sedan": r"\b(?:AMG GT|BMW 5|545e|BMW 520i|Mercedes.Benz C250)\b",
    "luxury SUV": r"\b(?:Lexus|Range Rover|Rubicon|Mercedes.Benz GLS|Mercedes.Benz GLA)\b",
    "electric and hybrid car": r"tesla|ioniq|\bhybrid\b|\bniro\b",
    "pool table": r"billiard table|pool table|بلياردو",
    "treadmill": r"treadmill|treadly|running machine",
    "gym machine": r"multi.gym|home gym|workout equipment set|resistance machine|weight bench|strength training machine",
    "weights": r"dumbbell|kettlebell|(?:\bweights\b|\bweight set\b)",
    "light exercise gear": r"\byoga\b|\bpilates\b|jump rope|exercise band|hand gripper",
    "small bag": r"backpack|lunch bag|bookbag|school bag",
    "costume": r"costume|fancy dress|robber clothes|cosplay|dress.up",
    "jewelry box": r"jewel.*box|trinket box",
    "precious jewelry": r"(?:sapphire|diamond|moissanite|emerald|solid gold|platinum|\b\d{2}\s?(?:ct|karat|carat)\b)"
                        r".*(?:jewel|bracelet|\bbangle\b|earrings|necklace|pendant|\bring\b)",
    "bracelet or bangle": r"bracelet|\bbangle\b",
    "earrings": r"earrings?",
    "fashion jewelry": r"jewel|necklace|pendant|\bring\b",
    "prescription-style eyewear": r"eyeglass|spectacles",
    "sunglasses": r"sunglasses",
    "handset": r"iphone|smartphone|galaxy (?:[as]\d|note)|mobile phone|redmi|pixel \d",
    "tablet": r"\bipad\b|surface pro|galaxy tab|\btablet\b",
    "laptop": r"laptop|notebook computer|thinkpad|xps|precision 5530|macbook|dell latitude|asus tuf",
    "keyboard or mouse": r"\b(?:keyboard|keypad|mouse)\b",
    "earphones": r"headphone|earphone|earbud|airpod|headset",
    "camera": r"camera|dslr|powershot|coolpix|camcorder",
    "calculator": r"calculator|casio fx",
    "console": r"playstation|\bps[2345]\b|\bxbox\b|nintendo switch|game console",
    "plush toy": r"\bplush\b|teddy bear|stuffed (?:animal|toy)",
    "ride-on toy": r"ride.on|battery.powered toy car",
    "toy vehicle": r"toy (?:truck|car|bus|vehicle)|miniature (?:car|truck)|dump truck|diecast",
    "collectible book": r"(?:rare|signed|collectible|first.edition).*(?:book|hardcover|paperback|memoir|edition)|"
                        r"(?:book|hardcover|paperback|memoir).*(?:rare|signed|collectible|first.edition)",
    "sacred text": r"^\s*(?:quran\s*[:(]|quran\s+edition|holy quran|al.quran |holy bible)|\bmissal\b|المصحف",
    "religious book": r"qur.?an|al.islam|religious book|حفظ القرآن|رسائل من القرآن",
    "sofa suite": r"sofa set|living.room set|sectional",
    "loveseat": r"loveseat|two.seat|2.seat",
    "sofa": r"sofa|couch|chesterfield",
    "coffee table": r"coffee table",
    "table": r"\btable\b|\bdesk\b",
    "seating": r"\bchair\b|\bstool\b|\brecliner\b|armchair",
    "fragrance": r"parfum|perfume|fragrance|cologne",
    "hair dryer": r"hair dryer",
    "hair appliance": r"hair (?:straightener|curler|clipper)|curling (?:tool|iron)",
    "empty toolbox": r"^\s*(?:used\s+)?tool\s?box\s*$",
    "tool set": r"toolbox|tool set|tool kit|ratchet set|tool box",
    "industrial motor": r"electric motor|motor \d+\s?hp",
    "industrial power": r"\bcompressor\b|inverter welder",
    "range and oven": r"gas oven|gas range|gas stove|gas cooker|stove with oven|kitchen oven",
    "kitchen vessels": r"cooking pot|saucepan|stockpot|frying pan|tea kettle|cookware",
    "serving vessel": r"beverage dispenser|carafe|water jug|drink dispenser|water pitcher",
    "drinkware": r"travel tumbler|\bmug\b",
    "collectible ukulele": r"(?:vintage|kamaka).*ukulele",
    "ukulele": r"ukulele",
    "fretted instrument": r"acoustic guitar|classical guitar|electric guitar",
    "decorative ornament": r"decorative pumpkin|artificial.*(?:tree|flower)|decorative tree|figurine|"
                           r"decorative planter|souvenir|decorative.*ornament",
    "decorative container": r"jewelry box|lidded.*box|metal box|decorative.*box|bread box",
    "wall art": r"calligraphy|wall art|framed (?:print|art|painting)|painting",
}
COMPILED_TYPES = [(label, re.compile(pattern, re.I)) for label, pattern in SUBTYPES.items()]
STOP_WORDS = set(("used new nearly good great very excellent item original brand working set "
                  "condition with and for the this plus inches model unknown visible only from "
                  "gold silver tone colored coloured black white blue and red").split())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keyed_csv(path, key):
    rows, _ = integration.read_csv(path)
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), f"Repeated key in {path.name}.")
    return result



def source_text(raw, column):
    return "" if quality.missing_kind(column, raw) else " ".join(raw.split())


def decimal(value):
    number = Decimal(str(value))
    require(number.is_finite() and number >= 0, "Expected a finite nonnegative numeric value.")
    return number


def ordinal(value):
    return int(decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def currency_fields(record, value, rates):
    amount, kind = value["price"], value["price_kind"]
    if kind == "ambiguous_separator" and record["price_raw"] in review.APPROVED_COMMAS:
        amount, kind = decimal(record["price_raw"].replace(",", "")), "supported_grouping"
    code = value["currency"]
    parsed = amount if kind in {"plain", "supported_grouping", "zero_documented"} else None
    if parsed is None or not code:
        return parsed, code, None, "", kind
    converted = (parsed * rates[code]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    method = "converted" if code != "ILS" else ("corrected" if kind == "supported_grouping" else "observed")
    return parsed, code, converted, method, kind


def log_change(log, key, field, action, original, final, evidence, related=()):
    log.append(dict(zip(LOG_COLUMNS, (key, field, action, original, final, evidence,
                                      audit.json_cell(list(related))))))


def clean_images(records, manifest, images, log):
    by_locator = {tuple(json.loads(photo["locator"])): photo for photo in images.values()}
    expected = {tuple(loc) for row in manifest for loc in json.loads(row["image_file_locators"])}
    require(len(by_locator) == len(images) and by_locator.keys() == expected, "The image inventory does not match selected files.")
    require(all(p["review_status"] == "reviewed" and re.fullmatch("[0-9a-f]{64}", p["sha256"])
                for p in images.values()), "The visual review is incomplete.")
    targets = {p["proposed_record_id"]: p for p in images.values() if p["proposed_record_id"]}
    links, statuses = {}, {}
    used = set()
    for record in records:
        key = record["record_id"]
        original = json.loads(record["image_links"])
        corrected, flags = [], []
        for item in original:
            locator = tuple(item["locator"])
            photo = by_locator[locator]
            require(key in json.loads(photo["record_ids"]), "Visual inventory link disagrees with the raw record.")
            if photo["replacement_locator"]:
                destination = tuple(json.loads(photo["replacement_locator"]))
                target = by_locator[destination]
                require(locator[0] == destination[0] and target["sha256"] == photo["replacement_sha256"]
                        and target["verdict"] == photo["verdict"] == "visually inconsistent",
                        "An image replacement lacks same-attachment and hash evidence.")
                corrected.append(destination)
                flags.append("replaced")
                log_change(log, key, "image_links_clean", "replaced", photo["locator"], target["locator"],
                           f'{photo["evidence"]} Replacement shows {target["observed_type"]}.')
            elif photo["verdict"] == "visually inconsistent":
                flags.append("mismatch_unresolved")
                log_change(log, key, "image_links_clean", "detached_mismatch", photo["locator"], "", photo["evidence"])
            else:
                corrected.append(locator)
                flags.append({"visually consistent": "visually_consistent", "uncertain": "uncertain",
                              "insufficient visual information": "insufficient_visual_information"}[photo["verdict"]])
        if key in targets:
            photo = targets[key]
            locator = tuple(json.loads(photo["locator"]))
            require(not original and photo["verdict"] == "unlinked image" and
                    locator[0] == json.loads(record["source_table"])[0], "The recovered picture conflicts with an original link.")
            corrected.append(locator)
            flags.append("recovered_visual_link")
            log_change(log, key, "image_links_clean", "recovered_visual_link", "", photo["locator"], photo["evidence"])
        require(len(set(corrected)) == len(corrected) and not used.intersection(corrected),
                "A cleaned image locator would be reused.")
        used.update(corrected)
        links[key] = corrected
        statuses[key] = "|".join(sorted(set(flags))) if flags else "missing"
    require(len(targets) == sum(bool(p["proposed_record_id"]) for p in images.values()), "Repeated recovered record image.")
    return links, statuses


def duplicate_groups(records, pairs, links, values, log):
    """Check audit edges on corrected photos before accounting for any exclusion."""
    by_key = {r["record_id"]: r for r in records}
    component = {}
    related = defaultdict(set)
    approved = [p for p in pairs if p["duplicate_decision"] == "propose consolidation"]
    require(all(p["review_status"] == "reviewed" for p in pairs), "Duplicate review is incomplete.")
    for pair in pairs:
        left, right = (json.loads(pair[f"record_ids_{side}"]) for side in ("first", "second"))
        if len(left) == len(right) == 1 and left != right and pair["visual_finding"] in STRONG_PHOTOS:
            related[left[0]].add(right[0])
            related[right[0]].add(left[0])
    for pair in approved:
        a, b = (json.loads(pair[f"record_ids_{side}"])[0] for side in ("first", "second"))
        require(tuple(json.loads(pair["first_locator"])) in links[a]
                and tuple(json.loads(pair["second_locator"])) in links[b],
                "An approved duplicate edge no longer has its reviewed image association.")
        require(pair["visual_finding"] in STRONG_PHOTOS and pair["evidence"], "An approved edge lacks evidence.")
        require(pair["listing_evidence"] != "different saved addresses", "Duplicate edge has contradictory listing evidence.")
        price_a, code_a, *_ = values[a]
        price_b, code_b, *_ = values[b]
        require(price_a is not None and price_a == price_b and code_a and code_a == code_b,
                "Approved duplicate rows disagree on asking price or currency.")
        group = {a, b} | component.get(a, set()) | component.get(b, set())
        component.update({key: group for key in group})
    # A connected group may include several pairs. Validate the full membership and
    # check every reviewed pair for contradictions before accepting transitive joins.
    groups = {}
    for pair in approved:
        keep = pair["representative_record_id"]
        excluded = set(json.loads(pair["proposed_excluded_record_ids"]))
        members = component[keep]
        require({keep} | excluded == members and pair["duplicate_group"],
                "Overlapping duplicate pairs disagree on group membership.")
        require(groups.setdefault(pair["duplicate_group"], (keep, excluded)) == (keep, excluded),
                "Duplicate edges disagree on representative.")
    for pair in pairs:
        combined = set(json.loads(pair["record_ids_first"]) + json.loads(pair["record_ids_second"]))
        if len(combined) != 2:
            continue
        a, b = sorted(combined)
        if b in component.get(a, set()):
            require(pair["visual_finding"] not in {"distinct", "similar", "stock-like", "stock-like reuse"}
                    and pair["listing_evidence"] != "different saved addresses",
                    "A reviewed pair contradicts an approved duplicate group.")
    representatives, drop = {}, set()
    for group, (keep, excluded) in sorted(groups.items()):
        require(keep not in drop and not excluded.intersection(drop | representatives.keys()),
                "Duplicate exclusions overlap unexpectedly.")
        representatives[keep] = group
        drop.update(excluded)
        for key in sorted(excluded):
            evidence = [p["evidence"] for p in approved if p["duplicate_group"] == group
                        and key in json.loads(p["record_ids_first"]) + json.loads(p["record_ids_second"])]
            log_change(log, key, "record_id", "duplicate_exclusion", key, keep, " ".join(evidence), (keep,))
    for key in sorted(related):
        # Expand linked photo variants so validation never memorizes a related item.
        cluster, pending = set(), [key]
        while pending:
            neighbor = pending.pop()
            if neighbor not in cluster:
                cluster.add(neighbor)
                pending.extend(related[neighbor] - cluster)
        related[key] = cluster - {key}
    require(drop <= by_key.keys(), "A duplicate exclusion names an unknown observation.")
    return representatives, drop, related


def build_initial(records, categories, values, images, statuses, representatives, outliers, notes, log,
                  groups):
    result = {}
    valid_methods = {
        "age_years": {"estimated_usage_duration", "estimated_model_year", "estimated_edition_year",
                      "estimated_purchase_year", "estimated_era_midpoint", "recovered_source"},
        "condition_rating": {"estimated_visual_condition", "recovered_source"},
        "description_clean": {"recovered_visual", "recovered_source"},
        "category_clean": {"recovered_visual", "reviewed_unresolved"},
        "price_ils": {"recovered_source", "reviewed_unresolved"},
    }
    for (key, field), note in notes.items():
        require(field in valid_methods and note["method"] in valid_methods[field] and note["evidence"],
                "A local recovery decision has an unsupported method or lacks evidence.")
    year = int(review.SNAPSHOT_DATE[:4])
    for row in records:
        key = row["record_id"]
        source = values[key]
        parsed, currency, price, price_method, price_kind = source["price_fields"]
        age, age_kind, condition = source["age"], source["age_kind"], source["condition"]
        age_method = "corrected" if age_kind in {"months", "years_text"} or (
            age is not None and row["age_raw"].strip().endswith(".")) else ("observed" if age is not None else "")
        if row["age_raw"] == review.APPROVED_AGE_TYPO:
            age, age_method = Decimal("0.25"), "corrected"
        condition_method = ("observed" if source["condition_kind"] == "integer" else "corrected") if condition else ""
        cat = categories[key]
        clean = dict(title_clean=source_text(row["title"], "title") or "Unknown",
                     description_clean=source_text(row["description"], "description") or "Unknown",
                     category_clean=cat["specific_category"], category_group=cat["category_group"],
                     age_years=age if age is not None and age >= 0 else None, age_method=age_method,
                     condition_rating=condition, condition_method=condition_method,
                     price_original_amount=parsed, currency_original_code=currency or "Unknown", price_ils=price,
                     price_method=price_method, price_currency="ILS", image_links_clean=audit.json_cell(images[key]),
                     image_status_clean=statuses[key], duplicate_group=representatives.get(key, ""))
        flags = set()
        if json.loads(row["source_extras"]).get("alignment") == "unquoted_prose_boundary":
            flags.add("unresolved_text_boundary")
        if not currency:
            flags.add("unresolved_original_currency")
            reason = ("Generic dollar label lacks a code." if source["currency_kind"] == "ambiguous_label" else
                      "The selected source provides no currency for this row.")
            log_change(log, key, "currency_original_code", "unresolved_source_currency", row["currency_raw"],
                       "Unknown", reason + " Original amount is retained if parseable.")
        if price_kind == "zero_documented":
            flags.add("documented_free_offer")
        if source["condition_kind"] == "outside_scale":
            flags.add("original_condition_outside_scale")
        for raw in ("age_raw", "price_raw"):
            if (key, raw) in outliers:
                verdict = outliers[key, raw]["verdict"]
                if verdict == "unresolved suspicious value":
                    flags.add(f"{raw.removesuffix('_raw')}_source_review")
        transformations = {
            "age_years": ("age_raw", clean["age_years"], age_method, source["age_evidence"] or "Approved unit interpretation"),
            "condition_rating": ("condition_raw", condition, condition_method, "Assignment 1 five-point rubric"),
            "price_ils": ("price_raw", price, price_method,
                          f"Frozen rate with original currency {currency}. Source price form {price_kind}."),
        }
        for field, (raw, final, method, evidence) in transformations.items():
            if final is not None and method in {"converted", "corrected"}:
                log_change(log, key, field, method, row[raw], final, evidence)
        if price_kind == "supported_grouping":
            log_change(log, key, "price_original_amount", "parsed_grouping", row["price_raw"], parsed,
                       "Exact approved comma form or source-supported thousands formatting.")
        if currency and currency != row["currency_raw"]:
            log_change(log, key, "currency_original_code", "normalized_code", row["currency_raw"], currency,
                       "Explicit currency name, code or symbol.")
        for field in ("age_years", "condition_rating", "description_clean", "category_clean", "price_ils"):
            if note := notes.get((key, field)):
                method, value = note["method"], note["value"]
                require(clean[field] is None or clean[field] == "Unknown", "A recovery would overwrite a usable source value.")
                if field == "age_years":
                    if method.endswith(("_year", "_midpoint")):
                        value = Decimal(year) - decimal(value)
                    else:
                        pieces = value.split("/")
                        value = decimal(pieces[0]) / decimal(pieces[1]) if len(pieces) == 2 else decimal(value)
                    clean["age_method"] = method
                elif field == "condition_rating":
                    value = int(value)
                    clean["condition_method"] = method
                elif field == "category_clean":
                    clean["category_group"] = groups.get(value, cat["category_group"])
                elif field == "price_ils":
                    if method == "reviewed_unresolved":
                        require(not value, "An unresolved price must remain blank.")
                        value, clean["price_method"] = None, "unresolved"
                        flags.add("price_ils_unresolved")
                    else:
                        value, clean["price_method"] = decimal(value), method
                clean[field] = value
                old_field = {"age_years": "age_raw", "condition_rating": "condition_raw", "price_ils": "price_raw",
                             "description_clean": "description", "category_clean": "category"}[field]
                log_change(log, key, field, method, row[old_field], value, note["evidence"])
        if clean["category_clean"] != row["category"] and (key, "category_clean") not in notes:
            log_change(log, key, "category_clean", cat["review_status"], row["category"],
                       clean["category_clean"], cat["evidence"])
        for field, original_field in (("title_clean", "title"), ("description_clean", "description")):
            if clean[field] != row[original_field] and (key, field) not in notes:
                log_change(log, key, field, "text_representation", row[original_field], clean[field],
                           "Collapse whitespace in derived text or label a missing value Unknown.")
        clean["quality_flags"] = flags
        result[key] = {**row, **clean}
    return result


@dataclass(frozen=True)
class ProductFeatures:
    subtype: str
    tokens: set
    parts_only: bool
    unit_size: float | None


def product_features(row, image_types):
    text = quality.text_key(row["title_clean"])
    # Use visible type only when the original title does not already identify it.
    subtype = next((name for name, pattern in COMPILED_TYPES if pattern.search(text)), "")
    if not subtype:
        subtype = next((name for name, pattern in COMPILED_TYPES if pattern.search(image_types)), "")
    if not subtype and row["category_clean"] == "Cars":
        subtype = "other car"
    if row["category_clean"] in {"Phone accessories", "Mobile and tablet accessories"}:
        subtype = "phone accessory"
    tokens = set(re.findall(r"[^\W_]{2,}", text)) - STOP_WORDS
    # A parts-only offer needs a separate price pool from working devices.
    description = quality.text_key(row["description"])
    if subtype in {"fashion jewelry", "bracelet or bangle", "earrings"} and re.search(
            r"\b(?:faux|gold.colou?red|silver.colou?red|gold.tone|silver.tone)\b", text + " " + description
    ) and not re.search(r"\b(?:chanel|cartier|pandora|tiffany|sapphire|diamond|gold plated|sterling silver)\b", text):
        subtype = "costume jewelry"
    parts = bool(re.search(r"\b(?:for parts|not working|non.working|broken|for repair)\b", text + " " + description))
    size = None
    if subtype == "weights":
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*(kg|lbs?)\b", text + " " + description)
        if match:
            size = float(match[1]) * (1 if match[2] == "kg" else .45359237)
    elif subtype == "handset":
        match = re.search(r"\biphone\s*(\d+|xr|xs|x)\b", text)
        if match:
            size = float(match[1]) if match[1].isdigit() else 10
    return ProductFeatures(subtype, tokens, parts, size)


def mode_nearest_middle(values):
    modes = stats.multimode(values)
    median = stats.median(values)
    return min(modes, key=lambda mode: (abs(mode - median), mode))


class Donors:
    def __init__(self, rows, field, features, related):
        self.field, self.features, self.related = field, features, related
        self.rows = sorted(rows, key=lambda row: row["record_id"])
        self.by_category = defaultdict(list)
        self.by_group = defaultdict(list)
        self.by_subtype = defaultdict(list)
        for row in self.rows:
            feature = features[row["record_id"]]
            self.by_category[row["category_clean"]].append(row)
            self.by_group[row["category_group"]].append(row)
            if feature.subtype:
                self.by_subtype[feature.subtype, feature.parts_only if field == "price_ils" else False].append(row)

    def options(self, row):
        key, student = row["record_id"], row["student_id"]
        blocked = self.related[key] | {key}
        feature = self.features[key]
        kind, tokens, parts = feature.subtype, feature.tokens, feature.parts_only
        is_price = self.field == "price_ils"

        def eligible(rows):
            return [r for r in rows if r["student_id"] != student and r["record_id"] not in blocked]

        all_rows = eligible(self.rows)
        category = eligible(self.by_category[row["category_clean"]])
        group = eligible(self.by_group[row["category_group"]])
        if row["category_clean"] == "Unknown":
            category = []
        if row["category_group"] == "Unknown or unresolved":
            group = []
        pool = eligible(self.by_subtype[kind, parts if is_price else False]) if kind else []
        if is_price and kind in {"loveseat", "sacred text"} and len({r["student_id"] for r in pool}) < 2:
            fallback = {"loveseat": "sofa", "sacred text": "religious book"}[kind]
            pool = eligible(self.by_subtype[fallback, parts])
            kind = fallback
        if is_price and feature.unit_size is not None:
            compatible = []
            for donor in pool:
                size = self.features[donor["record_id"]].unit_size
                difference = abs(size - feature.unit_size) if size is not None else math.inf
                if (kind == "handset" and difference <= 2 or kind == "weights" and
                        size and feature.unit_size and max(size, feature.unit_size) / min(size, feature.unit_size) <= 2.5):
                    compatible.append(donor)
            pool = compatible
        category_eligible = [r for r in category if not is_price or self.features[r["record_id"]].parts_only == parts]
        # Broad price categories can mix tiny accessories and major goods. Require
        # same subtype or several strong title matches before using a price pool.
        lexical = []
        lexical_pool = pool if kind else category_eligible
        for candidate in lexical_pool:
            candidate_key = candidate["record_id"]
            other = self.features[candidate_key].tokens
            shared = len(tokens & other)
            score = shared / len(tokens | other) if shared else 0
            if shared >= 2 and score >= .25:
                lexical.append((score, candidate_key, candidate))
        shortlist, students, seen = [], set(), set()
        for score, key, candidate in sorted(lexical, key=lambda entry: (-entry[0], entry[1])):
            if key not in seen and candidate["student_id"] not in students:
                shortlist.append(candidate)
                students.add(candidate["student_id"])
                seen.add(key)
            if len(shortlist) == 7:
                break
        minimum = 2 if is_price and kind in {"toy vehicle", "hair dryer", "loveseat", "range and oven",
                                             "serving vessel", "light exercise gear", "luxury SUV",
                                             "weights", "ukulele", "costume jewelry"} else 3
        if len(shortlist) >= 3:
            comparable, comparable_label = shortlist, "title and product-type neighbors"
        elif len({r["student_id"] for r in pool}) >= minimum:
            comparable, comparable_label = pool, f"same product subtype ({kind})"
        else:
            comparable, comparable_label = [], ""

        def sufficient(items, n):
            return len({r["student_id"] for r in items}) >= n

        options = {}
        for method in METHODS[self.field]:
            basis = method.removesuffix("_benchmark")
            scope, operation = basis.split("_", 1)
            donors = {"global": all_rows, "category": category_eligible, "group": group,
                      "comparable": comparable}[scope]
            if not sufficient(donors, {"global": 1, "category": 4, "group": 6, "comparable": minimum}[scope]):
                continue
            values = [r[self.field] for r in donors]
            aggregate = {"mean": lambda vals: sum(vals) / len(vals), "median": stats.median,
                         "mode": mode_nearest_middle}[operation]
            value = aggregate(values)
            if self.field == "condition_rating":
                value = ordinal(value)
            else:
                value = decimal(value).quantize(Decimal("0.01") if is_price else Decimal("0.001"),
                                                rounding=ROUND_HALF_UP)
            options[method] = (value, donors, comparable_label if scope == "comparable" else scope)
        return options


def training_pool(rows, field):
    method = METHOD_FIELDS[field]
    suspect = {"age_years": "age_source_review", "price_ils": "price_source_review"}.get(field)
    return [row for row in rows if row[method] in MEASURED and row[field] is not None
            and (field != "price_ils" or row[field] > 0) and suspect not in row["quality_flags"]]


def evaluate(rows, features, related):
    """Mask each observed value once in a reproducible five-fold student split."""
    students = sorted({row["student_id"] for row in rows})
    random.Random(SEED).shuffle(students)
    folds = {student: index % 5 for index, student in enumerate(students)}
    results = {}
    for field in FIELDS:
        measured = training_pool(rows, field)
        errors = {m: {} for m in METHODS[field]}
        by_fold = defaultdict(list)
        for row in measured:
            by_fold[folds[row["student_id"]]].append(row)
        for fold, test in sorted(by_fold.items()):
            pool = Donors([r for r in measured if folds[r["student_id"]] != fold], field, features, related)
            for row in test:
                truth = float(row[field])
                for method, (value, _, _) in pool.options(row).items():
                    prediction = float(value)
                    errors[method][row["record_id"]] = (abs(prediction - truth),
                                                         abs(math.log1p(prediction) - math.log1p(truth)),
                                                         prediction - truth)
        common = set.intersection(*(set(values) for values in errors.values()))
        results[field] = []
        for method, predictions in errors.items():
            values = [predictions[key] for key in sorted(common)]
            require(values, f"No shared cross-validation cases for {field}.")
            results[field].append(dict(method=method, n=len(predictions), eligible=len(measured), common=len(values),
                                       mae=stats.mean(v[0] for v in values), log_mae=stats.mean(v[1] for v in values),
                                       bias=stats.mean(v[2] for v in values),
                                       exact=stats.mean(v[0] == 0 for v in values)))
    return results


PRICE_CATEGORY_FALLBACK = {
    "Books", "Science textbooks", "Rugs", "Lighting", "Clocks", "Laptops", "Mobile phones",
    "Smartphone", "Jewelry", "Watches", "Phone accessories", "Game consoles", "Refrigerators",
    "Microwave ovens", "Acoustic guitars", "Electric bicycles", "Electric scooters", "Racket sports equipment",
    "Sofas and seating", "Dining tables and chair sets", "Footwear", "Fragrance", "Watches and jewelry",
}


def fill_missing(rows, features, related, evaluation, log):
    selections = {}
    for field in FIELDS:
        method_field = METHOD_FIELDS[field]
        metrics = evaluation[field]
        best = min(metrics, key=lambda r: (r["log_mae"] if field == "price_ils" else r["mae"],
                                           -r["exact"], abs(r["bias"])))
        # Age and condition can use a global fallback. Price must stay in a meaningful
        # cohort, even when a broad benchmark benefits from common low prices.
        if field == "price_ils":
            priority = ["comparable_median", "category_median"]
        else:
            priority = [best["method"]]
            for m in ("category_median", "group_median", "global_median") if field == "age_years" else (
                    "category_mode", "group_mode", "global_mode"):
                if m not in priority:
                    priority.append(m)
        selections[field] = priority
        pool = Donors(training_pool(rows, field), field, features, related)
        for row in rows:
            if row[field] is not None or row[method_field] == "unresolved":
                continue
            options = pool.options(row)
            key = row["record_id"]
            for method in priority:
                if method not in options:
                    continue
                if field == "price_ils" and method == "category_median" and (
                        row["category_clean"] not in PRICE_CATEGORY_FALLBACK or
                        features[key].subtype in {"collectible book", "sacred text"} or features[key].parts_only):
                    continue
                value, donors, basis = options[method]
                row[field] = value
                row[method_field] = "imputed_" + method
                observed = [r[field] for r in donors]
                spread = (min(observed), max(observed))
                evidence = (f"{basis}. {len(donors)} eligible source-valued donors from "
                            f"{len({r['student_id'] for r in donors})} other students. "
                            f"Donor value range {spread[0]} to {spread[1]}.")
                related_ids = [r["record_id"] for r in donors] if method.startswith("comparable_") else []
                log_change(log, key, field, row[method_field], row[SOURCE_NUMERICS[field]], value, evidence,
                           related_ids)
                break
            if row[field] is None:
                row[method_field] = "unresolved"
                row["quality_flags"].add(f"{field}_unresolved")
                log_change(log, key, field, "unresolved", row[SOURCE_NUMERICS[field]], "",
                           "No sufficiently comparable donor pool or verified source value.")
    return selections


def diagnostics(rows):
    """Post-cleaning IQR and observed/completed diagnostics for Phase 3 validation."""
    summaries, tails, relations = [], [], []
    for field, method in METHOD_FIELDS.items():
        for label in ("source-valued", "completed"):
            values = [float(r[field]) for r in rows
                      if r[field] is not None and (label == "completed" or r[method] in MEASURED)]
            require(len(values) > 1, "Insufficient values for Phase 3 sensitivity checks.")
            summaries.append((field, label, len(values), stats.mean(values), stats.median(values), stats.stdev(values)))
            if field != "condition_rating":
                q1, _, q3 = stats.quantiles(values, n=4, method="inclusive")
                lower, upper = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
                tails.append((field, label, len(values), q1, q3, lower, upper,
                              sum(v < lower for v in values), sum(v > upper for v in values)))
                if label == "completed":
                    for row in rows:
                        if row[field] is not None and not lower <= float(row[field]) <= upper:
                            row["quality_flags"].add(f"{'price' if field == 'price_ils' else 'age'}_iqr_candidate")
    for field in ("age_years", "condition_rating"):
        for label in ("source-valued", "completed"):
            pairs = [(float(r[field]), float(r["price_ils"])) for r in rows
                     if r[field] is not None and r["price_ils"] is not None and
                     (label == "completed" or r[METHOD_FIELDS[field]] in MEASURED and r["price_method"] in MEASURED)]
            a, b = zip(*pairs)
            rho = pd.Series(a).rank().corr(pd.Series(b).rank())
            relations.append((field, label, len(pairs), stats.correlation(a, b), rho))
    return summaries, tails, relations



def summary(records, rows, evidence_only, drops, log, validation, digest, clean_digest, attachments, choices, sensitivity):
    n, n_clean = len(records), len(rows)
    raw_missing = Counter({field: sum(bool(quality.missing_kind(field, r[field])) for r in records)
                           for field in quality.ANALYTICAL + ("image_links",)})
    table_fields = (
        ("Title", "title", "title_clean"), ("Description", "description", "description_clean"),
        ("Category", "category", "category_clean"), ("Age", "age_raw", "age_years"),
        ("Condition", "condition_raw", "condition_rating"), ("Price", "price_raw", "price_ils"),
        ("Currency of original amount", "currency_raw", "currency_original_code"),
        ("Image association", "image_links", "image_links_clean"),
    )

    def missing(row, name):
        return row[name] in (None, "", "Unknown", "[]")

    def fraction(count, total):
        return f"{count:,} ({100 * count / total:.2f}%)"

    old_union = sum(any(quality.missing_kind(k, r[k]) for k in quality.ANALYTICAL) for r in records)
    blank_union = sum(any(not r[k].strip() for k in quality.ANALYTICAL) for r in records)
    blank_numerics = sum(any(not r[k].strip() for k in ("age_raw", "condition_raw", "price_raw")) for r in records)
    numeric_union = sum(any(quality.missing_kind(k, r[k]) for k in ("age_raw", "condition_raw", "price_raw"))
                        for r in records)
    final_core = ("title_clean", "description_clean", "category_clean", *FIELDS)
    final_union = sum(any(missing(r, name) for name in final_core) for r in rows)
    related = Counter((item["attribute"], item["action"]) for item in log)
    fx_rows = sum(r["price_method"] == "converted" for r in rows)
    incomplete_price = [r for r in rows if r["price_ils"] is None]
    foreign = Counter(r["currency_original_code"] for r in rows if r["price_method"] == "converted")
    image_events = {a: related["image_links_clean", a] for a in ("replaced", "recovered_visual_link", "detached_mismatch")}
    outlier_flags = Counter(flag for row in rows for flag in row["quality_flags"]
                            if flag.endswith(("source_review", "iqr_candidate")))
    title = [
        "# Phase 3 cleaning and preprocessing", "",
        "## Reconciliation", "",
        f"- Raw data contains {n:,} observations from {len({r['student_id'] for r in records})} students. "
        f"The cleaned CSV contains {n_clean:,} observations from {len({r['student_id'] for r in rows})} students "
        f"and {len(integration.COLUMNS) + len(CLEAN_COLUMNS)} columns.",
        f"- Excluded {len(drops)} observations in {sum(bool(r['duplicate_group']) for r in rows)} reviewed groups. "
        "The corrected photo links support every consolidation edge. There were no conflicting reviewed pairs or asking prices "
        "within those groups. Retained representatives use the documented listing, field-completeness and source-alignment evidence. "
        "Conflicting subjective grades or ages remain in the raw source. The cleaning log maps every exclusion to its retained row.",
        f"- Reconciled the raw file hash before and after execution and compared {attachments} original attachment files "
        f"against the frozen export. Raw SHA-256 is `{digest}`.",
        f"- Cleaned CSV SHA-256 is `{clean_digest}`.",
        f"- Raw exact nonblank category labels total {len({r['category'] for r in records if r['category'].strip()})}. "
        f"The cleaned data has {len({r['category_clean'] for r in rows})} specific labels and "
        f"{len({r['category_group'] for r in rows})} broader groups, including Unknown where evidence remains insufficient.",
        "", "## Missingness and evidence", "",
        "Raw missingness includes blanks, whitespace and explicit placeholders. Before-imputation counts use the retained rows "
        "after supported source work. The original currency row counts ambiguous codes as unresolved after source review.",
        "", "| Attribute | Raw missing | Retained before imputation | Cleaned missing |",
        "|---|---:|---:|---:|",
    ]
    for label, raw, clean in table_fields:
        old_n = raw_missing[raw]
        before_n = sum(missing(r, clean) for r in evidence_only)
        clean_n = sum(missing(r, clean) for r in rows)
        title.append(f"| {label} | {fraction(old_n, n)} | {fraction(before_n, n_clean)} | {fraction(clean_n, n_clean)} |")
    title.extend([
        "",
        f"The independent union calculation gives **{fraction(old_union, n)}** with at least one missing analytical "
        f"source field. Counting only blank or whitespace fields gives {fraction(blank_union, n)}. Restricting that "
        f"definition to age, condition and price gives {fraction(blank_numerics, n)} and including their placeholders "
        f"gives {fraction(numeric_union, n)}. Those definitions can explain part of the reported difference. "
        f"The classmates' exact rule and dataset are unavailable. After cleaning the core-field union is {fraction(final_union, n_clean)}.",
        "",
        "| Analytical field | Value origin | Records |", "|---|---|---:|",
    ])
    for field, method in METHOD_FIELDS.items():
        for name, count in sorted(Counter(r[method] for r in rows).items()):
            title.append(f"| {field} | {name} | {count:,} |")
    title.extend([
        "",
        "The age recovery review used all missing rows. Explicit model, edition, era, purchase and usage evidence "
        "produces approximate ages with separate method labels. Photographs corroborate item types and model details. "
        "Condition estimates use the Assignment 1 rubric and visible wear where it is sufficiently informative. "
        "The rating of 9 is preserved in raw data. The source description supports a cleaned rating of 5.",
        f"Local judgments supplied {related['description_clean', 'recovered_visual']} missing descriptions. "
        "Descriptions contain supported visible details and previously recorded facts. The log records reasons and any "
        "limits on those inferences. The 12 unresolved title/description boundaries keep their original source fragments.",
        "", "## Currency and photos", "",
        f"- Applied the frozen {review.SNAPSHOT_DATE} snapshot to {fx_rows:,} retained foreign-currency prices. "
        "Counts by original code are " + quality.display_counts(foreign) + ". The ILS identity and Decimal cross-rates "
        "were verified. Currency values are current-rate equivalents and source amounts are preserved.",
        "- Dollar labels and absent currency columns were checked against table headers, descriptions, original values and "
        "the provided photo evidence. No missing code was identified with sufficient certainty. The original amount is "
        "kept when available and a defensible price estimate is recorded separately in ILS.",
        f"- {len(incomplete_price)} analytical prices remain blank. Examples include specialty items with no comparable "
        "model, an ambiguous premium vehicle price, and a parts-only phone outside the comparable generation range. "
        f"{sum(r['currency_original_code'] == 'Unknown' and r['price_method'].startswith('imputed_') for r in rows)} "
        "records with unresolved original currency have a separate ILS estimate.",
        f"- Across the full source, applied {image_events['replaced']} within-attachment replacements and "
        f"{image_events['recovered_visual_link']} bread-box link. Detached {image_events['detached_mismatch']} "
        "visually inconsistent associations without a supported replacement. Their original links remain traceable. "
        "Plausibility and limited visual evidence remain explicit. Multiple legitimate views are retained.",
        "- Retained image-record statuses are "
        + quality.display_counts(Counter(r["image_status_clean"] for r in rows)) + ".",
        "- Unresolved source age and price flags carried into the cleaned data are "
        + quality.display_counts({key: value for key, value in outlier_flags.items() if key.endswith("source_review")})
        + ". Price and age were not capped, smoothed or deleted based on IQR.",
        "", "## Imputation validation", "",
        f"Each usable source-valued target was masked in a five-fold split by student, seed {SEED}. "
        "Donors were other students, excluding photo-linked relatives, inferred values, suspicious numeric values, "
        "and the free offer for price estimation. Comparable methods use matching product subtype and title/model similarity. "
        "Parts-only offers use separate price pools. Donors can be filtered by observable product generation or size. "
        "Narrow, explicitly listed product types can use two independent donors when the product match is clear. "
        "Age and condition outcomes were excluded as price predictors to protect "
        "the required relationship analyses. Thin or heterogeneous price groups can remain missing. Results on real missing "
        "targets can differ because the missingness mechanism is unknown.",
        "", "| Field | Method | Test coverage | Common n | MAE | Log1p MAE | Signed bias | Exact agreement |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])
    for field, items in validation.items():
        for m in items:
            title.append(f"| {field} | {m['method']} | {m['n']}/{m['eligible']} | {m['common']} | "
                         f"{m['mae']:.3f} | {m['log_mae']:.3f} | {m['bias']:.3f} | {100*m['exact']:.1f}% |")
    title.extend([
        "", "Applied priorities by field are " + ", ".join(f"{field} ({' → '.join(methods)})" for field, methods in choices.items()) + ".",
        "For price, log1p error captures relative scale in skewed cohorts. A lower overall benchmark error does not "
        "make a mixed-product pool appropriate for a rare book or commercial motor. The price method and donor range "
        "are documented per row.", "", "## Statistical sensitivity and post-cleaning IQR", "",
        "| Attribute | Cohort | n | Mean | Median | Sample SD |", "|---|---|---:|---:|---:|---:|",
    ])
    summaries, tails, relations = sensitivity
    for field, label, size, mean, med, spread in summaries:
        title.append(f"| {field} | {label} | {size:,} | {mean:.3f} | {med:.3f} | {spread:.3f} |")
    title.extend(["", "| Attribute | Cohort | n | Q1 | Q3 | Q1 − 1.5 IQR | Q3 + 1.5 IQR | Lower | Upper |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---:|"])
    for field, label, size, q1, q3, lower, upper, lo, hi in tails:
        title.append(f"| {field} | {label} | {size:,} | {q1:.3f} | {q3:.3f} | {lower:.3f} | {upper:.3f} | {lo} | {hi} |")
    title.extend(["", "| Relationship | Cohort | n | Pearson r | Spearman rho |", "|---|---|---:|---:|---:|"])
    for field, label, size, pearson, rho in relations:
        title.append(f"| {field} and price | {label} | {size:,} | {pearson:.4f} | {rho:.4f} |")
    condition_source = Counter(r["condition_rating"] for r in rows if r["condition_method"] in MEASURED)
    condition_final = Counter(r["condition_rating"] for r in rows)
    title.extend([
        "", "| Condition rating | Source-valued | Completed |", "|---|---:|---:|",
        *(f"| {value} | {condition_source[value]:,} | {condition_final[value]:,} |" for value in range(1, 6)),
        "", "For observed-only analysis, select methods `observed`, `corrected`, `converted` and `recovered_source` "
        "for each attribute involved in the analysis. Estimate and imputation methods remain individually identifiable. "
        "Later work should compare important findings across these cohorts and report sample sizes.",
        "", "Assignment 1 §§2, 4, 5, and 7 establish the approximate years, currency, rating and image rules. "
        "Assignment 2 §3 requires documented handling of data quality issues and §4 motivates preserving associations for "
        "analysis. Lecture slides 20–22 guide recovery and imputation, slides 23–24 and 69–70 guide IQR investigation, "
        "and slide 26 supports resolving value conflicts and redundant observations.",
        "", "## Readiness", "",
        "The cleaned CSV and cleaning log reconcile every original observation. Sensitive row-level findings and review "
        "inputs stay in the course workspace. The observed-only and completed cohorts are available for Phase 4 after review.",
        "",
    ])
    return "\n".join(title)


def verify_export(data, records, rows, dropped, log, rates):
    exported = list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))
    source = {r["record_id"]: r for r in records}
    cleaned_ids = {r["record_id"] for r in exported}
    require(len(exported) == len(cleaned_ids) == len(rows)
            and cleaned_ids.isdisjoint(dropped) and cleaned_ids | dropped == source.keys(),
            "Exported record IDs and duplicate exclusions do not reconcile.")
    require({r["record_id"] for r in log if r["action"] == "duplicate_exclusion"} == dropped,
            "Every excluded observation needs a decision entry.")
    require(tuple(exported[0]) == integration.COLUMNS + CLEAN_COLUMNS, "Unexpected CSV schema.")
    require({r["student_id"] for r in exported} == {r["student_id"] for r in records}, "A student was lost.")
    logs = {(r["record_id"], r["attribute"], r["action"]) for r in log}
    for row in exported:
        key = row["record_id"]
        require(all(row[field] == source[key][field] for field in integration.COLUMNS),
                "An original value changed during export.")
        decimal(row["age_years"])
        require(row["condition_rating"] in {"1", "2", "3", "4", "5"}, "Invalid exported condition.")
        require(row["price_currency"] == "ILS", "Unstandardized analytical price currency.")
        if row["price_ils"]:
            final = decimal(row["price_ils"])
            if row["price_method"] in {"converted", "corrected", "observed"}:
                expected = decimal(row["price_original_amount"]) * rates[row["currency_original_code"]]
                require(final == expected.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                        "Currency conversion differs from frozen rates.")
        else:
            require(row["price_method"] == "unresolved", "Missing analytical price is unexplained.")
        if source[key]["age_raw"] == review.APPROVED_AGE_TYPO:
            require(decimal(row["age_years"]) == Decimal("0.25"), "Approved age typo did not produce 0.25 years.")
        if source[key]["price_raw"] in review.APPROVED_COMMAS:
            require(decimal(row["price_original_amount"]) == decimal(source[key]["price_raw"].replace(",", "")),
                    "An approved thousands grouping differs in the export.")
        for field, method in METHOD_FIELDS.items():
            logged = (key, field, row[method]) in logs or (
                row[method] == "unresolved" and (key, field, "reviewed_unresolved") in logs)
            require(row[method] and (row[method] in MEASURED or logged),
                    "An estimated value lacks a traceable decision.")


def run(root):
    root = root.resolve()
    raw_path, digest, frame, manifest, selected = quality.load_baseline(root)
    attachment_count = integration.verify_originals(root, manifest)
    records = frame.to_dict("records")
    raw_csv, _ = integration.read_csv(raw_path)
    independent_missing = sum(any(row[field].strip().casefold() in quality.PLACEHOLDERS | {""}
                                  for field in quality.ANALYTICAL) for row in raw_csv)
    require(independent_missing == sum(any(quality.missing_kind(field, row[field]) for field in quality.ANALYTICAL)
                                       for row in records), "Independent raw missingness calculation differs.")
    local_audit = root / "Audit"
    categories = keyed_csv(local_audit / "pre_cleaning_category_review.csv", "record_id")
    images = keyed_csv(local_audit / "pre_cleaning_visual_review.csv", "image_id")
    pairs = integration.read_csv(local_audit / "pre_cleaning_duplicate_review.csv")[0]
    outliers = review.load_judgments(local_audit / "pre_cleaning_outlier_review.csv", ("record_id", "attribute"))
    note_file = root / "Working" / "PreCleaning" / "phase3_source_judgments.csv"
    require(note_file.is_file(), "Obtain the authorized Phase 3 source judgments before producing the reviewed dataset.")
    notes = review.load_judgments(note_file, ("record_id", "attribute"))
    keys = {r["record_id"] for r in records}
    require(keys == categories.keys() and all(categories[r["record_id"]]["raw_category"] == r["category"]
                                               for r in records), "The category review differs from the raw records.")
    source_by_id = {r["record_id"]: r for r in records}
    require(all(k in keys for k, _ in notes), "A source decision names an unknown record.")
    require(all(row["review_status"] == "individually reviewed" and row["original_value"] == source_by_id[key][field]
                for (key, field), row in outliers.items()) and outliers, "Outlier evidence is incomplete or stale.")
    values, _, _ = quality.value_assessment(records, selected, quality.category_mapping(records), [])
    fx = integration.read_csv(local_audit / "pre_cleaning_exchange_rates.csv")[0]
    require(fx == review.rates({v["currency"] for v in values.values() if v["currency"]}),
            "Exchange-rate reference differs from the approved snapshot.")
    review.rate_check(fx)
    rates = {r["currency_code"]: decimal(r["ils_per_unit"]) for r in fx}
    price_values = {r["record_id"]: currency_fields(r, values[r["record_id"]], rates) for r in records}
    for key, price in price_values.items():
        values[key]["price_fields"] = price
    require(Counter(r["price_raw"] for r in records if r["price_raw"] in review.APPROVED_COMMAS
                    and price_values[r["record_id"]][4] == "supported_grouping") ==
            Counter(review.APPROVED_COMMAS), "An approved price interpretation was lost or repeated.")
    log = []
    linked, statuses = clean_images(records, selected, images, log)
    representatives, dropped, related = duplicate_groups(records, pairs, linked, price_values, log)
    group_by_category = {row["specific_category"]: row["category_group"] for row in categories.values()}
    group_by_category["Cargo carts"] = "Transport"
    clean = build_initial(records, categories, values, linked, statuses, representatives,
                          outliers, notes, log, group_by_category)
    retained = [r for key, r in clean.items() if key not in dropped]
    types = {tuple(json.loads(p["locator"])): p["observed_type"] for p in images.values()}
    features = {key: product_features(r, " ".join(types[loc] for loc in linked[key])) for key, r in clean.items()}
    evidence_only = [row.copy() for row in retained]
    validation = evaluate(retained, features, related)
    choices = fill_missing(retained, features, related, validation, log)
    sensitivity = diagnostics(retained)
    export_rows = [{**row, "quality_flags": audit.json_cell(sorted(row["quality_flags"]))} for row in retained]
    data = quality.csv_output(export_rows, integration.COLUMNS + CLEAN_COLUMNS)
    report = summary(records, retained, evidence_only, dropped, log, validation, digest,
                     hashlib.sha256(data).hexdigest(), attachment_count, choices, sensitivity)
    verify_export(data, records, retained, dropped, log, rates)
    require(audit.digest_file(raw_path).hex() == digest
            and integration.verify_originals(root, manifest) == attachment_count,
            "The raw data or original submissions changed during cleaning.")
    integration.write_output(root / "marketplace_cleaned.csv", data)
    integration.write_output(local_audit / "phase3_cleaning_log.csv", quality.csv_output(log, LOG_COLUMNS))
    integration.write_output(local_audit / "phase3_summary.md", report.encode("utf-8"))
    print(f"{len(retained):,} cleaned rows. {len(dropped)} duplicate exclusions. Verified {attachment_count} original attachments.")
    print("Unresolved analytical prices:", sum(r["price_ils"] is None for r in retained))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Course data root containing the raw CSV, Audit and Working folders.")
    run(parser.parse_args().root)


if __name__ == "__main__":
    main()

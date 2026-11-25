"""Generate independent Phase 3 duplicate candidates and private review previews."""
import argparse
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

import phase1_integration as integration
import phase2_quality_assessment as quality
import phase3_cleaning as cleaning
import pre_cleaning_verification as review


WINDOWS = ((0, 0, 1, 1), (.1, .1, .9, .9), (.2, .2, .8, .8),
           (0, 0, .75, .75), (.25, 0, 1, .75), (0, .25, .75, 1), (.25, .25, 1, 1))
DCT = np.cos(np.pi * np.arange(8)[:, None] * (np.arange(32) + .5) / 32)
BIT_COUNT = np.array([v.bit_count() for v in range(256)], dtype=np.uint8)
STOP_WORDS = cleaning.STOP_WORDS | {"this", "very", "pre", "owned", "available", "used", "excellent", "good"}
CANDIDATE_COLUMNS = ("first", "second", "first_image", "second_image", "first_sha256", "second_sha256", "detection")


def signatures(data):
    with Image.open(io.BytesIO(data)) as original:
        photo = ImageOps.exif_transpose(original).convert("RGB")
        photo.thumbnail((450, 450), Image.Resampling.LANCZOS)
        width, height = photo.size
        hashes, colors = [], []
        for left, top, right, bottom in WINDOWS:
            crop = photo.crop((int(left*width), int(top*height), int(right*width), int(bottom*height)))
            gray = np.asarray(crop.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=float)
            low = (DCT @ gray @ DCT.T).ravel()[1:]
            hashes.append(np.packbits(low > np.median(low)))
            colors.append(np.asarray(crop.resize((1, 1), Image.Resampling.BOX), dtype=np.int16).ravel())
        thumb = io.BytesIO()
        photo.save(thumb, format="JPEG", quality=92)
        return np.array(hashes), np.array(colors), thumb.getvalue()


def photo_candidates(images, hashes, colors, digest):
    candidates = defaultdict(set)
    for i, first in enumerate(images):
        scores = BIT_COUNT[np.bitwise_xor(hashes[i, :, None, :], hashes[i + 1:, None, :, :])].sum(axis=-1)
        differences = np.abs(colors[i, :, None, :] - colors[i + 1:, None, :, :]).sum(axis=-1)
        # Full images, crop-to-full, and patch-to-patch use increasingly strict cutoffs.
        limits = np.full((len(WINDOWS), len(WINDOWS)), 5)
        limits[0, :] = limits[:, 0] = 7
        limits[0, 0] = 10
        qualifying = (scores <= limits) & (differences <= 86)
        for j in np.flatnonzero(qualifying.any(axis=(1, 2))):
            second = images[i + 1 + j]
            distance = int(scores[j][qualifying[j]].min())
            kind = "full DCT" if qualifying[j, 0, 0] else "crop DCT"
            candidates[first, second].add(f"{kind} ({distance})")
    by_digest = defaultdict(list)
    for image in images:
        by_digest[digest[image]].append(image)
    for group in by_digest.values():
        for pair in combinations(group, 2):
            candidates[pair].add("exact SHA-256")
    return candidates


def match_text(records):
    """Qualify text candidates without gates on price, category, currency, or student."""
    by_word, by_title, by_listing = defaultdict(list), defaultdict(list), defaultdict(list)
    counters, titles = {}, {}
    for row in records:
        key = row["record_id"]
        title, description = (quality.text_key(row[field]) for field in ("title", "description"))
        titles[key] = title
        words = re.findall(r"[^\W_]{2,}", title + " " + description)
        counters[key] = Counter(word for word in words if word not in STOP_WORDS)
        if len(title) >= 12 and len(title.split()) >= 2:
            by_title[title].append(key)
        if url := quality.recorded_listing(row)[0]:
            by_listing[url].append(key)
        for word in counters[key]:
            by_word[word].append(key)
    results = defaultdict(set)
    for group, label in ((by_title, "normalized title"), (by_listing, "same saved listing")):
        for rows in group.values():
            for first, second in combinations(rows, 2):
                results[tuple(sorted((first, second)))].add(label)
    weights = {word: math.log1p(len(records) / len(keys)) for word, keys in by_word.items()}
    rare_pairs = Counter()
    for word, keys in by_word.items():
        if 2 <= len(keys) <= 55:
            rare_pairs.update(tuple(sorted(pair)) for pair in combinations(keys, 2))
    for (first, second), shared in rare_pairs.items():
        if shared < 3:
            continue
        a, b = set(counters[first]), set(counters[second])
        score = math.fsum(weights[word] for word in a & b) / math.fsum(weights[word] for word in a | b)
        title_score = SequenceMatcher(None, titles[first], titles[second], autojunk=False).ratio()
        if score >= .56 or (shared >= 4 and score >= .31 and title_score >= .72) or (
                shared >= 3 and score >= .24 and title_score >= .82):
            results[first, second].add(f"rare token overlap ({score:.3f})")
    return results


def run(root, gallery=False):
    root = root.resolve()
    _, _, frame, _, selected = quality.load_baseline(root)
    records = frame.to_dict("records")
    by_record = {r["record_id"]: r for r in records}
    audit_dir = root / "Audit"
    image_rows = cleaning.keyed_csv(audit_dir / "pre_cleaning_visual_review.csv", "image_id")
    links, _ = cleaning.clean_images(records, selected, image_rows, [])
    by_locator = {tuple(json.loads(row["locator"])): key for key, row in image_rows.items()}
    owner = {by_locator[loc]: key for key, locators in links.items() for loc in locators}
    payloads = {}
    for submission in selected:
        locators = [tuple(loc) for loc in json.loads(submission["image_file_locators"])]
        for locator, data in integration.read_selected_files(
                root, json.loads(submission["original_submission_paths"]), locators).items():
            key = by_locator[locator]
            if hashlib.sha256(data).hexdigest() != image_rows[key]["sha256"]:
                raise ValueError("An image differs from the verified visual inventory.")
            payloads[key] = signatures(data)
    images = sorted(payloads)
    hashes, colors, _ = zip(*(payloads[key] for key in images))
    photo_hits = photo_candidates(images, np.array(hashes), np.array(colors),
                                  {key: row["sha256"] for key, row in image_rows.items()})
    text_hits = match_text(records)
    old_pairs = integration.read_csv(audit_dir / "pre_cleaning_duplicate_review.csv")[0]
    old_records = {frozenset(json.loads(row["record_ids_first"]) + json.loads(row["record_ids_second"]))
                   for row in old_pairs}
    pairs = defaultdict(set)
    choices = {}
    for (first, second), evidence in photo_hits.items():
        a, b = owner.get(first), owner.get(second)
        if a and b and a != b:
            key = tuple(sorted((a, b)))
            pairs[key].update(evidence)
            choices.setdefault(key, (first, second) if (a, b) == key else (second, first))
    for key, evidence in text_hits.items():
        pairs[key].update(evidence)
        choices.setdefault(key, tuple(by_locator[links[record][0]] if links[record] else "" for record in key))
    candidates = []
    for (first, second), evidence in sorted(pairs.items()):
        if frozenset((first, second)) in old_records:
            continue
        a, b = choices[first, second]
        candidates.append(dict(first=first, second=second, first_image=a, second_image=b,
                               first_sha256=image_rows[a]["sha256"] if a else "",
                               second_sha256=image_rows[b]["sha256"] if b else "",
                               detection="; ".join(sorted(evidence))))
    candidates.sort(key=lambda r: (not any(kind in r["detection"] for kind in ("exact", "DCT")),
                                   r["first"], r["second"]))
    folder = root / "Working" / "PreCleaning" / "Phase3DuplicateReview"
    folder.mkdir(parents=True, exist_ok=True)
    integration.write_output(folder / "candidates.csv", quality.csv_output(candidates, CANDIDATE_COLUMNS))
    if gallery:
        for start in range(0, len(candidates), 5):
            cards = []
            for n, pair in enumerate(candidates[start:start + 5], start + 1):
                for side in ("first", "second"):
                    key, image = pair[side], pair[side + "_image"]
                    row = by_record[key]
                    title = " ".join(row["title"].split())
                    amount = f'{row["price_raw"]} {row["currency_raw"]}'.strip()
                    caption = f"{n:03d}{side[0]} · {image or 'no supported photo'} · {amount}"
                    if image:
                        picture = payloads[image][2]
                    else:
                        empty = io.BytesIO()
                        Image.new("RGB", (100, 100), "white").save(empty, format="JPEG")
                        picture = empty.getvalue()
                    cards.append((caption, title, picture))
            review.sheet(folder / f"pairs_{start // 5 + 1:02d}.jpg", cards, 2, (460, 260))
    print(f"{len(records)} records, {len(images)} photographs, {len(photo_hits)} photo pairs, "
          f"{len(text_hits)} text pairs. {len(candidates)} previously unreviewed record pairs.")
    return candidates


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--contact-sheets", action="store_true")
    args = parser.parse_args()
    run(args.root, args.contact_sheets)

#!/usr/bin/env python3
"""
generate_pantry_log.py — Project Pantry Audit synthetic log generator.

Builds a deliberately messy data/raw/warehouse_scan_log.csv FROM a real list
of product barcodes (pulled live by the student from the Open Food Facts
API's `code` field), instead of shipping a static pre-made file. Because the
log is generated from whatever barcodes the student actually pulled, a real
join will always have real matches — but three flaws are injected on every
run so a naive 1:1 join still fails:

    1. Dropped ids  (~10% of the input barcodes are simply missing from the
                      log, simulating scan-gun/sync downtime)
    2. Ghost ids    (~10% extra, fabricated barcodes appear in the log that
                      were never in the input, simulating unrelated scans)
    3. Dirty values (shelf_location's own choice list includes a whitespace-
                      padded entry; units_sold_last_month occasionally comes
                      back blank, whitespace-padded, "0", "null", or comma-
                      formatted like "1,200")

IMPORTANT: barcodes are written and compared as plain strings throughout this
script, never cast through int(). Real barcodes can carry meaningful leading
zeroes (e.g. "0180411000803"); casting to int silently destroys them and
breaks the join. Warn students of the same if they "clean" this column later.

Usage (terminal):
    python generate_pantry_log.py --input-ids extracted_ids.txt
    python generate_pantry_log.py --input-ids extracted_ids.txt --output data/raw/warehouse_scan_log.csv --seed 7
    python generate_pantry_log.py                       # no file yet -> runs a built-in smoke test

Usage (notebook / direct import):
    from generate_pantry_log import generate_pantry_log
    generate_pantry_log(my_barcode_list)
"""

import argparse
import csv
import random
from pathlib import Path

DEFAULT_OUTPUT = Path("data/raw/warehouse_scan_log.csv")
FIELDNAMES = ["barcode", "shelf_location", "units_sold_last_month"]

SHELF_LOCATIONS = ["Aisle 1A", "Aisle 2B", "Aisle 4B", "Endcap-South", " Aisle 3C"]

DROP_RATE = 0.10
GHOST_RATE = 0.10
DIRTY_RATE = 0.15

# Real / plausible EAN-13 barcodes so the script produces a genuine-looking
# file even with zero setup.
FALLBACK_IDS = [
    "0180411000803", "3017620422003", "3263859883713", "8437011606013", "6111069000451",
    "737628064502", "5449000000996", "3017620425035", "4005808262629", "8000500310427",
]


def _dirty_units_sold():
    """Mostly a clean integer string; occasionally blank, padded, '0', 'null', or comma-formatted."""
    clean_val = random.randint(50, 1200)
    if random.random() < DIRTY_RATE:
        options = ["", "null", "0", f" {clean_val} "]
        if clean_val >= 1000:
            options.append(f"{clean_val:,}")  # e.g. "1,200"
        return random.choice(options)
    return str(clean_val)


def _fabricate_ghost_id(used_ids):
    """Build a plausible 13-digit EAN-shaped barcode string (leading zeroes allowed)
    that is not already in use."""
    while True:
        candidate = "".join(str(random.randint(0, 9)) for _ in range(13))
        if candidate not in used_ids:
            return candidate


def generate_pantry_log(id_list, output_path=None, seed=None):
    """
    Write a messy warehouse_scan_log.csv built from a real list of product barcodes.

    Args:
        id_list: iterable of barcode strings (the API's `code` field). Pass these
            as strings — do not int() them first, or leading zeroes will be lost.
        output_path: where to write the CSV. Defaults to data/raw/warehouse_scan_log.csv;
            parent folders are created automatically if they don't exist.
        seed: optional int for reproducible output (useful for grading/debugging).
            Leave as None for a fresh random log on every run.

    Returns:
        pathlib.Path to the file that was written.
    """
    if seed is not None:
        random.seed(seed)

    output_path = Path(output_path) if output_path else DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ids = [str(i).strip() for i in id_list if str(i).strip()]

    n_drop = round(len(ids) * DROP_RATE)
    dropped = set(random.sample(ids, n_drop)) if n_drop else set()
    surviving_ids = [i for i in ids if i not in dropped]

    n_ghost = round(len(ids) * GHOST_RATE)
    used_ids = set(ids)
    ghost_ids = []
    for _ in range(n_ghost):
        ghost = _fabricate_ghost_id(used_ids)
        used_ids.add(ghost)
        ghost_ids.append(ghost)

    all_ids = surviving_ids + ghost_ids
    random.shuffle(all_ids)

    rows = [
        {
            "barcode": barcode,
            "shelf_location": random.choice(SHELF_LOCATIONS),
            "units_sold_last_month": _dirty_units_sold(),
        }
        for barcode in all_ids
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"[generate_pantry_log] {len(ids)} input barcodes -> {len(rows)} log rows "
        f"({len(dropped)} dropped, {len(ghost_ids)} ghost ids injected) -> {output_path}"
    )
    return output_path


def _load_ids_from_file(path):
    """Read one barcode per line from a plain text file, ignoring blank lines."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Could not find {p}. Pass a text file with one barcode per line via "
            "--input-ids, or omit --input-ids to run the built-in smoke test."
        )
    return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _cli():
    parser = argparse.ArgumentParser(
        description="Generate a messy data/raw/warehouse_scan_log.csv for Project Pantry Audit."
    )
    parser.add_argument(
        "--input-ids", default=None,
        help="Path to a text file with one barcode per line. Omit to run a built-in smoke test.",
    )
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT),
        help=f"Output CSV path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Optional random seed for reproducible output.",
    )
    args = parser.parse_args()

    if args.input_ids:
        ids = _load_ids_from_file(args.input_ids)
    else:
        print("No --input-ids given; running with the built-in fallback id list as a smoke test.")
        ids = FALLBACK_IDS

    generate_pantry_log(ids, output_path=args.output, seed=args.seed)


if __name__ == "__main__":
    _cli()

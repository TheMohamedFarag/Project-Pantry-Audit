"""
Project Pantry Audit — Retail Shelf-Health Scoring Pipeline.

Pulls a live product catalog from Open Food Facts, reconciles it against a
generated warehouse scan log, and flags SKUs against the FDA 5/20 rule for
added sugars.
"""

import requests
import json
import csv
from pathlib import Path

API_URL = "https://world.openfoodfacts.org/api/v2/search"

HEADERS = {
    "User-Agent": "RowadMasr-Python-MohamedFarag/1.0 (themohamedfarag@gmail.com)"
}

PARAMS = {
    "categories_tags_en": "breakfast-cereals",
    "page_size": 100,
    "fields": "code,product_name,brands,quantity,categories_tags_en,countries_tags,ingredients_text,nutrition_grades,nutriments",
}


def fetch_products():
    """
    Fetch the product catalog from the Open Food Facts search API.

    Sends a single GET request with the module-level PARAMS and HEADERS,
    wraps the network call in try/except so a connection failure doesn't
    crash the whole pipeline.

    Returns:
        list[dict]: the list of product records under payload["products"],
        or an empty list if the request failed.
    """
    try:
        response = requests.get(API_URL, params=PARAMS, headers=HEADERS)
        response.raise_for_status()
        payload = response.json()
        return payload.get("products", [])
    except requests.exceptions.RequestException as e:
        print(f"[fetch_products] Request failed: {e}")
        return []


def scrape_daily_value_sugar():
    """
    Scrape the FDA Daily Value for added sugars from sugar.org.

    Fetches the target page, finds the anchor phrase "the Daily Value is ",
    and takes the first whitespace-delimited token right after it as the
    number. Falls back to the well-known FDA figure (50.0g) if the page or
    the anchor phrase can't be reached/found, so the pipeline stays runnable
    offline.

    Note on source reliability: sugar.org is an industry advocacy site, but
    here it is reporting a federal regulatory figure (the FDA Daily Value)
    in plain prose rather than asserting an opinion, so it's used only as
    a convenient carrier of that public number.

    Returns:
        float: the daily value in grams (expected: 50.0).
    """
    scrape_url = "https://www.sugar.org/blog/making-sense-of-added-sugars-on-the-new-nutrition-facts-label/"
    anchor = "the Daily Value is "

    try:
        response = requests.get(scrape_url, headers=HEADERS)
        response.raise_for_status()
        page_text = response.text

        position = page_text.find(anchor)
        if position == -1:
            print("[scrape_daily_value_sugar] Anchor phrase not found, using fallback 50.0")
            return 50.0

        text_after_anchor = page_text[position + len(anchor):]
        first_token = text_after_anchor.strip().split()[0]
        return float(first_token)

    except (requests.exceptions.RequestException, ValueError, IndexError) as e:
        print(f"[scrape_daily_value_sugar] Scrape failed: {e}, using fallback 50.0")
        return 50.0


def parse_quantity_grams(raw):
    """
    Extract the leading numeric value from OFF's free-text quantity field.

    Walks the string character by character, collecting digits and at most
    one decimal point into a running string, and stops as soon as it hits
    a non-digit character after collection has started. Multipack strings
    like "12 x 25 g" are not confidently parseable and return None.

    Args:
        raw: the raw quantity string (e.g. "70 g", "1.5 L"), or None.

    Returns:
        float or None: the parsed leading number, or None if nothing
        confident could be parsed.
    """
    if raw is None:
        return None

    number_str = ""
    started = False
    seen_decimal = False

    for char in raw:
        if char.isdigit():
            number_str += char
            started = True
        elif char == "." and started and not seen_decimal:
            number_str += char
            seen_decimal = True
        elif started:
            break

    if not number_str:
        return None

    try:
        return float(number_str)
    except ValueError:
        return None


def filter_cohort(records):
    """
    Drop any product with no sugars_100g value at all.

    Products missing sugars_100g can't be scored against the target
    definition, so they're structurally excluded from the cohort (distinct
    from imputation, which is reserved for fields we keep but fill in).

    Args:
        records: list[dict] of raw product records.

    Returns:
        list[dict]: only the records where sugars_100g is present.
    """
    return [
        record for record in records
        if record.get("nutriments", {}).get("sugars_100g") is not None
    ]


def compute_cohort_means(records, field):
    """
    Compute the mean of a nutriment field across records where it's present.

    Used to derive imputation values for fields like fiber_100g and
    proteins_100g. Skips records missing the field entirely.

    Args:
        records: list[dict] of product records.
        field: the nutriment key to average (e.g. "fiber_100g").

    Returns:
        float: the mean value, or 0.0 if no record has the field.
    """
    total = 0
    count = 0
    for record in records:
        value = record.get("nutriments", {}).get(field)
        if value is not None:
            total += value
            count += 1
    return total / count if count else 0.0


def build_clean_records(records, fiber_mean, proteins_mean, daily_value_sugar_g):
    """
    Build cleaned, feature-engineered records from the filtered cohort.

    For each record: imputes missing fiber_100g/proteins_100g with the
    cohort mean, parses the free-text quantity field into grams, and
    derives sugar_pct_dv, sugar_tier, and high_sugar_flag per the FDA
    5/20 rule.

    Args:
        records: list[dict], the filtered cohort (sugars_100g guaranteed present).
        fiber_mean: float, cohort mean used to impute missing fiber_100g.
        proteins_mean: float, cohort mean used to impute missing proteins_100g.
        daily_value_sugar_g: float, the scraped FDA daily value for added sugars.

    Returns:
        list[dict]: one flat dict per product, ready for CSV writing.
    """
    clean_records = []

    for record in records:
        nutriments = record.get("nutriments", {})

        sugars_100g = nutriments.get("sugars_100g")

        fiber_100g = nutriments.get("fiber_100g")
        if fiber_100g is None:
            fiber_100g = fiber_mean

        proteins_100g = nutriments.get("proteins_100g")
        if proteins_100g is None:
            proteins_100g = proteins_mean

        quantity_grams = parse_quantity_grams(record.get("quantity"))

        sugar_pct_dv = (sugars_100g / daily_value_sugar_g) * 100

        if sugar_pct_dv < 5:
            sugar_tier = "low"
        elif sugar_pct_dv < 20:
            sugar_tier = "moderate"
        else:
            sugar_tier = "high"

        high_sugar_flag = 1 if (sugars_100g / 50.0) >= 0.20 else 0

        clean_records.append({
            "barcode": str(record.get("code", "")),
            "product_name": record.get("product_name", ""),
            "brands": record.get("brands", ""),
            "quantity_grams": quantity_grams,
            "sugars_100g": sugars_100g,
            "fat_100g": nutriments.get("fat_100g"),
            "fiber_100g": fiber_100g,
            "proteins_100g": proteins_100g,
            "salt_100g": nutriments.get("salt_100g"),
            "energy_kcal_100g": nutriments.get("energy-kcal_100g"),
            "nutrition_grades": record.get("nutrition_grades", ""),
            "sugar_pct_dv": sugar_pct_dv,
            "sugar_tier": sugar_tier,
            "high_sugar_flag": high_sugar_flag,
        })

    return clean_records


def load_warehouse_log(log_path):
    """
    Load the warehouse scan log into a dict keyed by barcode.

    Args:
        log_path: path to warehouse_scan_log.csv.

    Returns:
        dict[str, dict]: barcode -> {"shelf_location": ..., "units_sold_last_month": ...}
    """
    log_by_barcode = {}
    with open(log_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            log_by_barcode[row["barcode"]] = row
    return log_by_barcode


def join_with_log(clean_records, log_by_barcode):
    """
    Attach warehouse log fields to each cleaned record by barcode.

    About 10% of barcodes won't have a match in the log (dropped ids) —
    those records still keep their place but get None for the log fields.

    Args:
        clean_records: list[dict], the output of build_clean_records.
        log_by_barcode: dict[str, dict], the output of load_warehouse_log.

    Returns:
        list[dict]: clean_records with shelf_location and
        units_sold_last_month added to each.
    """
    joined_records = []
    for record in clean_records:
        log_row = log_by_barcode.get(record["barcode"], {})
        record["shelf_location"] = log_row.get("shelf_location")
        record["units_sold_last_month"] = log_row.get("units_sold_last_month")
        joined_records.append(record)
    return joined_records


def scale_sugar_pct_dv(records):
    """
    Add a min-max scaled version of sugar_pct_dv to each record.

    scaled_x = (x - min_x) / (max_x - min_x)

    Args:
        records: list[dict], each with a sugar_pct_dv field.

    Returns:
        list[dict]: the same records with sugar_pct_dv_scaled added.
    """
    values = [r["sugar_pct_dv"] for r in records]
    min_x = min(values)
    max_x = max(values)

    for record in records:
        record["sugar_pct_dv_scaled"] = (record["sugar_pct_dv"] - min_x) / (max_x - min_x)

    return records


def validation_check(records):
    """
    Build a grouped rate table: for each nutrition_grades letter, what
    percentage of products are high_sugar_flag == 1?

    Uses two counters (total per grade, flagged per grade) built with the
    same .get(key, 0) + 1 accumulation pattern, since nutrition_grades is
    a letter (a-e, or missing) rather than a binary field.

    Args:
        records: list[dict], each with nutrition_grades and high_sugar_flag.

    Returns:
        dict[str, dict]: grade -> {"total": int, "flagged": int, "pct_flagged": float}
    """
    totals_by_grade = {}
    flagged_by_grade = {}

    for record in records:
        grade = record.get("nutrition_grades") or "unknown"
        totals_by_grade[grade] = totals_by_grade.get(grade, 0) + 1
        if record["high_sugar_flag"] == 1:
            flagged_by_grade[grade] = flagged_by_grade.get(grade, 0) + 1

    result = {}
    for grade, total in totals_by_grade.items():
        flagged = flagged_by_grade.get(grade, 0)
        result[grade] = {
            "total": total,
            "flagged": flagged,
            "pct_flagged": (flagged / total) * 100,
        }

    return result


def write_clean_csv(records, output_path):
    """
    Write the final cleaned, feature-engineered, joined, and scaled
    records to a CSV file using csv.DictWriter.

    Args:
        records: list[dict], the fully processed records.
        output_path: path to write the CSV to (parent dirs are created
        automatically if they don't exist).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(records[0].keys())

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"Wrote {len(records)} rows to {output_path}")


if __name__ == "__main__":
    products = fetch_products()
    print(f"Fetched {len(products)} products")

    cohort = filter_cohort(products)
    print(f"Cohort after filtering: {len(cohort)} products")

    fiber_mean = compute_cohort_means(cohort, "fiber_100g")
    proteins_mean = compute_cohort_means(cohort, "proteins_100g")
    print(f"Fiber mean: {fiber_mean:.2f}")
    print(f"Proteins mean: {proteins_mean:.2f}")

    daily_value_sugar_g = scrape_daily_value_sugar()
    print(f"Daily value sugar (scraped): {daily_value_sugar_g}")
    clean_records = build_clean_records(cohort, fiber_mean, proteins_mean, daily_value_sugar_g)
    print(f"Built {len(clean_records)} clean records")
    print(clean_records[0])

    log_by_barcode = load_warehouse_log("data/raw/warehouse_scan_log.csv")
    print(f"Loaded {len(log_by_barcode)} log entries")

    joined_records = join_with_log(clean_records, log_by_barcode)
    matched = sum(1 for r in joined_records if r["shelf_location"] is not None)
    print(f"Matched {matched}/{len(joined_records)} records against the log")
    print(joined_records[0])

    scaled_records = scale_sugar_pct_dv(joined_records)
    print(f"Scaled sugar_pct_dv range: {min(r['sugar_pct_dv_scaled'] for r in scaled_records):.2f} to {max(r['sugar_pct_dv_scaled'] for r in scaled_records):.2f}")

    grade_table = validation_check(scaled_records)
    print("\nValidation Check — % high_sugar_flag by nutrition_grades:")
    for grade, stats in sorted(grade_table.items()):
        print(f"  {grade}: {stats['flagged']}/{stats['total']} ({stats['pct_flagged']:.1f}%)")

    write_clean_csv(scaled_records, "data/processed/clean_data.csv")
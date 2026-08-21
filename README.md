# Project Pantry Audit — Retail Shelf-Health Scoring

**Rowad Masr Digital Initiative | Python Track**
**Domain:** CPG & Retail / Consumer Health Analytics

A data pipeline project that pulls a live product catalog from the Open Food Facts API, reconciles it against a generated internal warehouse record, and flags products against an FDA health threshold — simulating a retailer's "healthy aisle" / reformulation-review program.

---

## 1. Business Understanding

### 1.1 Objectives

Build an automated shelf-health scoring pass over a product category (Breakfast Cereals), flagging SKUs that would need reformulation review before inclusion in a retailer's "healthy aisle" program.

### 1.2 Resource Audit

| Resource | Detail |
|---|---|
| **API Access** | No key required — but a descriptive `User-Agent` header is mandatory. Requests without one may be rejected. |
| **Rate Limit** | ~10 requests/minute on the search endpoint — irrelevant at this scale since data is pulled once with a large `page_size` instead of polling in a loop. |
| **Data Sources** | Open Food Facts search endpoint (1 call), `data/raw/warehouse_scan_log.csv` (generated, never downloaded), 1 web scrape call |
| **Estimated Time** | 4–6 hours across all three phases |

### 1.3 Target Definition

The FDA nutrition-labeling industry's own "5/20 Rule": a nutrient is considered **low** at ≤5% of its Daily Value and **high** at ≥20%.

```
high_sugar_flag = 1  if (sugars_100g / 50.0) >= 0.20
high_sugar_flag = 0  otherwise
```

**50.0** is the FDA's official Daily Value for added sugars, in grams. This number was scraped live from a public source (see Section 3), not hardcoded.

### 1.4 Brainstormed Features (8)

1. `sugars_100g`
2. `fat_100g`
3. `fiber_100g`
4. `salt_100g`
5. `energy-kcal_100g`
6. `nutrition_grades`
7. `quantity_grams` (parsed from the free-text `quantity` field)
8. `brands`

### 1.5 ROI Framework — Reformulation Workload Reduction

```
pct_workload_reduction = (1 - (n_flagged / n_total)) * 100
```

**Actual result from this run (breakfast-cereals category, 100 products):**

- `n_total` = 100 products
- `n_flagged` (high_sugar_flag == 1) = 63 products
- `pct_workload_reduction` = (1 − 63/100) × 100 = **37.0%**

**Interpretation:** Of the 100 SKUs pulled in this category, **63% (`high_sugar_flag == 1`)** are the products a reformulation team would actually need to review before this category could carry a "healthy aisle" label. In other words, instead of reviewing the entire catalog (100 products), the team only needs to review 63 — a workload reduction of just **37%** in this particular case (since a majority of products in this specific category run high in sugar).

---

## 2. Data Understanding — Key Findings

Full exploration details live in `notebooks/exploration.ipynb`. Key takeaways:

- **Structural inconsistency across products:** Even among the first 6 consecutive products, no two share the exact same set of top-level keys (some carry `nutrition_data_per`, others carry `nutriments_estimated` instead).
- **Nutrient field completeness:** In the pulled sample (100 products), all six core fields (`sugars_100g`, `fat_100g`, `fiber_100g`, `salt_100g`, `proteins_100g`, `energy-kcal_100g`) came back 100% complete. This doesn't mean the underlying database is always this clean — completeness varies significantly across categories, and the code is written to handle missing values (via `.get()`) even though this particular sample didn't surface any.
- **`ingredients_text`:** In this sample specifically, no "missing key" or "empty string" cases appeared (all 100 products had a real value) — but the code explicitly distinguishes between the two states (`"key" not in record` vs. `record.get("key") == ""`) to handle them correctly if they occur in a future run.
- **sugars_100g (single-pass loop, no libraries):** Min = 0, Max = 25, Mean = 12.55 g/100g.
- **Nesting depth:** The data structure is fairly shallow — only one real level of nesting (`nutriments` as a sub-dict inside each product); the rest of the fields are flat values or lists of simple strings.

---

## 3. Data Preparation — Pipeline Summary

Full logic lives in `src/pipeline.py`, executed in this order:

1. **Fetch** — pull 100 products from the Open Food Facts API (`breakfast-cereals` category), wrapped in `try/except` for network errors.
2. **Scrape** — extract the official FDA Daily Value for sugar from a public source by searching for the stable anchor phrase `"the Daily Value is "` — result: **50.0 grams** (matches the official FDA figure).
3. **Cohort Filtering** — drop any product with no `sugars_100g` value at all (it can't be scored against the target).
4. **Imputation** — fill missing `fiber_100g` and `proteins_100g` with the cohort mean (not `sugars_100g`, which is filtered out entirely rather than imputed).
5. **Quantity Parsing** — `parse_quantity_grams()` walks free text like `"70 g"` or `"1.5 L"` character by character and pulls out the leading number, returning `None` for ambiguous cases like `"12 x 25 g"`.
6. **Feature Engineering** — compute `sugar_pct_dv`, `sugar_tier` (low/moderate/high), and `high_sugar_flag` for each product.
7. **Join** — merge each product with `warehouse_scan_log.csv` by barcode (always kept as a string, never cast through `int()`, to preserve leading zeroes).
8. **Min-Max Scaling** — scale `sugar_pct_dv` to a [0, 1] range.
9. **Validation Check** — a grouped rate table of `high_sugar_flag` by `nutrition_grades`.
10. **Export** — write the final output to `data/processed/clean_data.csv`.

### 3.1 Warehouse Log Join Result

Of the 100 barcodes pulled, **90 products (90%)** matched against the generated warehouse log, while 10 (10%) had no match — exactly as expected given how `generate_pantry_log.py` deliberately drops ~10% of ids to simulate scan-gun/sync downtime.

### 3.2 Validation Check — Interpretation

| nutrition_grades | Total Products | Flagged (high_sugar_flag=1) | % Flagged |
|---|---|---|---|
| a | 38 | 9 | 23.7% |
| b | 13 | 10 | 76.9% |
| c | 38 | 35 | 92.1% |
| d | 7 | 5 | 71.4% |
| e | 3 | 3 | 100.0% |
| unknown | 1 | 1 | 100.0% |

**Interpretation:** The table shows a clear overall trend that matches expectations — as `nutrition_grades` worsens (from a toward e), the share of products flagged `high_sugar_flag == 1` climbs sharply, from 23.7% at grade a to 100% at grade e. This makes sense because Open Food Facts' letter grade is computed from several nutritional factors including sugar itself, so a strong overlap with this project's 5/20 rule is expected. A mild exception shows up at grade b (76.9%), which is higher than a perfectly linear trend between a and c would predict — suggesting sugar isn't the only factor driving Open Food Facts' letter grade (it also weighs fat, salt, fiber, and protein).

---

## 4. Repository Structure

```
project-pantry-audit/
├── README.md
├── generate_pantry_log.py        # warehouse log generator (never hand-edited)
├── data/
│   ├── raw/
│   │   ├── extracted_ids.txt         # barcodes extracted from the API
│   │   └── warehouse_scan_log.csv    # generated warehouse log
│   └── processed/
│       └── clean_data.csv            # final pipeline output
├── notebooks/
│   └── exploration.ipynb             # Phase 2 — full EDA
└── src/
    └── pipeline.py                    # Phase 3 — runs standalone end-to-end
```

---

## 5. Setup & Run

### 5.1 Requirements

- Python 3.10+
- Required library: `requests` (everything else used is built into Python: `json`, `csv`, `pathlib`)

### 5.2 Install & Run

```bash
# 1) Clone / download the project, then enter the root folder
cd project-pantry-audit

# 2) Install the required library
pip install requests

# 3) Run the full pipeline (automatically fetches data, cleans it,
#    engineers features, joins, scales, and writes the final output)
python src/pipeline.py
```

**Note (Windows):** if you have more than one Python installation on your machine, use the Python Launcher to target the correct one (the one with `pip` and `requests` installed):

```bash
py -3.13 src/pipeline.py
```

### 5.3 Expected Output

On a successful run, you should see output similar to this in the terminal, and `data/processed/clean_data.csv` will be written:

```
Fetched 100 products
Cohort after filtering: 100 products
Fiber mean: 8.91
Proteins mean: 10.14
Daily value sugar (scraped): 50.0
Built 100 clean records
Loaded 100 log entries
Matched 90/100 records against the log
Scaled sugar_pct_dv range: 0.00 to 1.00

Validation Check — % high_sugar_flag by nutrition_grades:
  a: 9/38 (23.7%)
  b: 10/13 (76.9%)
  c: 35/38 (92.1%)
  d: 5/7 (71.4%)
  e: 3/3 (100.0%)
  unknown: 1/1 (100.0%)
Wrote 100 rows to data/processed/clean_data.csv
```

### 5.4 Generating the Warehouse Log Manually (Optional)

`data/raw/warehouse_scan_log.csv` is auto-generated from inside `notebooks/exploration.ipynb`. To generate it manually from the terminal instead (once `data/raw/extracted_ids.txt` exists):

```bash
python generate_pantry_log.py --input-ids data/raw/extracted_ids.txt
```

### 5.5 Troubleshooting

- **`503 Service Unavailable` from the API:** this is a transient error from the Open Food Facts server (high load on the public service), not a code issue. Retry after a few minutes — the code is wrapped in `try/except` to handle this safely without crashing.
- **`ModuleNotFoundError: No module named 'requests'`:** make sure the library is installed on the same Python interpreter used to run the file (`python -m pip install requests`, or target a specific version explicitly with `py -3.13 -m pip install requests`).

---

## 6. Source Reliability Note

The daily value figure for sugar (50g) was scraped from an industry advocacy site. That said, the specific excerpt used here reports a federal regulatory figure from the FDA in plain prose, not an opinion or interpretation of the site's own — so this source was used only as a convenient carrier of that public number, not as an independent analytical reference.
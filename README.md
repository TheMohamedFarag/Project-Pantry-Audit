# Project Pantry Audit — Retail Shelf-Health Scoring

**Rowad Masr Digital Initiative | Python Track**
**Domain:** CPG & Retail / Consumer Health Analytics

Pulls a live product catalog from the Open Food Facts API, reconciles it against a generated warehouse record, and flags products against an FDA health threshold — simulating a retailer's "healthy aisle" / reformulation-review program.

**Full notebook:** [notebooks/exploration.ipynb](https://github.com/TheMohamedFarag/Project-Pantry-Audit/blob/main/notebooks/exploration.ipynb)
**Full pipeline code:** [src/pipeline.py](https://github.com/TheMohamedFarag/Project-Pantry-Audit/blob/main/src/pipeline.py)
**Final output data:** [data/processed/clean_data.csv](https://github.com/TheMohamedFarag/Project-Pantry-Audit/blob/main/data/processed/clean_data.csv)

---

## 1. Business Understanding

**Objective:** Build an automated shelf-health scoring pass over a product category (Breakfast Cereals), flagging SKUs that would need reformulation review before inclusion in a retailer's "healthy aisle" program.

**Resource Audit:** No API key required (descriptive `User-Agent` header mandatory) · ~10 req/min rate limit (irrelevant, single pull) · Sources: Open Food Facts API + generated `warehouse_scan_log.csv` + 1 scrape call · ~4–6 hrs estimated.

**Target Definition** — FDA's "5/20 Rule":

```
high_sugar_flag = 1  if (sugars_100g / 50.0) >= 0.20
high_sugar_flag = 0  otherwise
```

`50.0` = FDA's official Daily Value for added sugars (grams), scraped live from a public source — not hardcoded.

**Features used (8):** `sugars_100g`, `fat_100g`, `fiber_100g`, `salt_100g`, `energy-kcal_100g`, `nutrition_grades`, `quantity_grams` (parsed), `brands`.

**ROI Framework:**
```
pct_workload_reduction = (1 - (n_flagged / n_total)) * 100
```
**Result:** 63/100 products flagged high-sugar → **37.0% workload reduction** (reviewing 63 SKUs instead of the full 100).

---

## 2. Data Understanding (full detail in the notebook)

- Product records are structurally inconsistent — no two of the first 6 products share the exact same set of keys.
- All 6 core nutrient fields came back 100% complete in this sample; the code still handles missing values via `.get()` for cases not seen here.
- `sugars_100g` (single-pass loop, no libraries): **Min = 0, Max = 25, Mean = 12.55** g/100g.
- Nesting is shallow — one level (`nutriments` sub-dict per product).

---

## 3. Data Preparation (full code in `src/pipeline.py`)

Pipeline steps: **Fetch → Scrape Daily Value → Cohort Filter → Impute (fiber/proteins) → Parse Quantity → Feature Engineer (sugar_pct_dv, sugar_tier, high_sugar_flag) → Join Warehouse Log → Min-Max Scale → Validation Check → Export CSV.**

- **Join result:** 90/100 barcodes matched the warehouse log (10% intentionally dropped by the log generator).
- **Validation Check** (`high_sugar_flag` rate by `nutrition_grades`): rises from **23.7%** at grade `a` to **100%** at grade `e` — confirming the letter grade correlates with sugar content, as expected, with a minor deviation at grade `b` (76.9%) since the grade also weighs fat, salt, and fiber. Full table in the notebook.

---

## 4. Repository Structure

```
project-pantry-audit/
|-- README.md
|-- generate_pantry_log.py
|-- data/{raw, processed}/
|-- notebooks/exploration.ipynb
`-- src/pipeline.py
```

---

## 5. Setup & Run

```bash
cd project-pantry-audit
pip install requests
python src/pipeline.py
```

**Windows (multiple Python versions):** `py -3.13 src/pipeline.py`

**Troubleshooting:** A `503 Service Unavailable` from the API is a transient server-side issue (high public load), not a code bug — the pipeline retries safely via `try/except`; just re-run after a few minutes.

---

## 6. Source Reliability Note

The sugar Daily Value (50g) was scraped from an industry advocacy site, but the specific excerpt reports a federal FDA regulatory figure in plain prose, not the site's own opinion — used only as a convenient carrier of that public number.
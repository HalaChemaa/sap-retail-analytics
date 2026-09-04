# Retail Sales & Inventory Performance Analytics
### A multi-market SAP-style SD/MM analysis, built on a real Sephora product catalog.

---

## 1. Executive Summary

This project analyzes 18 months (Jan 2024 – Jun 2025) of sales and
inventory data for a 221-SKU beauty/skincare/fragrance assortment across 6
countries (France, UK, Germany, USA, UAE, Morocco) and 8 SAP-style plants,
structured the way SAP's Sales & Distribution (SD) and Materials Management
(MM) modules actually organize this data.

**Headline finding:** the business generated **$2.67M** in net revenue and
sold **70,918 units**, but **69.8%** of all SKU/market combinations
experienced at least one stockout over the period — and the highest-revenue
markets (US, France, UK) are also the *most* exposed to it. The
lowest-volume market (Morocco) had by far the lowest stockout rate (29.9%
vs. 82.7% in the US), suggesting stockout risk here scales with demand
outpacing a fixed replenishment cadence, not with any one market's
execution quality.

## 2. Where the data comes from — and why that matters

**The product catalog is real.** `sephora_product_info.csv` is sourced from
the well-known "Sephora Products and Skincare Reviews" dataset (8,494 real
products, 304 real brands, genuine prices and category structure). This
project curates a 221-SKU "active assortment" from it — a realistic
regional buying decision, not "every product sells everywhere."

**Everything transactional is synthetic**, because no company publishes its
actual SAP sales orders or stock movement tables. The synthetic layer
(sales orders, stock movements, plant listings) is built the same
disciplined way as this portfolio's other synthetic-data project: demand is
driven by a noisy function of each SKU's *real* popularity (its actual
`loves_count`/rating from the Sephora data) and price, not hand-picked to
produce a tidy story. Stockouts emerge from the interaction between that
demand and a periodic (14-day) replenishment cycle with occasional
deliberate under-ordering — they are not manufactured to appear at
convenient moments.

## 3. Data Model (mirrors SAP SD + MM structure)

```
dim_material (material_id PK, material_description, brand, product_category,
              product_subcategory, list_price_usd, standard_cost_usd,
              avg_rating, loves_count, review_count)
              -- equivalent to SAP MARA/MAKT (material master)

dim_plant (plant_id PK, country, region, channel)
              -- equivalent to SAP T001W (plant master)

plant_material_listing (plant_id FK, material_id FK)
              -- which SKUs are actually carried at which plant

sales_orders (order_id PK, order_date, plant_id FK, material_id FK, channel,
              quantity, unit_price_usd, discount_pct, units_returned)
              -- equivalent to SAP VBAK/VBAP (sales document header/items)

stock_movements (movement_id PK, movement_date, plant_id FK, material_id FK,
                  movement_type, quantity)
              -- equivalent to SAP MSEG (material document line items)
              -- NOTE: quantity is SIGNED — positive for stock coming in
              -- (000 opening balance, 101 goods receipt, 651 customer
              -- return), negative for stock going out (601 goods issue
              -- for a sale). A running SUM gives the inventory position.
```

**Movement types used** (named after real SAP movement type codes):
`000_OPENING_BALANCE`, `101_GOODS_RECEIPT`, `601_GOODS_ISSUE_SALE`,
`651_CUSTOMER_RETURN`.

**Why normalized rather than one flat table:** a material is listed at
several plants, has many sales order lines and many stock movements over
time — exactly the one-to-many relationships a relational schema exists to
handle, and exactly why the SQL file's JOINs and window functions do real
work rather than decorative ones.

## 4. Data Pipeline

```
01_prepare_material_master.py  → reshapes the real Sephora catalog into an
                                  SAP-style material master + curates a
                                  221-SKU active assortment
02_generate_transactions.py    → synthetic plant master, sales orders,
                                  stock movements (noisy, popularity-driven)
03_make_messy_raw_exports.py   → deliberately messy SAP-extract-style CSVs
04_clean_and_load.py           → cleans + loads into db/sap_retail.db
05_python_analysis.py          → metrics + 8 charts → outputs/
06_build_excel_template.py     → excel/cycle_count_template.xlsx (input layer)
```

The raw exports mimic a real SAP table extract pulled via SE16/SE16N into
Excel: plant codes with inconsistent casing/whitespace, movement types
shown as raw codes vs. descriptive text inconsistently, four different date
formats, a stray `$` left in some price fields, missing discount values,
and duplicate line items from a re-run extract.

**Cleaning report:**
| Issue | Count |
|---|---|
| Sales order exact duplicates removed | 995 |
| Sales orders with missing discount (defaulted to 0%) | 4,697 |
| Sales orders with negative quantity typo (sign fixed) | 664 |
| Stock movement exact duplicates removed | 1,053 |
| Stock movements with missing quantity (dropped) | 2,202 |

67,346 raw sales order rows → 66,351 clean rows. 106,353 raw movement rows
→ 103,098 clean rows.

## 5. Metrics

| Metric | Formula | Value | Why it matters |
|---|---|---|---|
| **Net Revenue** | Σ(quantity × unit_price × (1 − discount)) | **$2,670,812** | Headline commercial number |
| **Units Sold** | Σ(quantity) | **70,918** | Volume baseline for turnover/return-rate calculations |
| **Overall Return Rate** | returned units ÷ sold units | **5.8%** | Category-level variation is the more useful cut (see Finding 3) |
| **Stockout Rate** | % of plant/SKU combos where running stock ever went negative | **69.8%** | The single most actionable inventory metric in the project |
| **Median Inventory Turnover** | units sold ÷ units received, per SKU | **0.99x** | A ratio near 1.0 means replenishment is barely keeping pace with sales, on average — very little buffer |

## 6. Key Findings

**Finding 1 — Skincare and Fragrance drive revenue; the operational risk is
elsewhere.** Category revenue: Skincare $852K, Makeup $696K, Fragrance
$582K, Hair $344K, Bath & Body $197K. But revenue share and stockout risk
don't line up — see Finding 2.

**Finding 2 — The biggest markets have the worst stockout rates.**
Stockout rate by country: US 82.7%, France 78.8%, UK 78.6%, Germany 70.1%,
UAE 60.2%, **Morocco 29.9%**. Morocco's dramatically lower rate lines up
with it being the lowest-demand market in the model — with a fixed 14-day
replenishment cycle, higher-velocity markets have less margin for error
before they run dry between deliveries.

**Finding 3 — Makeup returns at 3x the rate of Bath & Body.** Return rate
by category: Makeup 9.1%, Skincare 5.0%, Hair 3.8%, Fragrance 2.9%, Bath &
Body 2.0% — consistent with real-world shade-matching being a common
makeup-specific return driver.

**Finding 4 — Inventory turnover sits right at the edge of comfortable.** A
median turnover ratio of 0.99x means, typically, a SKU sells almost exactly
what gets shipped to it — there's very little slack, which is consistent
with how often stockouts occur (Finding 2).

**Finding 5 (with an important caveat) — Discount depth showed no
relationship with order-line volume in this data**, averaging 1.06–1.07
units per line across every discount band from "no discount" to "16%+."
**This is a limitation of the synthetic model, not a market finding**:
demand in this dataset was not designed to respond to discount depth, so
this result mainly demonstrates the SQL/Python technique (Q10 / chart 8)
rather than a real insight — flagged honestly rather than dressed up as one.

## 7. Recommendations (framed for a hypothetical regional ops stakeholder)

1. **Move high-velocity market/category combinations to a shorter
   replenishment cycle.** US Bath & Body (96% stockout rate) and US Hair
   (92%) are the clearest candidates — the 14-day cycle isn't matching
   actual sell-through there.
2. **Don't treat Morocco's low stockout rate as an execution win to
   replicate elsewhere.** It's a function of lower demand, not better
   process — copying its replenishment cadence to high-velocity markets
   would make their stockout problem worse, not better.
3. **Investigate Makeup-specific return drivers** (shade matching, virtual
   try-on accuracy) given its return rate is roughly 3x the category
   average.
4. **Re-examine the discounting strategy** — if real sales data showed the
   same pattern as this synthetic model (discount depth not moving basket
   size), that would be a signal to test whether promotions are just
   eroding margin on sales that would have happened anyway.

## 8. Limitations

- **Transactional data is synthetic**; the specific figures above
  demonstrate the analytical approach, not real Sephora/LVMH performance.
- **Demand does not respond to discount depth in this model** — Finding 5
  is disclosed as a modeling limitation, not a market insight, precisely to
  avoid overselling a synthetic artifact as a real discovery.
- **Replenishment logic is simplified** to a fixed 14-day cycle with
  randomized under-ordering; real replenishment involves lead times,
  supplier constraints, and forecast-driven ordering this model doesn't
  capture.
- **Standard cost is estimated** from a category-typical margin assumption,
  not real margin data (which isn't public), so any profitability
  extension of this analysis should be treated as illustrative only.
- **No seasonality beyond a mild weekend boost** was modeled; real beauty
  retail has pronounced holiday-season effects this dataset doesn't capture.

## 9. Future Analysis

- Model lead-time-aware replenishment (reorder point + safety stock)
  instead of a fixed 14-day cycle, and re-test the stockout findings.
- If extended with real POS data: test whether discount depth *actually*
  moves volume, replacing the flagged limitation in Finding 5.
- Add a demand-forecasting layer (e.g. moving average or exponential
  smoothing) to compare forecasted vs. actual replenishment sizing.
- Extend `dim_material` with real ingredient/ratings data (already present
  in the source Sephora dataset) to test whether product rating predicts
  sell-through independent of brand.

---

## 10. Interview Prep

**1. "Which part of this is real data, and which is synthetic — and why
does that split make sense?"**
*Strong answer:* the product catalog (names, brands, prices, categories) is
a real, public dataset; the transactional layer is synthetic because SAP
transactional data is proprietary and never published. Explain the
popularity-driven, noisy demand generation as the safeguard against
"manufactured" findings.

**2. "Walk me through how you calculated whether a SKU stocked out."**
*Strong answer:* explain the signed `quantity` convention in
`stock_movements`, the running-sum window function (SQL Q3/Q4), and that
"stocked out" means the running balance went negative at least once —
mention the days-in-stockout severity measure as a refinement beyond a
simple flag.

**3. "Why is Morocco's stockout rate so much lower — is that a good sign?"**
*Strong answer:* no — it's an artifact of lower demand relative to a fixed
replenishment cadence, not better execution; explicitly warn against
copying its cadence to higher-velocity markets (Recommendation 2).

**4. "Your discount-vs-volume finding shows no effect — is that a real
result?"**
*Strong answer:* explicitly no, and say why up front — demand generation in
this synthetic model wasn't built to respond to discounting, so this
result is disclosed as a modeling limitation, not a market conclusion. A
candidate who volunteers this without being asked is showing exactly the
kind of honesty a hiring manager is testing for.

**5. "Why include an Excel cycle-count sheet instead of just SQL/Python/BI?"**
*Strong answer:* it represents the real manual-input layer in an SAP MM
environment (physical inventory counts, SAP transactions MI01/MI04/MI07) —
without it, the system's stock figures are just what the system believes,
not what's verified on the shelf.

**6. "How did you decide which 221 SKUs to include out of 8,494?"**
*Strong answer:* popularity-weighted sampling within each category's real
share of the catalog — mirrors how a regional buying team would curate an
assortment rather than carrying everything globally.

**7. "What would you do differently with real transactional data?"**
*Strong answer:* reference Section 9 — proper lead-time-aware replenishment
modeling and testing the actual discount-demand relationship instead of
disclosing it as a limitation.

**8. "Why SQLite instead of a 'real' database like PostgreSQL or SQL
Server?"**
*Strong answer:* SQLite is sufficient to demonstrate the same SQL
techniques (joins, CTEs, window functions) for a portfolio project of this
size, with zero setup friction for anyone reviewing it — a defensible
engineering trade-off, not a limitation of understanding.

**9. "What's the single most useful chart in this project for a
stakeholder?"**
*Strong answer:* the stockout heatmap (chart 4 / BI Page 2) — because it's
the only view that immediately tells a regional ops lead exactly where to
act, rather than just describing what already happened (revenue charts).

**10. "How does this project relate to your actual SAP/Atos experience?"**
*Strong answer:* be concrete about what you actually did on SAP (SD/MM
transactions, tables, reporting you touched) and how this project's schema
and movement types mirror that structure — this is the moment the project
is built to set up.

---

## Repository structure

```
data/raw/                    messy SAP-extract-style CSVs
data/clean/                  cleaned CSVs + cleaning_report.txt
db/sap_retail.db             normalized SQLite database
scripts/                     01-06, the full pipeline, run in order
sql/analysis_queries.sql     10 annotated SQL queries (JOINs, CTEs, window fns)
outputs/                     8 charts, metrics_summary.csv, flat tables for BI
excel/                       cycle_count_template.xlsx (input layer)
bi_specs/                    Power BI + Tableau design specification
```

## How to reproduce

```bash
pip install pandas numpy matplotlib seaborn openpyxl
python scripts/01_prepare_material_master.py
python scripts/02_generate_transactions.py
python scripts/03_make_messy_raw_exports.py
python scripts/04_clean_and_load.py
python scripts/05_python_analysis.py
python scripts/06_build_excel_template.py
```

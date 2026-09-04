# Power BI & Tableau Design Specs — Retail Sales & Inventory Analytics

Import `outputs/flat_sales_orders_for_bi.csv` (one row per sales order line
— the main fact table) and `outputs/flat_stockout_turnover_for_bi.csv`
(one row per plant/SKU combo — for inventory-side visuals) into either tool.

---

## Part A — Power BI Dashboard (3 pages)

### Page 1: Commercial Overview — "How is the business performing?"
**Business question:** Revenue, volume, and returns at a glance, filterable
by market and category — the page a regional sales lead opens first.

- **KPI cards:** Net Revenue · Units Sold · Overall Return Rate · Revenue per SKU
- **Main visual:** Bar — Net revenue by country (matches `chart_01_revenue_by_country.png`)
- **Secondary visual:** Line — Monthly revenue trend by region (matches `chart_03_monthly_revenue_by_region.png`)
- **Filters:** Country, Product Category, Channel, Date range
- **Key DAX measures:**
  ```
  Net Revenue = SUMX(sales_orders, sales_orders[quantity] * sales_orders[unit_price_usd] * (1 - sales_orders[discount_pct]))

  Return Rate = DIVIDE(SUM(sales_orders[units_returned]), SUM(sales_orders[quantity]))

  Revenue per SKU = DIVIDE([Net Revenue], DISTINCTCOUNT(sales_orders[material_id]))
  ```

### Page 2: Inventory Health — "Where are we losing sales to stockouts?"
**Business question:** Which markets/categories are most exposed to
stockout risk, and how healthy is inventory turnover?

- **Visual 1:** Heatmap — Stockout rate by country × category (matches `chart_04_stockout_heatmap.png`)
- **Visual 2:** Histogram — Inventory turnover ratio distribution
- **Visual 3:** Table — Top 15 SKUs by stockout severity (days_in_stockout), with country/category
- **Interaction:** Clicking a heatmap cell filters the SKU table to that country/category
- **Key DAX measure:**
  ```
  Stockout Rate = DIVIDE(
      CALCULATE(COUNTROWS(stockout_turnover), stockout_turnover[ever_stocked_out] = TRUE),
      COUNTROWS(stockout_turnover)
  )
  ```

### Page 3: Product & Brand Performance — "What's actually working?"
**Business question:** Which SKUs/brands are the revenue drivers, and does
discounting move volume or just erode margin?

- **Visual 1:** Bar — Top 10 SKUs by net revenue (matches `chart_07_top_skus.png`)
- **Visual 2:** Bar — Return rate by category (matches `chart_05_return_rate_by_category.png`)
- **Visual 3:** Bar — Average units per order line by discount band (matches `chart_08_discount_vs_volume.png`)
- **Filters carried from Page 1**

---

## Part B — Tableau Story: *"One Assortment, Six Markets: Where Retail
Execution Breaks Down"*

5 fixed story points, read in sequence:

| Story point | Sheet | Narrative beat |
|---|---|---|
| 1. The Business | Bar: revenue by country | "$2.67M in net revenue across 6 markets over 18 months — the US leads by a wide margin." |
| 2. Same Catalog, Different Fortunes | Bar: revenue by category | "Skincare and Makeup dominate revenue — but that's not where the operational risk is." |
| 3. The Real Problem Isn't Demand, It's Supply | Heatmap: stockout rate by country × category | "Nearly 70% of SKU/market combinations experienced a stockout at some point. The US and UK — the biggest markets — are also the most exposed." |
| 4. Lower Volume, Fewer Stockouts | Annotated bar: stockout rate, Morocco vs. others | "Morocco's lower sales velocity means replenishment keeps pace more easily — a reminder that stockout risk scales with demand, not just with process quality." |
| 5. Discounting Isn't Moving Volume | Bar: avg units per line by discount band | "Heavier discounts don't correspond to meaningfully larger order lines — closing recommendation." |

---

## Field/measure reference

| Field | Type | Source |
|---|---|---|
| `net_revenue` | Numeric | quantity × unit_price_usd × (1 - discount_pct) |
| `ever_stocked_out` | Boolean | min(running_stock) < 0 for that plant/material |
| `days_in_stockout` | Numeric | days spent with running_stock < 0 |
| `turnover_ratio` | Numeric | units sold ÷ units received, per SKU |

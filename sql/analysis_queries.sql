-- ============================================================================
-- SQL ANALYSIS QUERIES — "Retail Sales & Inventory Performance Analytics"
-- Database: db/sap_retail.db (SQLite)
-- Mirrors SAP SD (sales) + MM (inventory) module analysis.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Q1. Revenue by country and product category (SD-style reporting)
-- Technique: JOIN across 3 tables + GROUP BY + computed net revenue
-- ----------------------------------------------------------------------------
SELECT
    p.country,
    m.product_category,
    ROUND(SUM(s.quantity * s.unit_price_usd * (1 - s.discount_pct)), 2) AS net_revenue_usd,
    SUM(s.quantity) AS units_sold
FROM sales_orders s
JOIN dim_plant p ON p.plant_id = s.plant_id
JOIN dim_material m ON m.material_id = s.material_id
GROUP BY p.country, m.product_category
ORDER BY net_revenue_usd DESC
LIMIT 20;


-- ----------------------------------------------------------------------------
-- Q2. Top 10 SKUs by net revenue, with brand and category
-- Technique: JOIN + GROUP BY + ORDER BY + LIMIT
-- ----------------------------------------------------------------------------
SELECT
    m.material_id, m.material_description, m.brand, m.product_category,
    SUM(s.quantity) AS total_units_sold,
    ROUND(SUM(s.quantity * s.unit_price_usd * (1 - s.discount_pct)), 2) AS net_revenue_usd
FROM sales_orders s
JOIN dim_material m ON m.material_id = s.material_id
GROUP BY m.material_id
ORDER BY net_revenue_usd DESC
LIMIT 10;


-- ----------------------------------------------------------------------------
-- Q3. Running stock balance per plant/material (window function: SUM OVER)
-- Technique: WINDOW FUNCTION -- note: quantity is already signed in this
-- table (positive = stock in: opening balance/receipt/return, negative =
-- stock out: goods issue for a sale), so a plain running SUM gives the
-- inventory position over time.
-- ----------------------------------------------------------------------------
SELECT
    plant_id, material_id, movement_date,
    SUM(quantity) OVER (
        PARTITION BY plant_id, material_id ORDER BY movement_date, movement_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_stock
FROM stock_movements
ORDER BY plant_id, material_id, movement_date
LIMIT 30;


-- ----------------------------------------------------------------------------
-- Q4. Stockout incidence by plant and category (how often does running
-- stock go negative -- i.e. demand the plant couldn't actually fulfill?)
-- Technique: CTE + window function + aggregate on top of a derived CTE
-- ----------------------------------------------------------------------------
WITH running AS (
    SELECT
        plant_id, material_id, movement_date,
        SUM(quantity) OVER (
            PARTITION BY plant_id, material_id ORDER BY movement_date, movement_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running_stock
    FROM stock_movements
),
stockout_flag AS (
    SELECT
        plant_id, material_id,
        MAX(CASE WHEN running_stock < 0 THEN 1 ELSE 0 END) AS ever_stocked_out
    FROM running
    GROUP BY plant_id, material_id
)
SELECT
    p.country,
    m.product_category,
    COUNT(*) AS sku_plant_combos,
    SUM(sf.ever_stocked_out) AS combos_with_stockout,
    ROUND(100.0 * SUM(sf.ever_stocked_out) / COUNT(*), 1) AS stockout_rate_pct
FROM stockout_flag sf
JOIN dim_plant p ON p.plant_id = sf.plant_id
JOIN dim_material m ON m.material_id = sf.material_id
GROUP BY p.country, m.product_category
ORDER BY stockout_rate_pct DESC;


-- ----------------------------------------------------------------------------
-- Q5. Inventory turnover proxy: units sold / average on-hand units, per SKU
-- Technique: CTE + JOIN + division with NULLIF guard
-- ----------------------------------------------------------------------------
WITH sales_by_sku AS (
    SELECT material_id, SUM(quantity) AS units_sold
    FROM sales_orders
    GROUP BY material_id
),
receipts_by_sku AS (
    SELECT material_id, SUM(quantity) AS units_received
    FROM stock_movements
    WHERE movement_type IN ('101_GOODS_RECEIPT', '000_OPENING_BALANCE')
    GROUP BY material_id
)
SELECT
    m.material_id, m.material_description, m.product_category,
    sb.units_sold,
    rb.units_received,
    ROUND(sb.units_sold * 1.0 / NULLIF(rb.units_received, 0), 2) AS approx_turnover_ratio
FROM dim_material m
JOIN sales_by_sku sb ON sb.material_id = m.material_id
JOIN receipts_by_sku rb ON rb.material_id = m.material_id
ORDER BY approx_turnover_ratio DESC
LIMIT 20;


-- ----------------------------------------------------------------------------
-- Q6. Return rate by category and channel (CASE + GROUP BY on two dimensions)
-- ----------------------------------------------------------------------------
SELECT
    m.product_category,
    s.channel,
    SUM(s.quantity) AS units_sold,
    SUM(s.units_returned) AS units_returned,
    ROUND(100.0 * SUM(s.units_returned) / NULLIF(SUM(s.quantity), 0), 2) AS return_rate_pct
FROM sales_orders s
JOIN dim_material m ON m.material_id = s.material_id
GROUP BY m.product_category, s.channel
ORDER BY return_rate_pct DESC;


-- ----------------------------------------------------------------------------
-- Q7. Month-over-month revenue trend by region (date functions + window
-- function for month-over-month % change)
-- ----------------------------------------------------------------------------
WITH monthly AS (
    SELECT
        p.region,
        strftime('%Y-%m', s.order_date) AS year_month,
        SUM(s.quantity * s.unit_price_usd * (1 - s.discount_pct)) AS net_revenue
    FROM sales_orders s
    JOIN dim_plant p ON p.plant_id = s.plant_id
    GROUP BY p.region, year_month
)
SELECT
    region, year_month, ROUND(net_revenue, 2) AS net_revenue,
    ROUND(
        100.0 * (net_revenue - LAG(net_revenue) OVER (PARTITION BY region ORDER BY year_month))
        / NULLIF(LAG(net_revenue) OVER (PARTITION BY region ORDER BY year_month), 0),
        1
    ) AS mom_pct_change
FROM monthly
ORDER BY region, year_month;


-- ----------------------------------------------------------------------------
-- Q8. Brands with the highest revenue-per-SKU efficiency (a small assortment
-- generating outsized revenue vs. a brand with many SKUs spreading it thin)
-- Technique: subquery + GROUP BY + HAVING
-- ----------------------------------------------------------------------------
SELECT
    m.brand,
    COUNT(DISTINCT m.material_id) AS sku_count,
    ROUND(SUM(s.quantity * s.unit_price_usd * (1 - s.discount_pct)), 2) AS net_revenue_usd,
    ROUND(SUM(s.quantity * s.unit_price_usd * (1 - s.discount_pct)) * 1.0 / COUNT(DISTINCT m.material_id), 2) AS revenue_per_sku
FROM sales_orders s
JOIN dim_material m ON m.material_id = s.material_id
GROUP BY m.brand
HAVING sku_count >= 2
ORDER BY revenue_per_sku DESC
LIMIT 15;


-- ----------------------------------------------------------------------------
-- Q9. Plants carrying a SKU that has NEVER sold there (dead listing --
-- shelf space tied up with zero velocity)
-- Technique: LEFT JOIN + IS NULL (anti-join pattern)
-- ----------------------------------------------------------------------------
SELECT
    l.plant_id, p.country, l.material_id, m.material_description, m.product_category
FROM plant_material_listing l
JOIN dim_plant p ON p.plant_id = l.plant_id
JOIN dim_material m ON m.material_id = l.material_id
LEFT JOIN sales_orders s ON s.plant_id = l.plant_id AND s.material_id = l.material_id
WHERE s.order_id IS NULL
ORDER BY p.country, m.product_category;


-- ----------------------------------------------------------------------------
-- Q10. Discounting behavior: does heavier discounting actually correlate
-- with higher volume, or just lower margin on sales that would have
-- happened anyway? (bucketed CASE + aggregate)
-- ----------------------------------------------------------------------------
SELECT
    CASE
        WHEN discount_pct = 0 THEN 'No discount'
        WHEN discount_pct <= 0.10 THEN 'Light (up to 10%)'
        WHEN discount_pct <= 0.15 THEN 'Medium (11-15%)'
        ELSE 'Heavy (16%+)'
    END AS discount_band,
    COUNT(*) AS order_lines,
    ROUND(AVG(quantity), 2) AS avg_units_per_line,
    ROUND(SUM(quantity * unit_price_usd * (1 - discount_pct)), 2) AS net_revenue_usd
FROM sales_orders
GROUP BY discount_band
ORDER BY net_revenue_usd DESC;

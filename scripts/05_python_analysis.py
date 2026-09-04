"""
05_python_analysis.py

Core Python analysis for "Retail Sales & Inventory Performance Analytics".
Computes revenue, inventory turnover, stockout risk, and return-rate
metrics, and produces the supporting charts.

IMPORTANT DATA NOTE: `stock_movements.quantity` is signed (positive = stock
in: opening balance / goods receipt / customer return; negative = stock
out: goods issue for a sale). A plain running sum gives the inventory
position over time -- see sql/analysis_queries.sql Q3 for the SQL
equivalent of this same logic.
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import sqlite3
import os

sns.set_style("whitegrid")
OUT = "outputs"
os.makedirs(OUT, exist_ok=True)

conn = sqlite3.connect("db/sap_retail.db")
material = pd.read_sql("SELECT * FROM dim_material", conn)
plant = pd.read_sql("SELECT * FROM dim_plant", conn)
listing = pd.read_sql("SELECT * FROM plant_material_listing", conn)
orders = pd.read_sql("SELECT * FROM sales_orders", conn, parse_dates=["order_date"])
movements = pd.read_sql("SELECT * FROM stock_movements", conn, parse_dates=["movement_date"])
conn.close()

orders = orders.merge(material, on="material_id", how="left").merge(plant, on="plant_id", how="left")
orders["net_revenue"] = orders["quantity"] * orders["unit_price_usd"] * (1 - orders["discount_pct"])

# ---------------------------------------------------------------------------
# METRIC 1: TOTAL NET REVENUE, UNITS SOLD, RETURN RATE
# ---------------------------------------------------------------------------
total_revenue = orders["net_revenue"].sum()
total_units = orders["quantity"].sum()
total_returned = orders["units_returned"].sum()
overall_return_rate = total_returned / total_units

# ---------------------------------------------------------------------------
# METRIC 2: STOCKOUT RATE (share of plant/SKU combos that ever ran negative)
# ---------------------------------------------------------------------------
movements_sorted = movements.sort_values(["plant_id", "material_id", "movement_date", "movement_id"])
movements_sorted["running_stock"] = movements_sorted.groupby(["plant_id", "material_id"])["quantity"].cumsum()
stockout_flags = movements_sorted.groupby(["plant_id", "material_id"])["running_stock"].min() < 0
overall_stockout_rate = stockout_flags.mean()

# days spent in a stockout state per plant/material (a "severity" measure
# beyond a simple yes/no flag)
def days_in_stockout(group):
    group = group.sort_values("movement_date")
    dates = group["movement_date"].values
    stock = group["running_stock"].values
    if len(dates) < 2:
        return 0
    total_days = 0
    for i in range(len(dates) - 1):
        if stock[i] < 0:
            total_days += (dates[i+1] - dates[i]).astype("timedelta64[D]").astype(int)
    return total_days

stockout_days = movements_sorted.groupby(["plant_id", "material_id"]).apply(days_in_stockout, include_groups=False)
stockout_days.name = "days_in_stockout"

# ---------------------------------------------------------------------------
# METRIC 3: INVENTORY TURNOVER (units sold / units received, per SKU)
# ---------------------------------------------------------------------------
sales_by_sku = orders.groupby("material_id")["quantity"].sum()
receipts_by_sku = movements[movements.movement_type.isin(["101_GOODS_RECEIPT", "000_OPENING_BALANCE"])].groupby("material_id")["quantity"].sum()
turnover = (sales_by_sku / receipts_by_sku).rename("turnover_ratio")

# ---------------------------------------------------------------------------
# METRIC 4: RETURN RATE BY CATEGORY
# ---------------------------------------------------------------------------
return_by_category = orders.groupby("product_category").apply(
    lambda g: g["units_returned"].sum() / g["quantity"].sum(), include_groups=False
).sort_values(ascending=False)

metrics_summary = pd.DataFrame([
    {"metric": "Total Net Revenue (18 months)", "value": f"${total_revenue:,.0f}"},
    {"metric": "Total Units Sold", "value": f"{total_units:,.0f}"},
    {"metric": "Overall Return Rate", "value": f"{overall_return_rate:.1%}"},
    {"metric": "Stockout Rate (SKU-plant combos ever stocked out)", "value": f"{overall_stockout_rate:.1%}"},
    {"metric": "Median Inventory Turnover Ratio", "value": f"{turnover.median():.2f}x"},
])
metrics_summary.to_csv(f"{OUT}/metrics_summary.csv", index=False)
print(metrics_summary.to_string(index=False))

# ---------------------------------------------------------------------------
# CHART 1: NET REVENUE BY COUNTRY
# ---------------------------------------------------------------------------
rev_by_country = orders.groupby("country")["net_revenue"].sum().sort_values()
plt.figure(figsize=(8, 5))
plt.barh(rev_by_country.index, rev_by_country.values, color="steelblue")
plt.title("Net Revenue by Country (18-month window)")
plt.xlabel("Net Revenue (USD)")
plt.tight_layout()
plt.savefig(f"{OUT}/chart_01_revenue_by_country.png", dpi=150)
plt.close()

# ---------------------------------------------------------------------------
# CHART 2: REVENUE BY CATEGORY
# ---------------------------------------------------------------------------
rev_by_cat = orders.groupby("product_category")["net_revenue"].sum().sort_values()
plt.figure(figsize=(8, 5))
plt.barh(rev_by_cat.index, rev_by_cat.values, color="darkorange")
plt.title("Net Revenue by Product Category")
plt.xlabel("Net Revenue (USD)")
plt.tight_layout()
plt.savefig(f"{OUT}/chart_02_revenue_by_category.png", dpi=150)
plt.close()

# ---------------------------------------------------------------------------
# CHART 3: MONTHLY REVENUE TREND BY REGION
# ---------------------------------------------------------------------------
orders["year_month"] = orders["order_date"].dt.to_period("M").astype(str)
monthly_region = orders.groupby(["year_month", "region"])["net_revenue"].sum().unstack()
plt.figure(figsize=(10, 5.5))
for region in monthly_region.columns:
    plt.plot(monthly_region.index, monthly_region[region], marker="o", markersize=3, label=region)
plt.title("Monthly Net Revenue by Region")
plt.ylabel("Net Revenue (USD)")
plt.xticks(rotation=45, ha="right")
plt.legend()
plt.tight_layout()
plt.savefig(f"{OUT}/chart_03_monthly_revenue_by_region.png", dpi=150)
plt.close()

# ---------------------------------------------------------------------------
# CHART 4: STOCKOUT RATE BY COUNTRY AND CATEGORY (heatmap)
# ---------------------------------------------------------------------------
stockout_df = stockout_flags.reset_index()
stockout_df.columns = ["plant_id", "material_id", "ever_stocked_out"]
stockout_df = stockout_df.merge(plant, on="plant_id", how="left").merge(material[["material_id", "product_category"]], on="material_id", how="left")
pivot = stockout_df.groupby(["country", "product_category"])["ever_stocked_out"].mean().unstack() * 100

plt.figure(figsize=(9, 5.5))
sns.heatmap(pivot, annot=True, fmt=".0f", cmap="Reds", cbar_kws={"label": "Stockout rate (%)"})
plt.title("Stockout Rate (%) by Country and Category")
plt.ylabel("")
plt.xlabel("")
plt.tight_layout()
plt.savefig(f"{OUT}/chart_04_stockout_heatmap.png", dpi=150)
plt.close()

# ---------------------------------------------------------------------------
# CHART 5: RETURN RATE BY CATEGORY
# ---------------------------------------------------------------------------
plt.figure(figsize=(7.5, 4.5))
plt.barh(return_by_category.index[::-1], (return_by_category.values * 100)[::-1], color="indianred")
plt.title("Return Rate by Product Category")
plt.xlabel("Return Rate (%)")
plt.tight_layout()
plt.savefig(f"{OUT}/chart_05_return_rate_by_category.png", dpi=150)
plt.close()

# ---------------------------------------------------------------------------
# CHART 6: INVENTORY TURNOVER DISTRIBUTION
# ---------------------------------------------------------------------------
turnover_capped = turnover.clip(upper=turnover.quantile(0.97))
plt.figure(figsize=(7.5, 4.5))
sns.histplot(turnover_capped.dropna(), bins=30, color="teal")
plt.axvline(1.0, color="black", linestyle="--", label="Sold = Received (1.0x)")
plt.title("Inventory Turnover Ratio Across SKUs\n(units sold / units received, capped at 97th pct)")
plt.xlabel("Turnover Ratio")
plt.legend()
plt.tight_layout()
plt.savefig(f"{OUT}/chart_06_turnover_distribution.png", dpi=150)
plt.close()

# ---------------------------------------------------------------------------
# CHART 7: TOP 10 SKUs BY REVENUE
# ---------------------------------------------------------------------------
top_skus = orders.groupby(["material_id", "material_description", "brand"])["net_revenue"].sum().nlargest(10).reset_index()
top_skus["label"] = top_skus["material_description"].str[:30] + " (" + top_skus["brand"] + ")"
plt.figure(figsize=(9, 5.5))
plt.barh(top_skus["label"][::-1], top_skus["net_revenue"][::-1], color="mediumseagreen")
plt.title("Top 10 SKUs by Net Revenue")
plt.xlabel("Net Revenue (USD)")
plt.tight_layout()
plt.savefig(f"{OUT}/chart_07_top_skus.png", dpi=150)
plt.close()

# ---------------------------------------------------------------------------
# CHART 8: DISCOUNT BAND VS. AVERAGE UNITS PER ORDER LINE
# ---------------------------------------------------------------------------
def discount_band(d):
    if d == 0:
        return "No discount"
    elif d <= 0.10:
        return "Light (<=10%)"
    elif d <= 0.15:
        return "Medium (11-15%)"
    else:
        return "Heavy (16%+)"
orders["discount_band"] = orders["discount_pct"].apply(discount_band)
band_order = ["No discount", "Light (<=10%)", "Medium (11-15%)", "Heavy (16%+)"]
band_avg = orders.groupby("discount_band")["quantity"].mean().reindex(band_order)

plt.figure(figsize=(7, 4.5))
plt.bar(band_avg.index, band_avg.values, color="slateblue")
plt.title("Average Units per Order Line by Discount Band")
plt.ylabel("Avg. units per order line")
plt.tight_layout()
plt.savefig(f"{OUT}/chart_08_discount_vs_volume.png", dpi=150)
plt.close()

# Save master tables for BI tools
orders.to_csv(f"{OUT}/flat_sales_orders_for_bi.csv", index=False)
stockout_summary = stockout_df.merge(turnover.reset_index(), on="material_id", how="left")
stockout_summary.to_csv(f"{OUT}/flat_stockout_turnover_for_bi.csv", index=False)

print("\nAll charts saved to outputs/.")
print(f"\nReturn rate by category:\n{(return_by_category*100).round(2)}")

"""
01_prepare_material_master.py

Takes the REAL Sephora product catalog (product_info.csv — ~8,500 real
products, 304 real brands, sourced from the well-known Kaggle "Sephora
Products and Skincare Reviews" dataset) and reshapes it into an SAP-style
material master (MARA/MAKT-equivalent): one row per material (SKU), with
the fields a retail SAP system would actually carry.

This is the ONE part of the dataset that is real, not synthetic — the
product names, brands, categories, and prices are genuine. Everything
downstream (which of these SKUs are actually stocked in which market, sales
orders, stock movements) is synthetic, because no company publishes their
real SAP transactional tables.

We then select a curated "active assortment" -- not all 8,494 products get
transactional history. This mirrors a real regional merchandising decision
(a market doesn't stock the entire global catalog) and keeps the
transactional dataset a manageable, focused size instead of an unrealistic
"every SKU sells everywhere" scenario.
"""

import pandas as pd
import numpy as np
import random

random.seed(42)
np.random.seed(42)

raw = pd.read_csv("data/raw/sephora_product_info.csv")

# ---------------------------------------------------------------------------
# CLEAN / RESHAPE INTO A MATERIAL MASTER
# ---------------------------------------------------------------------------
mara = raw[[
    "product_id", "product_name", "brand_name", "primary_category",
    "secondary_category", "price_usd", "rating", "loves_count", "reviews",
]].copy()

mara.columns = [
    "material_id", "material_description", "brand", "product_category",
    "product_subcategory", "list_price_usd", "avg_rating", "loves_count", "review_count",
]

# Drop rows with no usable price or category (can't build a pricing/stock
# model without them) -- a normal material-master data-quality step
before = len(mara)
mara = mara.dropna(subset=["list_price_usd", "product_category"])
mara["material_description"] = mara["material_description"].fillna("Unknown Product")
mara["brand"] = mara["brand"].fillna("Unknown Brand")
print(f"Material master: {before} raw products -> {len(mara)} with usable price/category")

# Standard cost estimate (SAP would carry this separately from list price;
# we approximate it as a category-typical margin, since real margin data
# isn't public) -- used later for a rough "value at risk" stockout metric
CATEGORY_MARGIN = {
    "Skincare": 0.62, "Makeup": 0.58, "Fragrance": 0.70,
    "Hair": 0.55, "Bath & Body": 0.60, "Mini Size": 0.55,
    "Men": 0.58, "Tools & Brushes": 0.50, "Gifts": 0.60,
}
mara["standard_cost_usd"] = mara.apply(
    lambda r: round(r["list_price_usd"] * (1 - CATEGORY_MARGIN.get(r["product_category"], 0.58)), 2),
    axis=1
)

mara.to_csv("data/clean/material_master_full_catalog.csv", index=False)

# ---------------------------------------------------------------------------
# CURATE THE ACTIVE ASSORTMENT (what actually gets transactional history)
# ---------------------------------------------------------------------------
# Favor higher-popularity items (a real regional assortment leans toward
# proven sellers, not a random sample of the entire catalog), spread across
# the main categories, roughly matching their real category share.

TARGET_ASSORTMENT_SIZE = 220
CATEGORY_SHARE = {  # roughly matches real category proportions, capped to major categories
    "Skincare": 0.30, "Makeup": 0.30, "Fragrance": 0.18,
    "Hair": 0.14, "Bath & Body": 0.08,
}

assortment_parts = []
for cat, share in CATEGORY_SHARE.items():
    n = int(round(TARGET_ASSORTMENT_SIZE * share))
    pool = mara[mara["product_category"] == cat].copy()
    # weight selection toward popularity, but don't make it deterministic top-N only
    pool["_weight"] = np.log1p(pool["loves_count"].fillna(0)) + 1
    pool = pool.sample(n=min(n, len(pool)), weights="_weight", random_state=7)
    assortment_parts.append(pool.drop(columns="_weight"))

assortment = pd.concat(assortment_parts, ignore_index=True).drop_duplicates(subset="material_id")
assortment.to_csv("data/clean/active_assortment.csv", index=False)

print(f"\nActive assortment selected: {len(assortment)} SKUs")
print(assortment["product_category"].value_counts())
print(f"\nPrice range: ${assortment['list_price_usd'].min():.2f} - ${assortment['list_price_usd'].max():.2f}")
print(f"Unique brands in assortment: {assortment['brand'].nunique()}")

"""
04_clean_and_load.py

Cleans the messy SAP-style raw exports and loads everything into a
normalized SQLite database (db/sap_retail.db).

SCHEMA
------
dim_material (material_id PK, material_description, brand, product_category,
              product_subcategory, list_price_usd, standard_cost_usd,
              avg_rating, loves_count, review_count)
dim_plant    (plant_id PK, country, region, channel)
plant_material_listing (plant_id FK, material_id FK)   -- bridge: what's carried where
sales_orders (order_id PK, order_date, plant_id FK, material_id FK, channel,
              quantity, unit_price_usd, discount_pct, units_returned)
stock_movements (movement_id PK, movement_date, plant_id FK, material_id FK,
                  movement_type, quantity)
"""

import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime

pd.set_option("mode.chained_assignment", None)

issues = {}

# ---------------------------------------------------------------------------
# DIMENSION TABLES (already clean from script 01/02 -- loaded as-is, these
# represent the "master data" side which in a real SAP system is governed
# separately from transactional extracts)
# ---------------------------------------------------------------------------
material_master = pd.read_csv("data/clean/active_assortment.csv").drop(columns=["_base_rate"], errors="ignore")
material_master = material_master.rename(columns={
    "material_id": "material_id", "material_description": "material_description"
})
plant_master = pd.read_csv("data/clean/plant_master.csv")
plant_listing = pd.read_csv("data/clean/plant_material_listing.csv")

# ---------------------------------------------------------------------------
# CLEAN SALES ORDERS RAW EXPORT
# ---------------------------------------------------------------------------
so_raw = pd.read_csv("data/raw/sap_sd_sales_orders_raw.csv")
n_so_raw = len(so_raw)

before = len(so_raw)
so_raw = so_raw.drop_duplicates(subset=[c for c in so_raw.columns if c != "order_id"])
issues["sales_orders_exact_duplicates_removed"] = before - len(so_raw)

so_raw["plant_id"] = so_raw["plant_id"].astype(str).str.strip().str.upper()
valid_plants = set(plant_master["plant_id"])
issues["sales_orders_invalid_plant_id"] = int((~so_raw["plant_id"].isin(valid_plants)).sum())
so_raw = so_raw[so_raw["plant_id"].isin(valid_plants)]

CHANNEL_MAP = {
    "online": "Online", "web": "Online",
    "in-store": "In-Store", "store": "In-Store",
    "travel retail": "Travel Retail", "tr": "Travel Retail",
}
so_raw["channel"] = so_raw["channel"].astype(str).str.strip().str.lower().map(CHANNEL_MAP)
issues["sales_orders_channel_unmapped"] = int(so_raw["channel"].isna().sum())
so_raw["channel"] = so_raw["channel"].fillna("Unknown")

DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%d-%b-%Y"]
def parse_messy_date(s):
    s = str(s).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return pd.to_datetime(s, errors="coerce")
so_raw["order_date"] = so_raw["order_date"].apply(parse_messy_date)
issues["sales_orders_unparseable_dates"] = int(so_raw["order_date"].isna().sum())
so_raw = so_raw.dropna(subset=["order_date"])

def clean_price(p):
    if isinstance(p, str):
        p = p.replace("$", "").strip()
    try:
        return float(p)
    except (ValueError, TypeError):
        return np.nan
so_raw["unit_price_usd"] = so_raw["unit_price_usd"].apply(clean_price)

so_raw["discount_pct"] = pd.to_numeric(so_raw["discount_pct"], errors="coerce")
issues["sales_orders_missing_discount_defaulted_zero"] = int(so_raw["discount_pct"].isna().sum())
so_raw["discount_pct"] = so_raw["discount_pct"].fillna(0.0)

so_raw["quantity"] = pd.to_numeric(so_raw["quantity"], errors="coerce")
neg_qty = so_raw["quantity"] < 0
issues["sales_orders_negative_quantity_fixed"] = int(neg_qty.sum())
so_raw["quantity"] = so_raw["quantity"].abs()
so_raw = so_raw.dropna(subset=["quantity"])

so_clean = so_raw[[
    "order_id", "order_date", "plant_id", "material_id", "channel",
    "quantity", "unit_price_usd", "discount_pct", "units_returned"
]].copy()

# ---------------------------------------------------------------------------
# CLEAN STOCK MOVEMENTS RAW EXPORT
# ---------------------------------------------------------------------------
mv_raw = pd.read_csv("data/raw/sap_mm_stock_movements_raw.csv")
n_mv_raw = len(mv_raw)

before = len(mv_raw)
mv_raw = mv_raw.drop_duplicates(subset=[c for c in mv_raw.columns if c != "movement_id"])
issues["stock_movements_exact_duplicates_removed"] = before - len(mv_raw)

mv_raw["plant_id"] = mv_raw["plant_id"].astype(str).str.strip().str.upper()
issues["stock_movements_invalid_plant_id"] = int((~mv_raw["plant_id"].isin(valid_plants)).sum())
mv_raw = mv_raw[mv_raw["plant_id"].isin(valid_plants)]

MOVEMENT_TYPE_MAP = {
    "000_opening_balance": "000_OPENING_BALANCE", "opening balance": "000_OPENING_BALANCE", "000": "000_OPENING_BALANCE",
    "101_goods_receipt": "101_GOODS_RECEIPT", "101": "101_GOODS_RECEIPT", "goods receipt": "101_GOODS_RECEIPT", "gr": "101_GOODS_RECEIPT",
    "601_goods_issue_sale": "601_GOODS_ISSUE_SALE", "601": "601_GOODS_ISSUE_SALE", "goods issue": "601_GOODS_ISSUE_SALE", "gi sale": "601_GOODS_ISSUE_SALE",
    "651_customer_return": "651_CUSTOMER_RETURN", "651": "651_CUSTOMER_RETURN", "customer return": "651_CUSTOMER_RETURN", "return": "651_CUSTOMER_RETURN",
}
mv_raw["movement_type"] = mv_raw["movement_type"].astype(str).str.strip().str.lower().map(MOVEMENT_TYPE_MAP)
issues["stock_movements_type_unmapped"] = int(mv_raw["movement_type"].isna().sum())
mv_raw = mv_raw.dropna(subset=["movement_type"])

mv_raw["movement_date"] = mv_raw["movement_date"].apply(parse_messy_date)
issues["stock_movements_unparseable_dates"] = int(mv_raw["movement_date"].isna().sum())
mv_raw = mv_raw.dropna(subset=["movement_date"])

mv_raw["quantity"] = pd.to_numeric(mv_raw["quantity"], errors="coerce")
issues["stock_movements_missing_quantity_dropped"] = int(mv_raw["quantity"].isna().sum())
mv_raw = mv_raw.dropna(subset=["quantity"])

mv_clean = mv_raw[["movement_id", "movement_date", "plant_id", "material_id", "movement_type", "quantity"]].copy()

# ---------------------------------------------------------------------------
# LOAD INTO SQLITE
# ---------------------------------------------------------------------------
conn = sqlite3.connect("db/sap_retail.db")

material_master.to_sql("dim_material", conn, if_exists="replace", index=False)
plant_master.to_sql("dim_plant", conn, if_exists="replace", index=False)
plant_listing.to_sql("plant_material_listing", conn, if_exists="replace", index=False)
so_clean.to_sql("sales_orders", conn, if_exists="replace", index=False)
mv_clean.to_sql("stock_movements", conn, if_exists="replace", index=False)

conn.execute("CREATE INDEX IF NOT EXISTS idx_so_material ON sales_orders(material_id);")
conn.execute("CREATE INDEX IF NOT EXISTS idx_so_plant ON sales_orders(plant_id);")
conn.execute("CREATE INDEX IF NOT EXISTS idx_mv_material_plant ON stock_movements(material_id, plant_id);")
conn.commit()

so_clean.to_csv("data/clean/sales_orders_clean.csv", index=False)
mv_clean.to_csv("data/clean/stock_movements_clean.csv", index=False)

conn.close()

# ---------------------------------------------------------------------------
# DATA QUALITY REPORT
# ---------------------------------------------------------------------------
print("=" * 65)
print("DATA CLEANING REPORT")
print("=" * 65)
print(f"Sales orders raw rows read:        {n_so_raw}")
print(f"Sales orders clean rows loaded:    {len(so_clean)}")
print(f"Stock movements raw rows read:     {n_mv_raw}")
print(f"Stock movements clean rows loaded: {len(mv_clean)}")
print("-" * 65)
for k, v in issues.items():
    print(f"{k:48s}: {v}")
print("=" * 65)

with open("data/clean/cleaning_report.txt", "w") as f:
    f.write("DATA CLEANING REPORT\n" + "=" * 65 + "\n")
    f.write(f"Sales orders raw rows read:        {n_so_raw}\n")
    f.write(f"Sales orders clean rows loaded:    {len(so_clean)}\n")
    f.write(f"Stock movements raw rows read:     {n_mv_raw}\n")
    f.write(f"Stock movements clean rows loaded: {len(mv_clean)}\n")
    f.write("-" * 65 + "\n")
    for k, v in issues.items():
        f.write(f"{k:48s}: {v}\n")

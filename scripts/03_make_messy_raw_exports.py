"""
03_make_messy_raw_exports.py

Takes the clean synthetic sales orders and stock movements and produces two
messy CSV exports that mimic what you'd actually get pulling data out of
SAP via a transaction like SE16/SE16N or a custom ABAP query into Excel:
inconsistent plant code casing/whitespace, movement types shown as raw
codes vs. descriptive text inconsistently, mixed date formats, a currency
symbol left in some price fields, a few duplicate line items (a common
side-effect of re-running an extract and appending instead of overwriting),
and some missing discount values.
"""

import pandas as pd
import numpy as np
import random

random.seed(21)
np.random.seed(21)

orders = pd.read_csv("data/clean/sales_orders.csv", parse_dates=["order_date"])
movements = pd.read_csv("data/clean/stock_movements.csv", parse_dates=["movement_date"])

# ---------------------------------------------------------------------------
# MESSY SALES ORDERS EXPORT (SD-style)
# ---------------------------------------------------------------------------
so = orders.copy()

PLANT_VARIANTS = lambda p: random.choice([p, p.lower(), f" {p}", f"{p} "])
so["plant_id"] = so["plant_id"].apply(PLANT_VARIANTS)

CHANNEL_VARIANTS = {
    "Online": ["Online", "online", "ONLINE", "Web"],
    "In-Store": ["In-Store", "in-store", "IN-STORE", "Store"],
    "Travel Retail": ["Travel Retail", "travel retail", "TR"],
}
so["channel"] = so["channel"].apply(lambda c: random.choice(CHANNEL_VARIANTS.get(c, [c])))

def messy_date(d):
    fmt = random.choice(["%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y", "%d-%b-%Y"])
    return d.strftime(fmt)
so["order_date"] = so["order_date"].apply(messy_date)

# a currency symbol left in on some rows (classic Excel-export artifact)
def messy_price(p):
    if random.random() < 0.08:
        return f"${p:.2f}"
    return p
so["unit_price_usd"] = so["unit_price_usd"].apply(messy_price)

# missing discount on some rows
missing_disc = np.random.random(len(so)) < 0.07
so.loc[missing_disc, "discount_pct"] = np.nan

# a few negative-quantity typos (should never be negative on a sales line)
neg_idx = so.sample(frac=0.01, random_state=5).index
so.loc[neg_idx, "quantity"] = -so.loc[neg_idx, "quantity"].abs()

# duplicate a few rows (re-run-of-extract artifact)
dup = so.sample(frac=0.015, random_state=6)
so = pd.concat([so, dup], ignore_index=True)
so = so.sample(frac=1.0, random_state=99).reset_index(drop=True)

so.to_csv("data/raw/sap_sd_sales_orders_raw.csv", index=False)
print(f"Messy sales orders export: {len(so)} rows -> data/raw/sap_sd_sales_orders_raw.csv")

# ---------------------------------------------------------------------------
# MESSY STOCK MOVEMENTS EXPORT (MM-style)
# ---------------------------------------------------------------------------
mv = movements.copy()

MOVEMENT_TEXT_VARIANTS = {
    "000_OPENING_BALANCE": ["000_OPENING_BALANCE", "Opening Balance", "000"],
    "101_GOODS_RECEIPT": ["101_GOODS_RECEIPT", "101", "Goods Receipt", "GR"],
    "601_GOODS_ISSUE_SALE": ["601_GOODS_ISSUE_SALE", "601", "Goods Issue", "GI Sale"],
    "651_CUSTOMER_RETURN": ["651_CUSTOMER_RETURN", "651", "Customer Return", "Return"],
}
mv["movement_type"] = mv["movement_type"].apply(lambda t: random.choice(MOVEMENT_TEXT_VARIANTS[t]))
mv["plant_id"] = mv["plant_id"].apply(PLANT_VARIANTS)
mv["movement_date"] = mv["movement_date"].apply(messy_date)

# a handful of missing quantities
missing_qty = np.random.random(len(mv)) < 0.02
mv.loc[missing_qty, "quantity"] = np.nan

dup2 = mv.sample(frac=0.01, random_state=8)
mv = pd.concat([mv, dup2], ignore_index=True)
mv = mv.sample(frac=1.0, random_state=100).reset_index(drop=True)

mv.to_csv("data/raw/sap_mm_stock_movements_raw.csv", index=False)
print(f"Messy stock movements export: {len(mv)} rows -> data/raw/sap_mm_stock_movements_raw.csv")

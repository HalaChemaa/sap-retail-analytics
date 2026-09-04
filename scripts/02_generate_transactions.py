"""
02_generate_transactions.py

Generates the synthetic SAP-style transactional layer on top of the real
active assortment: a plant/market master (SAP plant-equivalent), sales
orders (SD module: VBAK/VBAP-style header + line items), and stock
movements (MM module: MSEG-style goods receipts, issues, transfers, and
returns).

DESIGN NOTE ON REALISM:
Sales volume per SKU is driven by a noisy function of the SKU's real
popularity (loves_count/rating from the actual Sephora data) and the
market it's sold in -- not hard-coded. Stockouts emerge naturally from the
interaction between sales velocity and replenishment timing, they are not
manufactured to appear at convenient moments.
"""

import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta

random.seed(11)
np.random.seed(11)

assortment = pd.read_csv("data/clean/active_assortment.csv")

OBS_START = datetime(2024, 1, 1)
OBS_END = datetime(2025, 6, 30)

# ---------------------------------------------------------------------------
# PLANT / MARKET MASTER (SAP plant-equivalent)
# ---------------------------------------------------------------------------
PLANTS = [
    {"plant_id": "FR10", "country": "France",   "region": "Europe",       "channel": "Flagship Retail"},
    {"plant_id": "FR90", "country": "France",   "region": "Europe",       "channel": "Distribution Center"},
    {"plant_id": "UK10", "country": "United Kingdom", "region": "Europe", "channel": "Retail"},
    {"plant_id": "DE10", "country": "Germany",  "region": "Europe",       "channel": "Retail"},
    {"plant_id": "US10", "country": "United States", "region": "Americas","channel": "Retail"},
    {"plant_id": "US20", "country": "United States", "region": "Americas","channel": "Online Fulfillment"},
    {"plant_id": "AE10", "country": "United Arab Emirates", "region": "Middle East", "channel": "Travel Retail"},
    {"plant_id": "MA10", "country": "Morocco",  "region": "Middle East & Africa", "channel": "Retail"},
]
plants_df = pd.DataFrame(PLANTS)

# Relative demand-scale multiplier per plant (reflects store size / market
# maturity -- distribution centers don't sell directly to consumers, they
# only receive/transfer stock)
PLANT_DEMAND_SCALE = {
    "FR10": 1.3, "FR90": 0.0, "UK10": 1.1, "DE10": 0.9,
    "US10": 1.5, "US20": 1.2, "AE10": 0.8, "MA10": 0.4,
}

plants_df.to_csv("data/clean/plant_master.csv", index=False)

# ---------------------------------------------------------------------------
# WHICH SKUs ARE LISTED AT WHICH PLANT (not every plant carries everything)
# ---------------------------------------------------------------------------
listings = []
for _, plant in plants_df.iterrows():
    if plant["channel"] == "Distribution Center":
        continue  # DCs hold stock but aren't a point of sale
    # each retail/online plant carries 65-95% of the assortment
    carry_rate = np.random.uniform(0.65, 0.95)
    carried = assortment.sample(frac=carry_rate, random_state=hash(plant["plant_id"]) % (2**32)).copy()
    for _, sku in carried.iterrows():
        listings.append({"plant_id": plant["plant_id"], "material_id": sku["material_id"]})
listings_df = pd.DataFrame(listings)
listings_df.to_csv("data/clean/plant_material_listing.csv", index=False)
print(f"Plant-material listings: {len(listings_df)}")

# ---------------------------------------------------------------------------
# SALES ORDERS (SD module: header + line items)
# ---------------------------------------------------------------------------
# Popularity-driven daily demand rate per SKU (mean units/day, before plant scaling)
def base_daily_rate(row):
    popularity = np.log1p(row["loves_count"]) if pd.notna(row["loves_count"]) else 5
    price_drag = 1 / (1 + row["list_price_usd"] / 60)  # cheaper items sell more units
    return 0.015 * popularity * price_drag + 0.01

assortment["_base_rate"] = assortment.apply(base_daily_rate, axis=1)
sku_lookup = assortment.set_index("material_id")

order_rows = []
order_id_counter = 100000

n_days = (OBS_END - OBS_START).days + 1
dates = [OBS_START + timedelta(days=d) for d in range(n_days)]

sales_plants = listings_df["plant_id"].unique()

for plant_id in sales_plants:
    scale = PLANT_DEMAND_SCALE[plant_id]
    plant_skus = listings_df.loc[listings_df.plant_id == plant_id, "material_id"].tolist()
    for material_id in plant_skus:
        row = sku_lookup.loc[material_id]
        daily_rate = row["_base_rate"] * scale
        if daily_rate <= 0:
            continue
        # Simulate a Poisson-ish arrival of sales days, with mild weekly seasonality
        for d in dates:
            weekday_boost = 1.4 if d.weekday() in (4, 5) else 1.0  # Fri/Sat busier
            lam = daily_rate * weekday_boost
            units_sold = np.random.poisson(lam)
            if units_sold <= 0:
                continue
            channel_type = "Online" if "Online" in plants_df.set_index("plant_id").loc[plant_id, "channel"] else \
                           ("Travel Retail" if "Travel" in plants_df.set_index("plant_id").loc[plant_id, "channel"] else "In-Store")
            unit_price = row["list_price_usd"]
            discount_pct = np.random.choice([0, 0, 0, 0.1, 0.15, 0.2], p=[0.65, 0.1, 0.05, 0.1, 0.06, 0.04])
            order_rows.append({
                "order_id": order_id_counter,
                "order_date": d,
                "plant_id": plant_id,
                "material_id": material_id,
                "channel": channel_type,
                "quantity": int(units_sold),
                "unit_price_usd": round(unit_price, 2),
                "discount_pct": discount_pct,
            })
            order_id_counter += 1

sales_orders = pd.DataFrame(order_rows)
print(f"Sales order lines generated: {len(sales_orders)}")

# ---------------------------------------------------------------------------
# RETURNS (a fraction of sold units come back, category-dependent)
# ---------------------------------------------------------------------------
CATEGORY_RETURN_RATE = {
    "Skincare": 0.05, "Makeup": 0.09, "Fragrance": 0.03,
    "Hair": 0.04, "Bath & Body": 0.02,
}
sales_orders = sales_orders.merge(
    assortment[["material_id", "product_category"]], on="material_id", how="left"
)
sales_orders["return_rate"] = sales_orders["product_category"].map(CATEGORY_return_rate := CATEGORY_RETURN_RATE).fillna(0.04)
sales_orders["units_returned"] = np.random.binomial(sales_orders["quantity"].clip(upper=20), sales_orders["return_rate"])

sales_orders.drop(columns=["return_rate"], inplace=True)
sales_orders.to_csv("data/clean/sales_orders.csv", index=False)

# ---------------------------------------------------------------------------
# STOCK MOVEMENTS (MM module: goods receipts, issues, transfers, returns)
# ---------------------------------------------------------------------------
# Goods Issue (601) mirrors each sales order line (stock leaving due to a sale)
# Customer Return (651) mirrors units_returned
# Goods Receipt (101) is periodic replenishment from the DC to each plant,
#   sized to roughly cover recent sales velocity with some lead-time lag and
#   occasional under-ordering (this is what creates realistic stockouts)

movement_rows = []
movement_id_counter = 1

# Opening stock balance (SAP would carry this as an initial stock upload,
# not from thin air) -- sized to roughly cover the first ~18 days of
# expected demand for that SKU/plant, so the observation window doesn't
# open in an artificial permanent stockout.
for _, listing in listings_df.iterrows():
    plant_id, material_id = listing["plant_id"], listing["material_id"]
    daily_rate = sku_lookup.loc[material_id, "_base_rate"] * PLANT_DEMAND_SCALE[plant_id]
    opening_qty = max(3, int(round(daily_rate * np.random.uniform(12, 24))))
    movement_rows.append({
        "movement_id": movement_id_counter, "movement_date": OBS_START - timedelta(days=1),
        "plant_id": plant_id, "material_id": material_id,
        "movement_type": "000_OPENING_BALANCE", "quantity": opening_qty,
    })
    movement_id_counter += 1

for _, r in sales_orders.iterrows():
    movement_rows.append({
        "movement_id": movement_id_counter, "movement_date": r["order_date"],
        "plant_id": r["plant_id"], "material_id": r["material_id"],
        "movement_type": "601_GOODS_ISSUE_SALE", "quantity": -int(r["quantity"]),
    })
    movement_id_counter += 1
    if r["units_returned"] > 0:
        movement_rows.append({
            "movement_id": movement_id_counter,
            "movement_date": r["order_date"] + timedelta(days=random.randint(3, 14)),
            "plant_id": r["plant_id"], "material_id": r["material_id"],
            "movement_type": "651_CUSTOMER_RETURN", "quantity": int(r["units_returned"]),
        })
        movement_id_counter += 1

# Periodic replenishment (goods receipt) every ~14 days per plant/SKU,
# sized on trailing 14-day sales with noise and occasional shortfall
sales_orders["order_date"] = pd.to_datetime(sales_orders["order_date"])
for plant_id in sales_plants:
    plant_sales = sales_orders[sales_orders.plant_id == plant_id]
    for material_id in plant_sales["material_id"].unique():
        sku_sales = plant_sales[plant_sales.material_id == material_id].set_index("order_date")["quantity"]
        replen_dates = pd.date_range(OBS_START, OBS_END, freq="14D")
        for rd in replen_dates:
            window_start = rd - timedelta(days=14)
            recent_sales = sku_sales[(sku_sales.index >= window_start) & (sku_sales.index < rd)].sum()
            if recent_sales == 0:
                continue
            # replenish to roughly cover the next window, with noise and
            # occasional deliberate under-order (supply constraint / forecast miss)
            under_order_factor = np.random.choice([1.0, 1.0, 1.0, 0.5, 0.3], p=[0.55, 0.15, 0.1, 0.12, 0.08])
            receipt_qty = max(1, int(round(recent_sales * under_order_factor * np.random.uniform(0.9, 1.3))))
            movement_rows.append({
                "movement_id": movement_id_counter, "movement_date": rd,
                "plant_id": plant_id, "material_id": material_id,
                "movement_type": "101_GOODS_RECEIPT", "quantity": receipt_qty,
            })
            movement_id_counter += 1

stock_movements = pd.DataFrame(movement_rows)
stock_movements.to_csv("data/clean/stock_movements.csv", index=False)

print(f"Stock movement lines generated: {len(stock_movements)}")
print(stock_movements["movement_type"].value_counts())
print(f"\nTotal units sold across all markets: {int(sales_orders['quantity'].sum())}")
print(f"Total units returned: {int(sales_orders['units_returned'].sum())}")

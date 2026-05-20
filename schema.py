"""Shared CSV schema for synthetic and scraped price feeds."""

from __future__ import annotations

SCHEMA_COLUMNS: list[str] = [
    "date",
    "city",
    "category",
    "vendor_product_name",
    "normalized_category",
    "platform",
    "cpi_price_inr",
    "app_price_inr",
    "app_premium_pct",
    "app_price_parsed",
    "cpi_mom_change_pct",
    "app_daily_return_pct",
    "rolling_14d_app_volatility_pct",
    "is_perishable",
    "cpi_lag_weeks",
]

CITIES: list[str] = ["Delhi", "Mumbai", "Bengaluru"]

# Regional multipliers applied on top of national baselines
CITY_CONFIG: dict[str, dict[str, float]] = {
    "Delhi": {
        "convenience_markup": 0.06,
        "perishable_spike_multiplier": 1.45,
        "base_price_multiplier": 1.02,
    },
    "Mumbai": {
        "convenience_markup": 0.12,
        "perishable_spike_multiplier": 1.0,
        "base_price_multiplier": 1.08,
    },
    "Bengaluru": {
        "convenience_markup": 0.08,
        "perishable_spike_multiplier": 1.15,
        "base_price_multiplier": 1.05,
    },
}

CITY_PINCODES: dict[str, str] = {
    "Delhi": "110001",
    "Mumbai": "400001",
    "Bengaluru": "560001",
}

SCRAPE_CATEGORIES: list[str] = [
    "Rice",
    "Milk",
    "Onions",
    "Tomatoes",
    "Cooking Oil",
]

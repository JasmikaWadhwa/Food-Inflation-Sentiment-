"""
Synthetic market history generator for Food Inflation Sentiment vs. Official CPI.

Simulates quick-commerce (Blinkit/BigBasket-style) price feeds across Indian metro
zones (Delhi, Mumbai, Bengaluru) and national CPI baselines with regional markup,
seasonal perishable spikes, and vendor string normalization.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from schema import CITY_CONFIG, CITIES, SCHEMA_COLUMNS

# --- National classification mapping (fuzzy vendor strings → CPI categories) ---

NORMALIZATION_RULES: list[tuple[str, str]] = [
    (r"tomato|tamatar", "Tomatoes"),
    (r"onion|pyaz", "Onions"),
    (r"potato|aloo", "Potatoes"),
    (r"rice|chawal|basmati", "Rice"),
    (r"wheat|atta|flour", "Wheat Flour"),
    (r"milk|doodh", "Milk"),
    (r"egg|anda", "Eggs"),
    (r"oil|sunflower|mustard", "Cooking Oil"),
    (r"dal|lentil|moong|toor", "Pulses"),
    (r"sugar|chini", "Sugar"),
]

VENDOR_NAME_POOL: dict[str, list[str]] = {
    "Tomatoes": [
        "Premium Farm Tomatoes 1kg",
        "Hybrid Tamatar Pack 500g",
        "Fresh Red Tomato 1kg",
    ],
    "Onions": [
        "Premium Farm Onions 1kg",
        "Nasik Red Onion 1kg",
        "Organic Pyaz 500g",
    ],
    "Potatoes": [
        "Aloo Fresh 1kg",
        "Baby Potato Pack 500g",
        "Premium Potato 2kg",
    ],
    "Rice": [
        "Basmati Rice 5kg",
        "Sona Masoori 1kg",
        "Brown Rice Premium 1kg",
    ],
    "Wheat Flour": [
        "Aashirvaad Atta 5kg",
        "Whole Wheat Flour 1kg",
        "Multigrain Atta 2kg",
    ],
    "Milk": [
        "Amul Taaza 1L",
        "Full Cream Milk 500ml",
        "Organic Cow Milk 1L",
    ],
    "Eggs": [
        "Farm Fresh Eggs 6pc",
        "Brown Eggs 12pc",
        "Free Range Anda 6pc",
    ],
    "Cooking Oil": [
        "Sunflower Oil 1L",
        "Fortune Mustard Oil 1L",
        "Refined Oil 500ml",
    ],
    "Pulses": [
        "Toor Dal 1kg",
        "Moong Dal Split 500g",
        "Chana Dal Premium 1kg",
    ],
    "Sugar": [
        "Madhur Sugar 1kg",
        "Brown Sugar 500g",
        "Refined Chini 1kg",
    ],
}

VOLATILITY_PROFILE: dict[str, dict[str, float]] = {
    "Tomatoes": {"app_daily_sigma": 0.045, "cpi_monthly_sigma": 0.012, "cpi_lag_weeks": 2},
    "Onions": {"app_daily_sigma": 0.038, "cpi_monthly_sigma": 0.010, "cpi_lag_weeks": 2},
    "Potatoes": {"app_daily_sigma": 0.022, "cpi_monthly_sigma": 0.008, "cpi_lag_weeks": 3},
    "Rice": {"app_daily_sigma": 0.006, "cpi_monthly_sigma": 0.004, "cpi_lag_weeks": 4},
    "Wheat Flour": {"app_daily_sigma": 0.007, "cpi_monthly_sigma": 0.004, "cpi_lag_weeks": 4},
    "Milk": {"app_daily_sigma": 0.009, "cpi_monthly_sigma": 0.005, "cpi_lag_weeks": 3},
    "Eggs": {"app_daily_sigma": 0.015, "cpi_monthly_sigma": 0.006, "cpi_lag_weeks": 3},
    "Cooking Oil": {"app_daily_sigma": 0.008, "cpi_monthly_sigma": 0.005, "cpi_lag_weeks": 4},
    "Pulses": {"app_daily_sigma": 0.010, "cpi_monthly_sigma": 0.005, "cpi_lag_weeks": 4},
    "Sugar": {"app_daily_sigma": 0.007, "cpi_monthly_sigma": 0.004, "cpi_lag_weeks": 4},
}

PREMIUM_BY_CATEGORY: dict[str, float] = {
    "Tomatoes": 0.14,
    "Onions": 0.12,
    "Potatoes": 0.10,
    "Rice": 0.08,
    "Wheat Flour": 0.09,
    "Milk": 0.11,
    "Eggs": 0.13,
    "Cooking Oil": 0.15,
    "Pulses": 0.10,
    "Sugar": 0.18,
}

BASE_PRICES_INR: dict[str, float] = {
    "Tomatoes": 42.0,
    "Onions": 35.0,
    "Potatoes": 28.0,
    "Rice": 62.0,
    "Wheat Flour": 48.0,
    "Milk": 58.0,
    "Eggs": 72.0,
    "Cooking Oil": 145.0,
    "Pulses": 110.0,
    "Sugar": 48.0,
}

PLATFORMS = ["Blinkit", "BigBasket"]
RNG = np.random.default_rng(42)
DELHI_PERISHABLES = {"Tomatoes", "Onions"}


def normalize_vendor_name(raw_name: str) -> str | None:
    """Map arbitrary vendor inventory strings to national CPI categories."""
    lowered = raw_name.lower()
    for pattern, category in NORMALIZATION_RULES:
        if re.search(pattern, lowered):
            return category
    return None


def parse_price_string(price_str: str) -> float:
    """Convert scraped price strings (₹42.50, Rs 42, etc.) to float INR."""
    cleaned = re.sub(r"[^\d.]", "", price_str.replace(",", ""))
    return float(cleaned) if cleaned else np.nan


def _rolling_mean(series: np.ndarray, window: int) -> np.ndarray:
    out = np.empty_like(series)
    for i in range(len(series)):
        start = max(0, i - window + 1)
        out[i] = series[start : i + 1].mean()
    return out


def _seasonal_delhi_spike(day_idx: int, n_days: int, category: str, city: str) -> float:
    """Delhi: stronger monsoon/summer onion & tomato volatility."""
    if city != "Delhi" or category not in DELHI_PERISHABLES:
        return 1.0
    phase = 2 * np.pi * (day_idx / max(n_days, 1))
    monsoon = 1 + 0.22 * np.sin(phase * 3.2 + (0.5 if category == "Onions" else 0.0))
    summer = 1 + 0.18 * np.sin(phase * 5.1 + 1.2)
    return float(CITY_CONFIG["Delhi"]["perishable_spike_multiplier"] * (0.85 * monsoon + 0.15 * summer))


def generate_market_history(
    start_date: str = "2024-01-01",
    end_date: str = "2025-12-31",
    output_path: str | Path = "food_inflation_data.csv",
) -> pd.DataFrame:
    """Build unified historical price database with app and CPI series per Indian city."""
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    n_days = len(dates)
    rows: list[dict] = []

    for city in CITIES:
        city_cfg = CITY_CONFIG[city]
        city_seed = abs(hash(city)) % 10_000
        city_rng = np.random.default_rng(42 + city_seed)

        for category, national_base in BASE_PRICES_INR.items():
            profile = VOLATILITY_PROFILE[category]
            premium = PREMIUM_BY_CATEGORY[category]
            lag_days = int(profile["cpi_lag_weeks"] * 7)

            base = national_base * city_cfg["base_price_multiplier"]
            sigma = profile["app_daily_sigma"]
            if category in DELHI_PERISHABLES and city == "Delhi":
                sigma *= city_cfg["perishable_spike_multiplier"] * 0.35 + 1.0

            market_shocks = city_rng.normal(0, sigma, size=n_days)
            for day_idx in range(n_days):
                market_shocks[day_idx] *= _seasonal_delhi_spike(day_idx, n_days, category, city)

            market_level = base * np.cumprod(1 + market_shocks)
            cpi_anchor = _rolling_mean(market_level, window=30)
            cpi_smoothed = np.roll(cpi_anchor, lag_days)
            cpi_smoothed[:lag_days] = cpi_anchor[:lag_days]

            city_markup = city_cfg["convenience_markup"]
            premium_noise = city_rng.uniform(-0.02, 0.02, size=n_days)
            effective_premium = np.clip(
                premium + city_markup + premium_noise,
                0.08,
                0.28 if city == "Mumbai" else 0.22,
            )

            for day_idx, dt in enumerate(dates):
                cpi_price = round(float(cpi_smoothed[day_idx]), 2)
                app_price = round(float(cpi_price * (1 + effective_premium[day_idx])), 2)
                premium_pct = round((app_price / cpi_price - 1) * 100, 2) if cpi_price else np.nan

                window_start = max(0, day_idx - 13)
                app_window = market_level[window_start : day_idx + 1]
                app_vol = (
                    float(np.std(app_window) / np.mean(app_window) * 100)
                    if len(app_window) > 1
                    else 0.0
                )

                vendor_raw = city_rng.choice(VENDOR_NAME_POOL[category])
                mapped = normalize_vendor_name(vendor_raw)
                platform = city_rng.choice(PLATFORMS)

                rows.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "city": city,
                        "category": category,
                        "vendor_product_name": vendor_raw,
                        "normalized_category": mapped,
                        "platform": platform,
                        "cpi_price_inr": cpi_price,
                        "app_price_inr": app_price,
                        "app_premium_pct": premium_pct,
                        "app_price_parsed": parse_price_string(f"₹{app_price:.2f}"),
                        "cpi_mom_change_pct": round(
                            (cpi_price / cpi_smoothed[max(0, day_idx - 30)] - 1) * 100,
                            3,
                        )
                        if day_idx >= 30
                        else 0.0,
                        "app_daily_return_pct": round(
                            (market_level[day_idx] / market_level[max(0, day_idx - 1)] - 1) * 100,
                            3,
                        )
                        if day_idx > 0
                        else 0.0,
                        "rolling_14d_app_volatility_pct": round(app_vol, 3),
                        "is_perishable": category in ("Tomatoes", "Onions", "Potatoes"),
                        "cpi_lag_weeks": profile["cpi_lag_weeks"],
                    }
                )

    df = pd.DataFrame(rows)[SCHEMA_COLUMNS]
    df = df.drop_duplicates(subset=["date", "city", "category", "platform"], keep="first")
    df = df.sort_values(["date", "city", "category", "platform"]).reset_index(drop=True)

    out = Path(output_path)
    df.to_csv(out, index=False)
    print(f"Wrote {len(df):,} rows → {out.resolve()}")
    return df


if __name__ == "__main__":
    generate_market_history()

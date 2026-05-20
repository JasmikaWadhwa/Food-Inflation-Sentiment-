"""
Quick-commerce price scraper (Blinkit / BigBasket) with defensive --mock fallback.

Outputs CSV aligned with food_inflation_data.csv so app.py can load live or
fallback data when sites block automation.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from data_gen import (
    BASE_PRICES_INR,
    NORMALIZATION_RULES,
    PREMIUM_BY_CATEGORY,
    VOLATILITY_PROFILE,
    normalize_vendor_name,
    parse_price_string,
)
from schema import (
    CITY_CONFIG,
    CITY_PINCODES,
    CITIES,
    SCHEMA_COLUMNS,
    SCRAPE_CATEGORIES,
)

DEFAULT_OUTPUT = Path(__file__).parent / "food_inflation_scraped.csv"
PLATFORMS = ("Blinkit", "BigBasket")
RNG = np.random.default_rng(int(date.today().strftime("%Y%m%d")))

# Search terms per national category (India quick-commerce catalog)
SEARCH_QUERIES: dict[str, list[str]] = {
    "Rice": ["basmati rice 1kg", "sona masoori rice"],
    "Milk": ["amul taaza milk 1l", "toned milk 1 litre"],
    "Onions": ["onion 1kg", "red onion 1kg"],
    "Tomatoes": ["tomato 1kg", "hybrid tomato"],
    "Cooking Oil": ["sunflower oil 1l", "mustard oil 1l"],
}

BLINKIT_SEARCH = "https://blinkit.com/s/?q={query}"
BIGBASKET_SEARCH = "https://www.bigbasket.com/ps/?q={query}"


class ScrapeError(Exception):
    """Raised when live scraping cannot complete."""


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=SCHEMA_COLUMNS)


def _build_row(
    *,
    scrape_date: str,
    city: str,
    category: str,
    vendor_name: str,
    platform: str,
    app_price: float,
    cpi_price: float | None = None,
    prev_app_price: float | None = None,
    rolling_vol: float = 0.0,
) -> dict:
    profile = VOLATILITY_PROFILE.get(category, {"cpi_lag_weeks": 4})
    city_cfg = CITY_CONFIG[city]
    base_cpi = BASE_PRICES_INR[category] * city_cfg["base_price_multiplier"]
    cpi = cpi_price if cpi_price is not None else round(base_cpi, 2)
    app = round(app_price, 2)
    premium_pct = round((app / cpi - 1) * 100, 2) if cpi else np.nan
    daily_return = (
        round((app / prev_app_price - 1) * 100, 3) if prev_app_price and prev_app_price > 0 else 0.0
    )
    return {
        "date": scrape_date,
        "city": city,
        "category": category,
        "vendor_product_name": vendor_name,
        "normalized_category": normalize_vendor_name(vendor_name) or category,
        "platform": platform,
        "cpi_price_inr": cpi,
        "app_price_inr": app,
        "app_premium_pct": premium_pct,
        "app_price_parsed": parse_price_string(f"₹{app:.2f}"),
        "cpi_mom_change_pct": 0.0,
        "app_daily_return_pct": daily_return,
        "rolling_14d_app_volatility_pct": round(rolling_vol, 3),
        "is_perishable": category in ("Tomatoes", "Onions", "Potatoes"),
        "cpi_lag_weeks": profile["cpi_lag_weeks"],
    }


def _extract_prices_from_html(html: str, limit: int = 5) -> list[tuple[str, float]]:
    """Parse product cards from rendered HTML (Blinkit/BigBasket-like DOM patterns)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, float]] = []

    price_pattern = re.compile(r"₹\s*([\d,]+(?:\.\d+)?)")
    for tag in soup.find_all(string=price_pattern):
        parent = tag.parent
        for _ in range(6):
            if parent is None:
                break
            name_el = parent.find(["div", "span", "h3", "h4", "p"], string=lambda s: s and len(str(s).strip()) > 8)
            if name_el:
                name = name_el.get_text(strip=True)
                match = price_pattern.search(str(tag))
                if match:
                    price = parse_price_string(match.group(0))
                    if price and price > 0:
                        results.append((name, price))
                break
            parent = parent.parent

    if not results:
        for node in soup.select("[class*='Product'], [class*='product'], [data-testid]"):
            text = node.get_text(" ", strip=True)
            match = price_pattern.search(text)
            if not match:
                continue
            price = parse_price_string(match.group(0))
            if not price or price <= 0:
                continue
            name = price_pattern.sub("", text).strip()[:120] or "Unknown product"
            results.append((name, price))

    deduped: list[tuple[str, float]] = []
    seen: set[float] = set()
    for name, price in results:
        if price in seen:
            continue
        seen.add(price)
        deduped.append((name, price))
        if len(deduped) >= limit:
            break
    return deduped


def _match_category(product_name: str, target_category: str) -> bool:
    lowered = product_name.lower()
    for pattern, category in NORMALIZATION_RULES:
        if category == target_category and re.search(pattern, lowered):
            return True
    return False


def _create_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(25)
    return driver


def _scrape_platform_category(
    driver,
    platform: str,
    city: str,
    category: str,
    query: str,
) -> list[tuple[str, float]]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    url = (
        BLINKIT_SEARCH.format(query=query.replace(" ", "%20"))
        if platform == "Blinkit"
        else BIGBASKET_SEARCH.format(query=query.replace(" ", "%20"))
    )
    driver.get(url)
    time.sleep(2.5)

    if platform == "Blinkit":
        pincode = CITY_PINCODES[city]
        try:
            driver.execute_script(
                "window.localStorage.setItem('location', JSON.stringify({pincode: arguments[0]}));",
                pincode,
            )
        except Exception:
            pass

    WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(1.5)
    html = driver.page_source
    products = _extract_prices_from_html(html)
    matched = [(n, p) for n, p in products if _match_category(n, category)]
    return matched if matched else products[:2]


def scrape_live(cities: list[str] | None = None) -> pd.DataFrame:
    """Attempt Selenium scrape; raises ScrapeError if blocked or no prices found."""
    cities = cities or CITIES
    scrape_date = date.today().isoformat()
    rows: list[dict] = []

    driver = None
    try:
        driver = _create_driver()
        for city in cities:
            for platform in PLATFORMS:
                for category in SCRAPE_CATEGORIES:
                    query = SEARCH_QUERIES[category][0]
                    products = _scrape_platform_category(driver, platform, city, category, query)
                    if not products:
                        raise ScrapeError(
                            f"No prices parsed for {platform}/{city}/{category}"
                        )
                    name, price = products[0]
                    city_markup = CITY_CONFIG[city]["convenience_markup"]
                    national_premium = PREMIUM_BY_CATEGORY[category]
                    implied_cpi = price / (1 + national_premium + city_markup)
                    rows.append(
                        _build_row(
                            scrape_date=scrape_date,
                            city=city,
                            category=category,
                            vendor_name=name,
                            platform=platform,
                            app_price=price,
                            cpi_price=round(implied_cpi, 2),
                        )
                    )
    except ScrapeError:
        raise
    except Exception as exc:
        raise ScrapeError(f"Live scrape failed: {exc}") from exc
    finally:
        if driver is not None:
            driver.quit()

    if not rows:
        raise ScrapeError("Scrape completed but produced zero rows")

    df = pd.DataFrame(rows)[SCHEMA_COLUMNS]
    return df


def scrape_mock(cities: list[str] | None = None) -> pd.DataFrame:
    """
    India-specific mock snapshot when Blinkit/BigBasket block automation.
    Uses regional markup and Delhi perishable spike profile.
    """
    cities = cities or CITIES
    scrape_date = date.today().isoformat()
    rows: list[dict] = []

    for city in cities:
        cfg = CITY_CONFIG[city]
        for platform in PLATFORMS:
            for category in SCRAPE_CATEGORIES:
                base = BASE_PRICES_INR[category] * cfg["base_price_multiplier"]
                if category in ("Tomatoes", "Onions"):
                    seasonal = cfg["perishable_spike_multiplier"]
                    base *= 1 + 0.08 * seasonal * RNG.uniform(0.6, 1.4)
                national_premium = PREMIUM_BY_CATEGORY[category]
                markup = national_premium + cfg["convenience_markup"]
                platform_noise = 0.02 if platform == "Blinkit" else 0.0
                app_price = base * (1 + markup + platform_noise + RNG.uniform(-0.01, 0.01))
                cpi_price = base * (1 + RNG.uniform(-0.02, 0.02))
                vendor_pool = {
                    "Rice": "India Gate Basmati Rice 1kg",
                    "Milk": "Amul Taaza Homogenised Milk 1L",
                    "Onions": "Premium Farm Onions 1kg",
                    "Tomatoes": "Hybrid Tamatar 1kg",
                    "Cooking Oil": "Fortune Sunflower Oil 1L",
                }
                rows.append(
                    _build_row(
                        scrape_date=scrape_date,
                        city=city,
                        category=category,
                        vendor_name=vendor_pool[category],
                        platform=platform,
                        app_price=app_price,
                        cpi_price=cpi_price,
                        rolling_vol=float(RNG.uniform(2.5, 8.5)),
                    )
                )

    return pd.DataFrame(rows)[SCHEMA_COLUMNS]


def run_scraper(
    *,
    mock: bool = False,
    output: Path = DEFAULT_OUTPUT,
    cities: list[str] | None = None,
) -> pd.DataFrame:
    """Run scrape with automatic mock fallback on failure."""
    if mock:
        print("[scraper] --mock: using India-specific synthetic snapshot")
        df = scrape_mock(cities)
        source = "mock"
    else:
        try:
            print("[scraper] Attempting live Selenium scrape (Blinkit / BigBasket)...")
            df = scrape_live(cities)
            source = "live"
        except ScrapeError as exc:
            print(f"[scraper] Live scrape blocked or failed: {exc}")
            print("[scraper] Falling back to --mock snapshot (defensive fallback)")
            df = scrape_mock(cities)
            source = "mock_fallback"

    df.to_csv(output, index=False)
    print(f"[scraper] Wrote {len(df):,} rows ({source}) → {output.resolve()}")
    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape quick-commerce grocery prices (India)")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Skip Selenium; write India-specific mock snapshot (use when sites block bots)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output CSV path (default: food_inflation_scraped.csv)",
    )
    parser.add_argument(
        "--city",
        action="append",
        choices=CITIES,
        help="Limit to one or more cities (repeatable)",
    )
    args = parser.parse_args(argv)
    cities = args.city if args.city else None
    try:
        run_scraper(mock=args.mock, output=args.output, cities=cities)
        return 0
    except Exception as exc:
        print(f"[scraper] Fatal error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# 🌿 Food Inflation Sentiment vs. Official CPI Tracker

At its core, this project solves a major real-world puzzle: *"Why do consumers feel completely broke shopping for groceries when the government keeps announcing that inflation is under control?"*

A data analytics engine that tracks, cleans, and analyzes simulated real-time food price data from quick-commerce apps (Blinkit/BigBasket-style frameworks) and evaluates discrepancies against official National Consumer Price Index (CPI) metrics. It bridges the gap between official economic indices and actual consumer wallet impact across **Delhi, Mumbai, and Bengaluru**.

---

## 📊 Core Analytical Insights

| Insight | Finding |
|--------|---------|
| **The App Premium Gap** | Consistent **8%–18%** pricing premium on essential grocery segments on convenience apps vs. national CPI baseline |
| **Asymmetric Volatility** | Perishables (Tomatoes, Onions) show app price moves up to **~2 weeks faster** than lagging monthly CPI |
| **Consumer Perception Multiplier** | High-frequency small-ticket spikes (especially perishables) dominate negative inflation sentiment |

---

## 🛠 Tech Stack

| Layer | Tools |
|-------|--------|
| Ingestion (simulated) | Python — vendor string parsing, DOM-style price extraction patterns |
| Wrangling | `pandas`, `numpy` — deduplication, date standardization, price parsing |
| Statistics | Rolling volatility, MoM deltas, premium variance |
| Dashboard | `streamlit` + `plotly express` |

---

## 📂 Repository Structure

```text
├── data_gen.py                  # Synthetic market history (Delhi / Mumbai / Bengaluru)
├── scraper.py                   # Selenium scraper + --mock fallback
├── schema.py                    # Shared CSV schema & city config
├── food_inflation_data.csv      # Historical synthetic database
├── food_inflation_scraped.csv   # Latest live or mock scrape (optional)
├── app.py                       # Interactive Streamlit dashboard
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

---

## 🚀 Quick Start

```bash
# 1. Create virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Generate synthetic dataset (~2 years daily × categories × platforms)
python data_gen.py

# 4. (Optional) Scrape or mock live prices for dashboard
python scraper.py              # tries Blinkit/BigBasket; auto-falls back to mock
python scraper.py --mock         # skip Selenium when sites block bots

# 5. Launch dashboard
streamlit run app.py
```

Open the URL shown in the terminal (typically `http://localhost:8501`). Use the sidebar **City** filter and switch **Data source** to *Live scrape* when `food_inflation_scraped.csv` exists.

### India metro zones

| City | Regional behavior |
|------|-------------------|
| **Mumbai** | ~12% higher convenience markup on app prices |
| **Delhi** | Stronger seasonal onion & tomato volatility vs. national CPI |
| **Bengaluru** | Moderate markup and perishable sensitivity |

---

## 🔬 How the Pipeline Works

1. **`data_gen.py`** builds CPI and app price paths per commodity with category-specific volatility and reporting lag.
2. **Fuzzy normalization** maps vendor strings (e.g. *"Premium Farm Onions 1kg"*) → national categories (*"Onions"*).
3. **App premium** is applied per segment (8–18% band) on top of a lagged CPI anchor.
4. **`scraper.py`** pulls Rice, Milk, Onions, Tomatoes, Cooking Oil from Blinkit/BigBasket; on block/failure, writes the same schema via `--mock`.
5. **`app.py`** loads historical or scraped CSV with city-level filters and renders trend, premium, volatility, and sentiment views.

---

## 💼 Skills Demonstrated

- **Unstructured ingestion pipelines** — scrape-ready price parsing and vendor inventory normalization
- **Fuzzy data normalization** — regex-based mapping into strict national classification buckets
- **Actionable analytics** — KPIs and charts aimed at consumer sentiment and commercial pricing strategy

---

## ⚠️ Note on Data

Prices and platforms are **synthetically generated** for portfolio and learning use. The structure mirrors real quick-commerce vs. CPI dynamics but does not reflect live market quotes.

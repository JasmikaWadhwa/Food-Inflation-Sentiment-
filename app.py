"""
Food Inflation Sentiment vs. Official CPI — interactive Streamlit dashboard.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

DATA_DIR = Path(__file__).parent
HISTORICAL_PATH = DATA_DIR / "food_inflation_data.csv"
SCRAPED_PATH = DATA_DIR / "food_inflation_scraped.csv"
PERISHABLES = {"Tomatoes", "Onions", "Potatoes"}


@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    if "city" not in df.columns:
        df["city"] = "All India"
    df["year_month"] = df["date"].dt.to_period("M").astype(str)
    return df


def resolve_data_path(source: str) -> Path | None:
    if source == "Live scrape" and SCRAPED_PATH.exists():
        return SCRAPED_PATH
    if source == "Historical (synthetic)" and HISTORICAL_PATH.exists():
        return HISTORICAL_PATH
    if HISTORICAL_PATH.exists():
        return HISTORICAL_PATH
    if SCRAPED_PATH.exists():
        return SCRAPED_PATH
    return None


def compute_insights(df: pd.DataFrame, city_filter: list[str] | None = None) -> dict:
    scoped = df if not city_filter else df[df["city"].isin(city_filter)]
    latest = scoped.loc[scoped["date"] == scoped["date"].max()]
    premium = latest.groupby("category")["app_premium_pct"].mean()
    gap_low, gap_high = premium.min(), premium.max()

    perishable = scoped[scoped["category"].isin(PERISHABLES)]
    staple = scoped[~scoped["category"].isin(PERISHABLES)]

    def avg_vol(frame: pd.DataFrame, col: str) -> float:
        return frame.groupby("category")[col].mean().mean()

    app_vol_p = avg_vol(perishable, "rolling_14d_app_volatility_pct")
    app_vol_s = avg_vol(staple, "rolling_14d_app_volatility_pct")

    # Sentiment proxy: weight small-ticket perishable spikes more heavily
    spike_threshold = scoped["app_daily_return_pct"].quantile(0.90)
    spikes = scoped[scoped["app_daily_return_pct"] >= spike_threshold]
    perishable_spike_share = (
        spikes[spikes["category"].isin(PERISHABLES)].shape[0] / max(len(spikes), 1) * 100
    )

    return {
        "premium_range": (gap_low, gap_high),
        "avg_premium": premium.mean(),
        "perishable_vol": app_vol_p,
        "staple_vol": app_vol_s,
        "perishable_spike_share": perishable_spike_share,
        "median_cpi_lag_weeks": scoped["cpi_lag_weeks"].median(),
    }


def main() -> None:
    st.set_page_config(
        page_title="Food Inflation: App vs CPI",
        page_icon="🌿",
        layout="wide",
    )

    st.title("🌿 Food Inflation Sentiment vs. Official CPI")
    st.caption(
        "India metro zones — Delhi, Mumbai, Bengaluru — vs. national CPI "
        "(Blinkit / BigBasket quick-commerce)."
    )

    source_options = ["Historical (synthetic)"]
    if SCRAPED_PATH.exists():
        source_options.append("Live scrape")
    data_source = st.sidebar.selectbox("Data source", source_options)
    data_path = resolve_data_path(data_source)
    if data_path is None:
        st.error(
            "No dataset found. Run `python data_gen.py` and/or "
            "`python scraper.py --mock`."
        )
        st.stop()

    df = load_data(str(data_path))
    cities = sorted(df["city"].dropna().unique())
    default_cities = cities if len(cities) <= 3 else cities[:2]
    selected_cities = st.sidebar.multiselect(
        "City",
        cities,
        default=default_cities,
    )
    city_filter = selected_cities if selected_cities else None
    df_view = df if not city_filter else df[df["city"].isin(city_filter)]
    insights = compute_insights(df, city_filter)

    # --- KPI row ---
    c1, c2, c3, c4 = st.columns(4)
    lo, hi = insights["premium_range"]
    c1.metric("App Premium Gap", f"{lo:.1f}% – {hi:.1f}%", f"avg {insights['avg_premium']:.1f}%")
    c2.metric(
        "Perishable App Volatility",
        f"{insights['perishable_vol']:.1f}%",
        f"vs staples {insights['staple_vol']:.1f}%",
    )
    c3.metric("CPI Reporting Lag", f"{insights['median_cpi_lag_weeks']:.0f} weeks", "perishables ~2w faster on apps")
    c4.metric(
        "Perception Driver",
        f"{insights['perishable_spike_share']:.0f}%",
        "of top price spikes are perishables",
    )

    st.divider()

    if data_source == "Live scrape":
        st.success(f"Loaded live scrape: `{data_path.name}` ({len(df):,} rows)")
    else:
        st.info(f"Historical synthetic data: `{data_path.name}`")

    categories = sorted(df_view["category"].unique())
    platforms = sorted(df_view["platform"].unique())

    col_filters, col_main = st.columns([1, 4])
    with col_filters:
        st.subheader("Filters")
        if city_filter:
            st.caption(f"Cities: {', '.join(city_filter)}")
        selected_cats = st.multiselect(
            "Categories",
            categories,
            default=categories[:5],
        )
        selected_platforms = st.multiselect("Platforms", platforms, default=platforms)
        date_range = st.date_input(
            "Date range",
            value=(df_view["date"].min().date(), df_view["date"].max().date()),
            min_value=df_view["date"].min().date(),
            max_value=df_view["date"].max().date(),
        )

    filtered = df_view[
        df_view["category"].isin(selected_cats) & df_view["platform"].isin(selected_platforms)
    ]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
        filtered = filtered[(filtered["date"] >= start) & (filtered["date"] <= end)]

    with col_main:
        tab_trend, tab_gap, tab_vol, tab_sentiment = st.tabs(
            ["Price Trends", "App Premium Gap", "Volatility", "Consumer Sentiment"]
        )

        with tab_trend:
            daily = (
                filtered.groupby(["date", "category"], as_index=False)[
                    ["cpi_price_inr", "app_price_inr"]
                ]
                .mean()
            )
            melted = daily.melt(
                id_vars=["date", "category"],
                value_vars=["cpi_price_inr", "app_price_inr"],
                var_name="series",
                value_name="price_inr",
            )
            melted["series"] = melted["series"].map(
                {
                    "cpi_price_inr": "Official CPI (₹)",
                    "app_price_inr": "Quick-Commerce App (₹)",
                }
            )
            fig = px.line(
                melted,
                x="date",
                y="price_inr",
                color="series",
                facet_col="category",
                facet_col_wrap=3,
                title="CPI Baseline vs. App Prices by Category",
                labels={"price_inr": "Price (INR)", "date": "Date"},
            )
            fig.update_layout(height=500, legend_title_text="")
            st.plotly_chart(fig, use_container_width=True)

        with tab_gap:
            group_cols = ["category"] if "city" not in filtered.columns else ["city", "category"]
            gap = (
                filtered.groupby(group_cols, as_index=False)["app_premium_pct"]
                .mean()
                .sort_values("app_premium_pct", ascending=True)
            )
            fig_gap = px.bar(
                gap,
                x="app_premium_pct",
                y="category",
                color="city" if "city" in gap.columns else None,
                orientation="h",
                title="Average App Premium vs. National CPI Baseline (by city)",
                labels={"app_premium_pct": "Premium (%)", "category": ""},
                color="app_premium_pct",
                color_continuous_scale="RdYlGn_r",
            )
            fig_gap.add_vline(x=8, line_dash="dash", annotation_text="8% floor")
            fig_gap.add_vline(x=18, line_dash="dash", annotation_text="18% ceiling")
            st.plotly_chart(fig_gap, use_container_width=True)

            if city_filter and "Mumbai" in city_filter:
                st.info(
                    "**Mumbai convenience markup:** ~12% higher quick-commerce premium vs. "
                    "other metros on the same basket."
                )
            st.info(
                "**The App Premium Gap:** Essential grocery segments on convenience apps "
                "consistently price **8–18%+** above national baseline CPI metrics."
            )

        with tab_vol:
            vol = filtered.groupby(["date", "category"], as_index=False)[
                "rolling_14d_app_volatility_pct"
            ].mean()
            fig_vol = px.line(
                vol,
                x="date",
                y="rolling_14d_app_volatility_pct",
                color="category",
                title="14-Day Rolling App Price Volatility (%)",
            )
            st.plotly_chart(fig_vol, use_container_width=True)

            perish = vol[vol["category"].isin(PERISHABLES)]
            other = vol[~vol["category"].isin(PERISHABLES)]
            asym = (
                perish.groupby("date")["rolling_14d_app_volatility_pct"].mean()
                - other.groupby("date")["rolling_14d_app_volatility_pct"].mean()
            ).reset_index(name="perishable_minus_staple")
            fig_asym = px.area(
                asym,
                x="date",
                y="perishable_minus_staple",
                title="Asymmetric Volatility: Perishables vs. Staples (spread)",
            )
            st.plotly_chart(fig_asym, use_container_width=True)

        with tab_sentiment:
            monthly = (
                filtered.groupby(["year_month", "category"], as_index=False)
                .agg(
                    app_return=("app_daily_return_pct", "mean"),
                    cpi_change=("cpi_mom_change_pct", "mean"),
                )
            )
            monthly["sentiment_stress"] = np.where(
                monthly["category"].isin(PERISHABLES),
                monthly["app_return"] * 2.5,
                monthly["app_return"],
            )
            fig_sent = px.imshow(
                monthly.pivot(index="category", columns="year_month", values="sentiment_stress"),
                title="Consumer Perception Stress Index (weighted by category)",
                labels=dict(x="Month", y="Category", color="Stress"),
                aspect="auto",
                color_continuous_scale="Reds",
            )
            st.plotly_chart(fig_sent, use_container_width=True)

            st.markdown(
                """
                **The Consumer Perception Multiplier:** High-frequency spikes in
                small-ticket perishables (tomatoes, onions) drive negative inflation
                sentiment even when bulk staples remain stable on official CPI reports.
                """
            )

    with st.expander("Data pipeline & normalization sample"):
        sample_cols = [
            "date",
            "city",
            "vendor_product_name",
            "normalized_category",
            "platform",
            "app_price_inr",
        ]
        sample = filtered[sample_cols].drop_duplicates("vendor_product_name").head(12)
        st.dataframe(sample, use_container_width=True)

    st.caption(
        "Historical: `python data_gen.py` · Live/mock scrape: "
        "`python scraper.py` or `python scraper.py --mock`"
    )


if __name__ == "__main__":
    main()

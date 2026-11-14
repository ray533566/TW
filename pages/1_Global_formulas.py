"""Global formulas dashboard: trend and momentum, value and quality, compounding."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core import data, formulas  # noqa: E402

UP, DOWN = "#d9363e", "#1a9e55"   # Taiwan convention: red = up, green = down
ROWS = {"ni": ["Net Income", "Net Income Common Stockholders"], "ebit": ["EBIT", "Operating Income"],
        "gp": ["Gross Profit"], "rev": ["Total Revenue"], "cfo": ["Operating Cash Flow"],
        "assets": ["Total Assets"], "ca": ["Current Assets"], "cl": ["Current Liabilities"],
        "ltd": ["Long Term Debt"], "ppe": ["Net PPE"], "shares": ["Ordinary Shares Number", "Share Issued"],
        "equity": ["Stockholders Equity", "Common Stock Equity"], "debt": ["Total Debt"],
        "cash": ["Cash And Cash Equivalents"]}

st.set_page_config(page_title="Global formulas", page_icon="🌍", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)
def prices_tw(stocks: tuple) -> dict:
    return data.fetch_tw_prices(list(stocks), "2y")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def statements(symbol: str) -> dict:
    """The two latest fiscal years from Yahoo as {'cur': {...}, 'prev': {...}}. Any value may be None."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    frames = []
    for name in ("income_stmt", "balance_sheet", "cashflow"):
        try:
            frames.append(getattr(t, name))
        except Exception:  # noqa: BLE001
            pass
    out = {}
    for i, k in enumerate(("cur", "prev")):
        d = {}
        for key, rows in ROWS.items():
            d[key] = None
            for df in frames:
                hit = [r for r in rows if df is not None and r in df.index and df.shape[1] > i
                       and pd.notna(df.loc[r].iloc[i])]
                if hit:
                    d[key] = float(df.loc[hit[0]].iloc[i])
                    break
        if d["ltd"] is None and d["assets"] is not None:
            d["ltd"] = 0.0
        out[k] = d
    return out


def fmt(v, pattern="{:,.2f}"):
    return "—" if v is None or pd.isna(v) else pattern.format(v)


stocks = st.session_state.get("stocks")
if stocks is None:
    stocks = st.session_state.stocks = data.load_stock_list(ROOT / "data" / "AllStock.xlsx")

st.title("🌍 Global formulas")
st.caption("No single formula is the best: each of these well-known rules works in some markets and fails in "
           "others. The dashboard shows what each one says today so you can compare them side by side.")
tab_trend, tab_value, tab_comp = st.tabs(["📈 Trend & momentum", "💎 Value & quality", "🧮 Compounding"])

# ---------------- 1. trend and momentum ----------------

with tab_trend:
    watch = stocks[stocks.Watch]
    pairs = tuple(sorted(set(zip(watch.Number, watch.Market)) | {("0050", "TSE")}))
    with st.spinner("Loading prices…"):
        tbl = formulas.trend_table(prices_tw(pairs), dict(zip(stocks.Number, stocks.Name)))
    if tbl.empty:
        st.warning("No price history from Yahoo Finance right now. Try again in a few minutes.")
    else:
        ok = tbl[tbl.Trend != "n/a"]
        b = tbl.loc[tbl.Number == "0050", "Mom 12-1 %"]
        c = st.columns(4)
        c[0].metric("Stocks in uptrend", f"{int((ok.Trend == 'Up').sum())} / {len(ok)}")
        c[1].metric("Out of trend", f"{int((ok.Trend == 'Out').sum())} / {len(ok)}")
        c[2].metric("Median 12-1 momentum", fmt(ok["Mom 12-1 %"].median(), "{:+.1f}%"))
        c[3].metric("0050 12-1 momentum", fmt(b.iloc[0] if len(b) else None, "{:+.1f}%"))

        bar = ok.dropna(subset=["Mom 12-1 %"])
        fig = go.Figure(go.Bar(x=bar.Number + " " + bar.Name, y=bar["Mom 12-1 %"],
                               marker_color=[UP if v > 0 else DOWN for v in bar["Mom 12-1 %"]]))
        fig.update_layout(title="12-1 momentum, watchlist (%)", height=360, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(tbl, hide_index=True, width="stretch", height=480, column_config={
            "Close": st.column_config.NumberColumn(format="%.2f"),
            "Mom 12-1 %": st.column_config.NumberColumn(format="%+.1f"),
            "Sharpe 1y": st.column_config.NumberColumn(format="%.2f"),
            "Max DD 1y %": st.column_config.NumberColumn(format="%.1f")})
    st.caption("**12-1 momentum** (Jegadeesh & Titman): return from 12 months ago to 1 month ago. "
               "**Above 10M avg** (Faber): close above the average of the last 10 month-end closes. "
               "**Trend** (Antonacci absolute momentum + Faber): Up when both agree, Out when both fail. "
               "**Sharpe**: return above a 1.5% risk-free rate per unit of volatility. Watchlist stocks only; "
               "edit the watchlist in the main app's Stock list tab.")

# ---------------- 2. value and quality ----------------

with tab_value:
    opts = stocks.sort_values(["Watch", "Number"], ascending=[False, True])
    labels = {r.Number: f"{r.Number} {r.Name}" for r in opts.itertuples()}
    num = st.selectbox("Stock", list(labels), format_func=labels.get)
    mkt = stocks.loc[stocks.Number == num, "Market"].iloc[0]
    with st.spinner("Loading fundamentals…"):
        px = prices_tw(((num, mkt),)).get(num)
        fs = statements(data.yf_symbol(num, mkt))
    cur, prev = fs["cur"], fs["prev"]
    price = float(px["Close"].iloc[-1]) if px is not None and len(px) else None
    sh = cur["shares"]
    eps, bvps = formulas._ratio(cur["ni"], sh), formulas._ratio(cur["equity"], sh)
    gn = formulas.graham_number(eps, bvps)
    ev = None if price is None or sh is None else price * sh + (cur["debt"] or 0) - (cur["cash"] or 0)
    nwc = None if cur["ca"] is None or cur["cl"] is None else cur["ca"] - cur["cl"]
    ey, roc = formulas.magic_formula(cur["ebit"], ev, nwc, cur["ppe"])
    score, avail, checks = formulas.piotroski(cur, prev)

    c = st.columns(5)
    c[0].metric("Close", fmt(price))
    c[1].metric("Graham number", fmt(gn), None if gn is None or price is None
                else f"price is {(price / gn - 1) * 100:+.0f}% vs fair", delta_color="off")
    c[2].metric("Earnings yield (EBIT / EV)", fmt(ey, "{:.1f}%"))
    c[3].metric("Return on capital", fmt(roc, "{:.1f}%"))
    c[4].metric("Piotroski F-Score", f"{score} / {avail}" if avail else "—")
    if avail == 0:
        st.warning("Yahoo Finance returned no annual statements for this stock, so the scores cannot be computed.")
    else:
        st.dataframe(pd.DataFrame([{"Check": k, "Result": "✅ Pass" if v else ("— no data" if v is None else "❌ Fail")}
                                   for k, v in checks]), hide_index=True, width="stretch")
    st.caption("**Graham number** (Benjamin Graham): √(22.5 × EPS × book value per share); a price below it is "
               "cheap by his rule. **Earnings yield and return on capital** (Greenblatt's Magic Formula): higher is "
               "better on both. **F-Score** (Piotroski): 9 pass/fail checks of profitability, leverage and "
               "efficiency; 8-9 is strong, 0-2 weak. Latest annual report from Yahoo Finance, which is often "
               "incomplete for Taiwan listings; ETFs have no statements, and banks and insurers lack several inputs.")

# ---------------- 3. compounding ----------------

with tab_comp:
    c = st.columns(4)
    start = c[0].number_input("Starting amount (TWD)", 0, None, 100_000, step=10_000)
    monthly = c[1].number_input("Monthly contribution (TWD)", 0, None, 10_000, step=1_000)
    rate = c[2].number_input("Annual return %", -20.0, 50.0, 7.0, step=0.5)
    years = c[3].slider("Years", 1, 50, 20)
    path = formulas.compound_path(start, monthly, rate, years)
    end, paid = path.Value.iloc[-1], path["Paid in"].iloc[-1]
    r72, exact = formulas.doubling_years(rate)
    c = st.columns(4)
    c[0].metric("Value after %d years" % years, fmt(end, "{:,.0f}"))
    c[1].metric("Total paid in", fmt(paid, "{:,.0f}"))
    c[2].metric("Growth", fmt(end - paid, "{:,.0f}"))
    c[3].metric("Years to double (Rule of 72)", fmt(r72, "{:.1f}"), None if exact is None else f"exact {exact:.1f}",
                delta_color="off")
    fig = go.Figure()
    fig.add_scatter(x=path.Year, y=path.Value, name="Value", line=dict(color="#2a6fdb", width=2))
    fig.add_scatter(x=path.Year, y=path["Paid in"], name="Paid in", line=dict(color="gray", dash="dot"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10), xaxis_title="Year", yaxis_title="TWD")
    st.plotly_chart(fig, width="stretch")
    st.caption("Future value with monthly compounding at a constant return. Real returns vary year to year, "
               "so treat this as an illustration, not a forecast.")

st.caption("Signals are mechanical rule outputs for study, not investment advice.")

"""Taiwan Invest Signals — Streamlit app.

Run locally:  streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core import data, signals, sizing

ROOT = Path(__file__).parent
LIST_PATH = ROOT / "data" / "AllStock.xlsx"
MACRO_PATH = ROOT / "data" / "macro_inputs.json"
UP, DOWN = "#d9363e", "#1a9e55"   # Taiwan convention: red = up, green = down

st.set_page_config(page_title="Taiwan Invest Signals", page_icon="📈", layout="wide")


# ---------------- cached loaders ----------------

@st.cache_data(ttl=3600, show_spinner=False)
def prices_tw(stocks: tuple, period: str = "2y") -> dict:
    return data.fetch_tw_prices(list(stocks), period)


@st.cache_data(ttl=3600, show_spinner=False)
def prices_raw(symbols: tuple, period: str = "2y") -> dict:
    return data.fetch_prices(list(symbols), period)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fundamentals(symbol: str) -> dict:
    return data.fetch_fundamentals(symbol)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def macro_auto() -> dict:
    """Every fetch is optional: a failure leaves the value None and is listed in 'errors'."""
    out, err = {}, []
    for key, fn in [("curve", data.fetch_t10y2y), ("fear_greed", data.fetch_fear_greed),
                    ("margin", data.fetch_margin_balance)]:
        try:
            out[key] = fn()
        except Exception as e:  # noqa: BLE001
            out[key] = None
            err.append(f"{key}: {type(e).__name__}")
    out["errors"] = err
    return out


def get_list() -> pd.DataFrame:
    if "stocks" not in st.session_state:
        st.session_state.stocks = data.load_stock_list(LIST_PATH)
    return st.session_state.stocks


def last(df, col="Close"):
    return float(df[col].iloc[-1]) if df is not None and len(df) else None


# ---------------- sidebar ----------------

stocks = get_list()
saved = data.load_macro_inputs(MACRO_PATH)

with st.sidebar:
    st.title("📈 Taiwan Invest Signals")
    if st.button("🔄 Refresh market data", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.subheader("Manual macro inputs")
    st.caption("Defaults come from `data/macro_inputs.json`. 0 = unknown.")
    cycle = st.number_input("景氣對策信號 score (9–45)", 0, 45, int(saved.get("cycle_score") or 0),
                            help=f"NDC monthly release. Saved as of: {saved.get('cycle_score_as_of') or '—'}")
    mcap = st.number_input("Total market cap / GDP (%)", 0.0, 2000.0, float(saved.get("mcap_gdp_pct") or 0.0),
                           step=5.0, help=f"Saved as of: {saved.get('mcap_gdp_as_of') or '—'}")
    maint = st.number_input("大盤融資維持率 (%)", 0.0, 400.0, float(saved.get("maint_ratio_pct") or 0.0),
                            step=1.0, help=f"TWSE 台股儀表板. Saved as of: {saved.get('maint_ratio_as_of') or '—'}")
    fg_manual = st.number_input("Fear & Greed override (0 = auto)", 0, 100, 0)
    drop_manual = st.number_input("融資餘額 1-day drop % override (0 = auto)", 0.0, 50.0, 0.0, step=0.5)

    st.subheader("Rule parameters")
    P = signals.Params(
        ma_trend=st.selectbox("Trend MA (rule 4)", [20, 60, 120, 200], index=1),
        lookback=st.slider("Signal lookback (bars)", 1, 10, 3),
        vol_mult=st.slider("Volume spike × 20-day avg (rule 7)", 1.5, 4.0, 2.0, 0.5),
    )
    margin_thr = st.slider("Margin 1-day drop threshold % (rule 3)", 0.5, 5.0, 2.0, 0.5)
    st.caption("Signals are mechanical rule outputs for study, not investment advice.")

tab_mkt, tab_scr, tab_stk, tab_size, tab_list, tab_rules = st.tabs(
    ["🧭 Market", "🔎 Screener", "📊 Stock", "🧮 Position sizing", "📋 Stock list", "📖 Rules"])


# ---------------- 1. market ----------------

with tab_mkt:
    with st.spinner("Loading market data…"):
        idx = prices_raw(("^TWII", "^VIX"), "2y")
        auto = macro_auto()
    twii, vix = idx.get("^TWII"), idx.get("^VIX")
    margin = auto.get("margin")
    curve = auto.get("curve")
    curve_on, curve_date = signals.yield_curve_state(curve) if curve is not None else (None, None)

    fg = fg_manual or auto.get("fear_greed")
    d1 = drop_manual or (data.pct_drop(margin, 1) if margin is not None else None)
    d5 = data.pct_drop(margin, 5) if margin is not None else (drop_manual or None)
    ma200 = float(twii["Close"].rolling(200).mean().iloc[-1]) if twii is not None and len(twii) >= 200 else None

    m = {"mcap_gdp": mcap or None, "fear_greed": fg, "index_close": last(twii), "index_ma200": ma200,
         "maint_ratio": maint or None, "margin_drop_1d": d1, "margin_drop_5d": d5,
         "cycle_score": cycle or None, "curve_uninverted": curve_on, "curve_date": curve_date,
         "vix": last(vix)}
    cards = signals.macro_signals(m, margin_thr)
    st.session_state.macro_cards = cards

    buy_on = sum(c["status"] == "on" and c["side"] == "buy" for c in cards)
    def_on = sum(c["status"] == "on" and c["side"] == "defend" for c in cards)
    na = sum(c["status"] == "na" for c in cards)
    if buy_on and not def_on:
        st.success(f"**Regime: accumulate** — {buy_on} buy rule(s) active, no defensive rule active.")
    elif def_on and not buy_on:
        st.warning(f"**Regime: defensive** — {def_on} defensive rule(s) active, no buy rule active.")
    elif buy_on and def_on:
        st.info(f"**Regime: mixed** — {buy_on} buy and {def_on} defensive rule(s) active.")
    else:
        st.info("**Regime: neutral** — no macro rule is active.")
    if na:
        st.caption(f"{na} rule(s) could not be evaluated — fill the missing inputs in the sidebar.")

    c = st.columns(5)
    c[0].metric("TAIEX 加權指數", f"{m['index_close']:,.0f}" if m["index_close"] else "—",
                f"{(m['index_close'] / ma200 - 1) * 100:+.1f}% vs 200MA" if m["index_close"] and ma200 else None,
                delta_color="inverse")
    c[1].metric("VIX", f"{m['vix']:.1f}" if m["vix"] else "—")
    c[2].metric("Fear & Greed (US)", f"{fg:.0f}" if fg else "—")
    c[3].metric("10Y–2Y spread", f"{curve.iloc[-1]:+.2f}" if curve is not None and len(curve) else "—")
    c[4].metric("融資餘額 1d" + (f" (5d {-d5:+.1f}%)" if d5 is not None else ""),
                f"{-d1:+.1f}%" if d1 is not None else "—")

    st.divider()
    icon = {"on": "🟢", "off": "⚪", "na": "❔"}
    label = {"on": "TRIGGERED", "off": "not triggered", "na": "needs data"}
    for row in (cards[:4], cards[4:]):
        cols = st.columns(4)
        for col, cd in zip(cols, row):
            with col.container(border=True):
                side = "BUY" if cd["side"] == "buy" else "DEFENSIVE"
                st.markdown(f"**Rule {int(cd['no'])} · {side}**  \n{cd['name']}")
                st.markdown(f"{icon[cd['status']]} **{label[cd['status']]}** · {cd['value']}")
                if cd["missing"]:
                    st.caption("Missing: " + ", ".join(cd["missing"]))

    if twii is not None and len(twii) >= 200:
        fig = go.Figure()
        fig.add_scatter(x=twii.index, y=twii["Close"], name="TAIEX", line=dict(color="#2a6fdb"))
        fig.add_scatter(x=twii.index, y=twii["Close"].rolling(200).mean(), name="200MA",
                        line=dict(color="#e0a000", dash="dot"))
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=30, b=0), title="TAIEX vs 200-day MA",
                          legend=dict(orientation="h", y=1.12, x=0.6))
        st.plotly_chart(fig, width="stretch")
    elif twii is None:
        st.error("Could not load index prices from Yahoo Finance. Try **Refresh market data** in a minute.")
    if auto["errors"]:
        st.caption("Auto-fetch failed for: " + "; ".join(auto["errors"]) + " — use the sidebar inputs instead.")


# ---------------- 2. screener ----------------

with tab_scr:
    scope = st.radio("Universe", ["Watchlist", "All TSE 上市", "All OTC 上櫃"], horizontal=True)
    sel = stocks[stocks.Watch] if scope == "Watchlist" else stocks[stocks.Market == ("TSE" if "TSE" in scope else "OTC")]
    go_scan = True
    if scope != "Watchlist":
        st.caption(f"{len(sel)} stocks — the first scan downloads two years of prices and can take a few minutes.")
        go_scan = st.toggle("Run full-market scan", key=f"scan_{scope}")
    if sel.empty:
        st.info("The watchlist is empty. Tick stocks in the **Stock list** tab.")
    elif go_scan:
        with st.spinner(f"Scanning {len(sel)} stocks…"):
            px = prices_tw(tuple(zip(sel.Number, sel.Market)))
        rows = []
        for r in sel.itertuples():
            s = signals.stock_signals(px.get(r.Number), P)
            if s:
                rows.append({"Number": r.Number, "Name": r.Name, **s})
        if not rows:
            st.error("No price data came back from Yahoo Finance. Try **Refresh market data** in a minute.")
        else:
            res = pd.DataFrame(rows).sort_values(["score", "r14_parts"], ascending=False)
            only = st.toggle("Only stocks with at least one buy signal", value=scope != "Watchlist")
            if only:
                res = res[res[["r4_trend", "r5_breakout", "r6_rsi_div", "r7_squeeze", "r14_combo"]].any(axis=1)]
            miss = len(sel) - len(rows)
            st.caption(f"{len(rows)} scanned" + (f", {miss} without price data" if miss else "") +
                       f" · MA{P.ma_trend} trend, {P.lookback}-bar lookback")
            st.dataframe(
                res, hide_index=True, width="stretch", height=560,
                column_order=["Number", "Name", "close", "chg_pct", "score", "r4_trend", "r5_breakout",
                              "r6_rsi_div", "r7_squeeze", "r14_parts", "r5_exit", "rsi", "k", "d"],
                column_config={
                    "close": st.column_config.NumberColumn("Close", format="%.2f"),
                    "chg_pct": st.column_config.NumberColumn("Chg %", format="%+.2f"),
                    "score": st.column_config.NumberColumn("Score", help="Buy signals minus exit signal"),
                    "r4_trend": st.column_config.CheckboxColumn("R4 Trend", help="Close crossed above a flat/rising MA"),
                    "r5_breakout": st.column_config.CheckboxColumn("R5 Breakout", help="Close above prior 20-day high"),
                    "r6_rsi_div": st.column_config.CheckboxColumn("R6 RSI div", help="Lower low, higher RSI low, RSI<30"),
                    "r7_squeeze": st.column_config.CheckboxColumn("R7 Squeeze", help="BB squeeze + volume + upper-band break"),
                    "r14_parts": st.column_config.ProgressColumn("R14 KD combo", min_value=0, max_value=3, format="%d/3",
                                                                 help="KD<20 golden cross · RSI divergence · back above 20MA"),
                    "r5_exit": st.column_config.CheckboxColumn("R5 EXIT", help="Close below prior 10-day low"),
                    "rsi": st.column_config.NumberColumn("RSI", format="%.0f"),
                    "k": st.column_config.NumberColumn("K", format="%.0f"),
                    "d": st.column_config.NumberColumn("D", format="%.0f"),
                })
            st.download_button("Download results (CSV)", res.to_csv(index=False).encode("utf-8-sig"),
                               "screener.csv", "text/csv")


# ---------------- 3. single stock ----------------

with tab_stk:
    opts = stocks.sort_values(["Watch", "Number"], ascending=[False, True])
    labels = {r.Number: f"{r.Number} {r.Name}" for r in opts.itertuples()}
    num = st.selectbox("Stock", list(labels), format_func=labels.get)
    mkt = stocks.loc[stocks.Number == num, "Market"].iloc[0]
    with st.spinner("Loading…"):
        df = prices_tw(((num, mkt),)).get(num)
    if df is None or len(df) < 30:
        st.error("No price history from Yahoo Finance for this stock.")
    else:
        s = signals.stock_signals(df, P)
        o = signals.enrich(df, P).iloc[-250:]
        c = st.columns(6)
        c[0].metric("Close", f"{s['close']:.2f}", f"{s['chg_pct']:+.2f}%", delta_color="inverse")
        for col, (name, key) in zip(c[1:], [("R4 Trend buy", "r4_trend"), ("R5 Breakout", "r5_breakout"),
                                            ("R6 RSI divergence", "r6_rsi_div"), ("R7 Squeeze", "r7_squeeze")]):
            col.metric(name, "🟢 Yes" if s[key] else "⚪ No")
        c[5].metric("R14 KD combo", f"{s['r14_parts']}/3")
        if s["r5_exit"]:
            st.warning("Rule 5 exit: close is below the prior 10-day low.")

        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, row_heights=[0.52, 0.14, 0.17, 0.17],
                            vertical_spacing=0.02)
        fig.add_candlestick(x=o.index, open=o.Open, high=o.High, low=o.Low, close=o.Close, name="Price",
                            increasing_line_color=UP, decreasing_line_color=DOWN, row=1, col=1)
        for n, colr in [(20, "#e0a000"), (60, "#2a6fdb"), (200, "#8e44ad")]:
            fig.add_scatter(x=o.index, y=o[f"MA{n}"], name=f"MA{n}", line=dict(width=1.2, color=colr), row=1, col=1)
        fig.add_scatter(x=o.index, y=o.BBup, name="BB", line=dict(width=0.8, color="gray", dash="dot"), row=1, col=1)
        fig.add_scatter(x=o.index, y=o.BBlo, showlegend=False, line=dict(width=0.8, color="gray", dash="dot"),
                        row=1, col=1)
        fig.add_bar(x=o.index, y=o.Volume, name="Volume", showlegend=False,
                    marker_color=[UP if a >= b else DOWN for a, b in zip(o.Close, o.Open)], row=2, col=1)
        fig.add_scatter(x=o.index, y=o.RSI, name="RSI", line=dict(color="#16a085"), row=3, col=1)
        fig.add_scatter(x=o.index, y=o.K, name="K", line=dict(color="#e67e22"), row=4, col=1)
        fig.add_scatter(x=o.index, y=o.D, name="D", line=dict(color="#34495e"), row=4, col=1)
        for y, rw in [(30, 3), (70, 3), (20, 4), (80, 4)]:
            fig.add_hline(y=y, line_dash="dot", line_color="lightgray", row=rw, col=1)
        fig.update_layout(height=780, xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=10, b=0),
                          legend=dict(orientation="h", y=1.03))
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        st.plotly_chart(fig, width="stretch")

        st.subheader("Fundamentals (rules 11 & 12)")
        if st.toggle("Load fundamentals from Yahoo Finance", key=f"fund_{num}"):
            f = fundamentals(data.yf_symbol(num, mkt))
            c = st.columns(4)
            pe = c[0].number_input("PE ratio", value=float(f["pe"] or 0.0))
            gr = c[1].number_input("Annual EPS growth %", value=float(f["eps_growth_pct"] or 0.0))
            peg, on = signals.peg(pe or None, gr or None)
            c[2].metric("PEG", f"{peg:.2f}" if peg else "—",
                        "🟢 < 1.0 undervalued growth" if on else ("not triggered" if peg else "needs PE and growth > 0"),
                        delta_color="off")
            nv, on2 = signals.ncav(s["close"], f["current_assets"], f["total_liabilities"], f["shares"])
            c[3].metric("NCAV / share", f"{nv:.2f}" if nv is not None else "—",
                        ("🟢 price < 0.67 × NCAV" if on2 else f"needs price < {0.67 * nv:.2f}") if nv is not None
                        else "balance sheet unavailable", delta_color="off")
            st.caption("Yahoo data for Taiwan listings is often incomplete; PE and growth can be overridden. "
                       "PEG and NCAV do not apply to ETFs.")


# ---------------- 4. position sizing ----------------

with tab_size:
    st.caption("Rule 15 for any stock or ETF in the list; defaults to 0050.")
    nums = list(labels)
    snum = st.selectbox("Instrument", nums, index=nums.index("0050") if "0050" in nums else 0,
                        format_func=labels.get, key="size_num")
    smkt = stocks.loc[stocks.Number == snum, "Market"].iloc[0]
    hist = prices_tw(((snum, smkt),), "10y").get(snum)
    live = last(hist)
    price = st.number_input("Price (TWD)", 0.01, 100000.0, float(round(live, 2)) if live else 50.0, step=0.05,
                            help="Latest close from Yahoo; edit to today's quote.")
    if not live:
        st.warning("No live price — enter the price manually.")
    cards = st.session_state.get("macro_cards", [])
    act = [f"Rule {int(c['no'])}" for c in cards if c["status"] == "on"]
    if act:
        st.info("Active macro rules: " + ", ".join(act) + " — see the Market tab.")

    k_col, p_col = st.columns(2)
    with k_col, st.container(border=True):
        st.subheader("Half-Kelly 半凱利")
        capital = st.number_input("Total investable capital (TWD)", 0, 10**10, 1_000_000, step=50_000)
        held = st.number_input("Shares already held", 0, 10**8, 0, step=100)
        horizon = st.select_slider("Holding horizon (trading days)", [20, 60, 120, 250], 60)
        est = sizing.estimate_edge(hist["Close"], horizon) if hist is not None else None
        if est:
            st.caption(f"Estimated from {est[2]:,} overlapping {horizon}-day windows of adjusted history.")
        p = st.slider("Win rate p", 0.05, 0.95, round(est[0], 2) if est else 0.55, 0.01)
        b = st.number_input("Payoff ratio b (avg win ÷ avg loss)", 0.1, 20.0, round(est[1], 2) if est else 1.5, 0.05)
        frac = st.select_slider("Kelly fraction", [0.25, 0.5, 1.0], 0.5)
        k = sizing.kelly_shares(capital, held, price, p, b, frac)
        st.metric("Buy today", f"{k['buy_shares']:,} shares")
        st.caption(f"≈ NT${k['buy_shares'] * price:,.0f} · f = {frac:g} × (p − (1−p)/b) = **{k['f'] * 100:.1f}%** of capital → target "
                   f"NT${k['target_value']:,.0f} = {k['target_shares']:,} shares; you hold {held:,}.")

    with p_col, st.container(border=True):
        st.subheader("Pyramid 金字塔加碼")
        hi52 = float(hist["Close"].iloc[-250:].max()) if hist is not None else price
        ref = st.number_input("Reference high (TWD)", 0.01, 100000.0, float(round(max(hi52, price), 2)), step=0.05,
                              help="Defaults to the 52-week high close.")
        budget = st.number_input("Budget for the whole ladder (TWD)", 0, 10**10, 500_000, step=50_000)
        units = st.slider("Number of units", 2, 20, 10)
        step = st.slider("Add one unit every … % drop", 1, 15, 5) / 100
        bought = st.number_input("Units already bought", 0, units, 0)
        pl = sizing.pyramid_plan(ref, price, budget, units, step, bought)
        st.metric("Buy today", f"{pl['buy_shares']:,} shares")
        st.caption(f"{pl['units_due']} unit(s) ≈ NT${pl['cash_today']:,.0f} · drawdown from reference high: **{pl['drawdown'] * 100:.1f}%** → {pl['triggered']} level(s) reached.")
        st.dataframe(pl["ladder"], hide_index=True, width="stretch", height=250)

    with st.container(border=True):
        st.subheader("Rebalance check (rule 10)")
        c = st.columns(4)
        eq = c[0].number_input("Equity value", 0, 10**10, 700_000, step=10_000)
        bd = c[1].number_input("Bond value", 0, 10**10, 300_000, step=10_000)
        tgt = c[2].slider("Target equity %", 0, 100, 60)
        band = c[3].slider("Band ± %", 1, 20, 5)
        rb = sizing.rebalance(eq, bd, tgt, band)
        if rb["equity_pct"] is None:
            st.caption("Enter portfolio values.")
        elif rb["action"] == "sell_equity":
            st.warning(f"Equity is {rb['equity_pct']:.1f}% (> {tgt + band}%). "
                       f"Sell NT${rb['amount']:,.0f} of equity and buy bonds to return to {tgt}%.")
        elif rb["action"] == "buy_equity":
            st.info(f"Equity is {rb['equity_pct']:.1f}% (< {tgt - band}%). "
                    f"Move NT${rb['amount']:,.0f} from bonds to equity to return to {tgt}%.")
        else:
            st.success(f"Equity is {rb['equity_pct']:.1f}% — inside the {tgt}% ± {band}% band. No action.")


# ---------------- 5. stock list ----------------

with tab_list:
    st.caption("The list lives in `data/AllStock.xlsx` in the repo. Edits here last for this session — "
               "download the file and commit it to GitHub to make them permanent.")
    a, b_, c_ = st.columns([2, 2, 1])
    add = a.text_input("Add / watch stock numbers", placeholder="e.g. 2330, 00919, 6669")
    add_mkt = b_.radio("Market for new numbers", ["TSE", "OTC"], horizontal=True)
    if c_.button("Add", width="stretch") and add.strip():
        df_ = stocks.copy()
        for n in [data._norm_number(x) for x in add.replace("，", ",").replace(" ", ",").split(",") if x.strip()]:
            if n in set(df_.Number):
                df_.loc[df_.Number == n, "Watch"] = True
            else:
                df_.loc[len(df_)] = [n, "", add_mkt, True]
        st.session_state.stocks = df_.reset_index(drop=True)
        st.rerun()

    q = st.text_input("Filter", placeholder="number or name")
    only_w = st.toggle("Watchlist only", value=True)
    view = stocks
    if only_w:
        view = view[view.Watch]
    if q:
        view = view[view.Number.str.contains(q, case=False, regex=False) | view.Name.str.contains(q, case=False, regex=False)]
    edited = st.data_editor(
        view.reset_index(drop=True), hide_index=True, width="stretch", height=480, num_rows="dynamic", key=f"ed_{only_w}_{q}",
        column_config={"Number": st.column_config.TextColumn(required=True),
                       "Market": st.column_config.SelectboxColumn(options=["TSE", "OTC"], default="TSE"),
                       "Watch": st.column_config.CheckboxColumn(default=True)})
    if st.button("Apply table edits"):
        rest = stocks[~stocks.Number.isin(view.Number)]
        ed = edited.dropna(subset=["Number"]).copy()
        ed["Number"] = ed["Number"].map(data._norm_number)
        ed["Name"] = ed["Name"].fillna("")
        ed["Market"] = ed["Market"].fillna("TSE")
        ed["Watch"] = ed["Watch"].fillna(False).astype(bool)
        st.session_state.stocks = (pd.concat([rest, ed[data.COLS]])
                                   .drop_duplicates("Number", keep="last").reset_index(drop=True))
        st.rerun()
    st.caption(f"{len(stocks)} stocks · {int(stocks.Watch.sum())} on the watchlist. "
               "Delete rows by selecting them and pressing Delete, then **Apply table edits**.")

    d1_, d2_ = st.columns(2)
    d1_.download_button("⬇️ Download AllStock.xlsx", data.stock_list_to_excel(stocks), "AllStock.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    up = d2_.file_uploader("Load another Excel list for this session", type=["xlsx"], label_visibility="collapsed")
    if up is not None and st.session_state.get("uploaded_name") != up.name:
        try:
            st.session_state.stocks = data.load_stock_list(up)
            st.session_state.uploaded_name = up.name
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not read that file: {e}")


# ---------------- 6. rules ----------------

with tab_rules:
    st.markdown((ROOT / "RULES.md").read_text(encoding="utf-8"))

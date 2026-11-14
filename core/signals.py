"""The rule set. Each function is pure: data in, verdict out."""
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd
from . import indicators as ind


@dataclass
class Params:
    ma_trend: int = 60          # rule 4 moving average
    slope_days: int = 5         # rule 4: MA today vs MA n days ago
    lookback: int = 3           # event signals count if they fired within n bars
    breakout_n: int = 20        # rule 5
    exit_n: int = 10            # rule 5
    rsi_n: int = 14
    rsi_oversold: float = 30    # rule 6
    bb_n: int = 20
    squeeze_window: int = 126   # rule 7: ~6 months of trading days
    squeeze_recent: int = 5     # rule 7: squeeze low must be this recent
    vol_mult: float = 2.0       # rule 7: volume spike vs 20-day average
    kd_low: float = 20          # rule 14


def enrich(df: pd.DataFrame, p: Params = Params()) -> pd.DataFrame:
    """Add indicator columns to an OHLCV frame (Open High Low Close Volume)."""
    o = df.copy()
    c = o["Close"]
    for n in sorted({20, 60, 200, p.ma_trend}):
        o[f"MA{n}"] = ind.sma(c, n)
    o["RSI"] = ind.rsi(c, p.rsi_n)
    o["K"], o["D"] = ind.kd(o["High"], o["Low"], c)
    o["BBmid"], o["BBup"], o["BBlo"], o["BBw"] = ind.bollinger(c, p.bb_n)
    o["VolMA20"] = ind.sma(o["Volume"], 20)
    o["HighN"] = o["High"].rolling(p.breakout_n).max().shift(1)
    o["LowN"] = o["Low"].rolling(p.exit_n).min().shift(1)
    return o


def _recent(flag: pd.Series, n: int) -> bool:
    return bool(flag.iloc[-n:].fillna(False).any())


def stock_signals(df: pd.DataFrame, p: Params = Params()) -> dict:
    """Technical rules 4, 5, 6, 7, 14 for one stock. `df` is raw OHLCV."""
    if df is None or len(df) < 30:
        return {}
    o = enrich(df, p)
    c, ma = o["Close"], o[f"MA{p.ma_trend}"]

    # Rule 4: MA flat/rising AND close crosses above it
    cross_up = (c > ma) & (c.shift(1) <= ma.shift(1)) & (ma - ma.shift(p.slope_days) >= 0)
    r4 = _recent(cross_up, p.lookback)

    # Rule 5: Donchian breakout / exit (on the latest bar)
    r5_buy = bool(c.iloc[-1] > o["HighN"].iloc[-1]) if pd.notna(o["HighN"].iloc[-1]) else False
    r5_exit = bool(c.iloc[-1] < o["LowN"].iloc[-1]) if pd.notna(o["LowN"].iloc[-1]) else False

    # Rule 6: lower low in price, higher low in RSI, RSI < 30
    r6 = ind.bullish_divergence(o["Low"], o["RSI"], rsi_max=p.rsi_oversold)

    # Rule 7: bandwidth made its 6-month low very recently, then volume + upper-band break
    bw = o["BBw"]
    at_low = bw <= bw.rolling(p.squeeze_window, min_periods=p.squeeze_window // 2).min() * 1.0001
    r7 = bool(_recent(at_low, p.squeeze_recent)
              and o["Volume"].iloc[-1] > p.vol_mult * o["VolMA20"].iloc[-1]
              and c.iloc[-1] > o["BBup"].iloc[-1])

    # Rule 14: KD golden cross below 20 + RSI divergence + close back above MA20
    k, d = o["K"], o["D"]
    gc = (k > d) & (k.shift(1) <= d.shift(1)) & (np.minimum(k.shift(1), d.shift(1)) < p.kd_low)
    a = _recent(gc, 5)
    b = ind.bullish_divergence(o["Low"], o["RSI"])
    below = (c < o["MA20"]).iloc[-6:-1].any()
    cc = bool(c.iloc[-1] > o["MA20"].iloc[-1] and below)
    r14_parts = int(a) + int(b) + int(cc)

    last, prev = c.iloc[-1], c.iloc[-2]
    return {
        "close": float(last), "chg_pct": float((last / prev - 1) * 100),
        "rsi": float(o["RSI"].iloc[-1]), "k": float(k.iloc[-1]), "d": float(d.iloc[-1]),
        "r4_trend": r4, "r5_breakout": r5_buy, "r5_exit": r5_exit,
        "r6_rsi_div": r6, "r7_squeeze": r7,
        "r14_parts": r14_parts, "r14_combo": r14_parts == 3,
        "score": int(r4) + int(r5_buy) + int(r6) + int(r7) + int(r14_parts == 3) - int(r5_exit),
    }


# ---------- fundamentals (rules 11, 12) ----------

def peg(pe, eps_growth_pct):
    """Rule 11. Returns (peg, triggered). Growth in percent, e.g. 25 for 25%."""
    if pe is None or eps_growth_pct is None or pe <= 0 or eps_growth_pct <= 0:
        return None, None
    v = pe / eps_growth_pct
    return v, v < 1.0


def ncav(price, current_assets, total_liabilities, shares):
    """Rule 12 (Graham net-net). Returns (ncav_per_share, triggered)."""
    if None in (price, current_assets, total_liabilities, shares) or not shares:
        return None, None
    v = (current_assets - total_liabilities) / shares
    return v, price < 0.67 * v


# ---------- macro (rules 1, 2, 3, 8, 9, 13) ----------

LIGHTS = [(16, "Blue 藍燈"), (22, "Yellow-blue 黃藍燈"), (31, "Green 綠燈"),
          (37, "Yellow-red 黃紅燈"), (45, "Red 紅燈")]


def light_name(score):
    for hi, name in LIGHTS:
        if score <= hi:
            return name
    return "?"


def yield_curve_state(spread: pd.Series, min_inverted_days: int = 60, window_days: int = 365):
    """Rule 9. True if the 10Y-2Y spread crossed back above 0 within `window_days`
    after an inversion that lasted at least `min_inverted_days` observations."""
    s = spread.dropna()
    if s.empty:
        return None, None
    neg = s < 0
    cross = (~neg) & neg.shift(1, fill_value=False)
    for dt in reversed(list(s.index[cross])):
        run = 0
        for v in reversed(neg[:dt].iloc[:-1].tolist()):
            if not v:
                break
            run += 1
        if run >= min_inverted_days:
            days = (s.index[-1] - dt).days
            return bool(days <= window_days and s.iloc[-1] > 0), dt
    return False, None


def macro_signals(m: dict, margin_drop_thr: float = 2.0) -> list[dict]:
    """m keys (any may be None): mcap_gdp, fear_greed, index_close, index_ma200,
    maint_ratio, margin_drop_1d, margin_drop_5d, cycle_score, curve_uninverted,
    curve_date, vix. Drops are positive percentages."""
    def card(no, name, side, cond, value, need):
        missing = [k for k in need if m.get(k) is None]
        return {"no": no, "name": name, "side": side, "value": value,
                "status": "na" if missing else ("on" if cond() else "off"),
                "missing": missing}

    g = m.get
    out = [
        card(1, "Buffett indicator 市值/GDP < 75%", "buy", lambda: g("mcap_gdp") < 75,
             f"{g('mcap_gdp')}%" if g("mcap_gdp") is not None else "—", ["mcap_gdp"]),
        card(2, "Fear & Greed < 20 and index < 200MA", "buy",
             lambda: g("fear_greed") < 20 and g("index_close") < g("index_ma200"),
             f"F&G {g('fear_greed'):.0f}" if g("fear_greed") is not None else "—",
             ["fear_greed", "index_close", "index_ma200"]),
        card(3, f"融資維持率 < 140% and margin balance 1-day drop > {margin_drop_thr:g}%", "buy",
             lambda: g("maint_ratio") < 140 and g("margin_drop_1d") > margin_drop_thr,
             f"{g('maint_ratio')}%" if g("maint_ratio") is not None else "—",
             ["maint_ratio", "margin_drop_1d"]),
        card(8, "景氣對策信號 ≤ 16 (blue) → buy 0050", "buy", lambda: g("cycle_score") <= 16,
             f"{g('cycle_score')} · {light_name(g('cycle_score'))}" if g("cycle_score") is not None else "—",
             ["cycle_score"]),
        card(8.5, "景氣對策信號 ≥ 38 (red) → take profit", "defend", lambda: g("cycle_score") >= 38,
             f"{g('cycle_score')} · {light_name(g('cycle_score'))}" if g("cycle_score") is not None else "—",
             ["cycle_score"]),
        card(9, "10Y-2Y spread back above 0 after inversion → hold cash", "defend",
             lambda: bool(g("curve_uninverted")),
             f"un-inverted {g('curve_date'):%Y-%m-%d}" if g("curve_date") is not None else "—",
             ["curve_uninverted"]),
        card(13, f"VIX > 30 + 融資大減 (5-day drop > {2.5 * margin_drop_thr:g}%) + 藍燈", "buy",
             lambda: g("vix") > 30 and g("margin_drop_5d") > 2.5 * margin_drop_thr and g("cycle_score") <= 16,
             f"VIX {g('vix'):.1f}" if g("vix") is not None else "—",
             ["vix", "margin_drop_5d", "cycle_score"]),
    ]
    return out

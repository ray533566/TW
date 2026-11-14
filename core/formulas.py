"""Classic investing formulas from around the world. Pure functions: data in, numbers out."""
import math

import pandas as pd


# ---------- trend and momentum (price only) ----------

def momentum_12_1(close: pd.Series) -> float | None:
    """Jegadeesh-Titman momentum: % return from 12 months ago to 1 month ago."""
    if close is None or len(close) < 253:
        return None
    return float((close.iloc[-22] / close.iloc[-253] - 1) * 100)


def above_10m_sma(close: pd.Series) -> bool | None:
    """Faber timing rule: latest close above the average of the last 10 month-end closes."""
    if close is None or len(close) < 200:
        return None
    m = close.groupby(close.index.to_period("M")).last()
    if len(m) < 10:
        return None
    return bool(close.iloc[-1] > m.iloc[-10:].mean())


def sharpe(close: pd.Series, rf_pct: float = 1.5, days: int = 252) -> float | None:
    """Sharpe ratio over the last `days` bars: (annual return - risk-free) / annual volatility."""
    r = close.iloc[-days - 1:].pct_change().dropna()
    if len(r) < 60 or r.std() == 0:
        return None
    return float((r.mean() * 252 - rf_pct / 100) / (r.std() * math.sqrt(252)))


def max_drawdown(close: pd.Series, days: int = 252) -> float | None:
    """Deepest peak-to-trough fall over the last `days` bars, in % (negative)."""
    c = close.iloc[-days:]
    if len(c) < 2:
        return None
    return float((c / c.cummax() - 1).min() * 100)


def trend_table(prices: dict, names: dict, bench: str = "0050") -> pd.DataFrame:
    """One row per stock. Trend is Up when momentum > 0 and price is above its 10-month average,
    Out when both fail, Mixed otherwise (Antonacci absolute momentum + Faber timing)."""
    b = momentum_12_1(prices[bench]["Close"]) if bench in prices else None
    rows = []
    for num, df in prices.items():
        c = df["Close"]
        mom, sma = momentum_12_1(c), above_10m_sma(c)
        if mom is None or sma is None:
            trend = "n/a"
        else:
            trend = "Up" if mom > 0 and sma else ("Out" if mom <= 0 and not sma else "Mixed")
        rows.append({"Number": num, "Name": names.get(num, ""), "Close": float(c.iloc[-1]),
                     "Mom 12-1 %": mom, "Beats 0050": None if mom is None or b is None else bool(mom > b),
                     "Above 10M avg": sma, "Sharpe 1y": sharpe(c), "Max DD 1y %": max_drawdown(c),
                     "Trend": trend})
    out = pd.DataFrame(rows)
    return out.sort_values("Mom 12-1 %", ascending=False, na_position="last").reset_index(drop=True) if len(out) else out


# ---------- value and quality (fundamentals) ----------

def _ratio(a, b):
    return None if a is None or b is None or b == 0 else a / b


def graham_number(eps, bvps) -> float | None:
    """Graham: fair price = sqrt(22.5 x EPS x book value per share). Needs both positive."""
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def magic_formula(ebit, ev, nwc, net_fixed):
    """Greenblatt: (earnings yield %, return on capital %) = (EBIT / EV, EBIT / (NWC + net fixed assets)).
    Negative working capital counts as zero."""
    ey = ebit / ev * 100 if ebit is not None and ev is not None and ev > 0 else None
    cap = None if nwc is None or net_fixed is None else max(nwc, 0) + net_fixed
    roc = ebit / cap * 100 if ebit is not None and cap is not None and cap > 0 else None
    return ey, roc


def piotroski(cur: dict, prev: dict):
    """Piotroski F-Score. cur/prev hold ni, cfo, assets, ltd, ca, cl, shares, gp, rev for the two
    latest fiscal years (any may be None). Returns (score, checks_available, [(label, True/False/None)])."""
    g, p = cur.get, prev.get

    def gt(a, b):
        return None if a is None or b is None else bool(a > b)

    def ge(a, b):
        return None if a is None or b is None else bool(a >= b)

    roa, roa0 = _ratio(g("ni"), g("assets")), _ratio(p("ni"), p("assets"))
    checks = [
        ("Return on assets > 0", gt(roa, 0)),
        ("Operating cash flow > 0", gt(g("cfo"), 0)),
        ("Return on assets improved", gt(roa, roa0)),
        ("Cash flow > net income", gt(g("cfo"), g("ni"))),
        ("Long-term debt / assets did not rise", ge(_ratio(p("ltd"), p("assets")), _ratio(g("ltd"), g("assets")))),
        ("Current ratio improved", gt(_ratio(g("ca"), g("cl")), _ratio(p("ca"), p("cl")))),
        ("No new shares issued", ge(p("shares"), g("shares"))),
        ("Gross margin improved", gt(_ratio(g("gp"), g("rev")), _ratio(p("gp"), p("rev")))),
        ("Asset turnover improved", gt(_ratio(g("rev"), g("assets")), _ratio(p("rev"), p("assets")))),
    ]
    return sum(1 for _, v in checks if v), sum(1 for _, v in checks if v is not None), checks


# ---------- compounding ----------

def compound_path(start: float, monthly: float, annual_pct: float, years: int) -> pd.DataFrame:
    """Year-by-year value of `start` plus `monthly` contributions at `annual_pct` compounded monthly."""
    r = (1 + annual_pct / 100) ** (1 / 12) - 1
    v, paid, rows = float(start), float(start), [(0, float(start), float(start))]
    for m in range(1, years * 12 + 1):
        v = v * (1 + r) + monthly
        paid += monthly
        if m % 12 == 0:
            rows.append((m // 12, paid, v))
    return pd.DataFrame(rows, columns=["Year", "Paid in", "Value"])


def doubling_years(annual_pct: float):
    """(Rule of 72 estimate, exact) years to double. None if the rate is not positive."""
    if annual_pct <= 0:
        return None, None
    return 72 / annual_pct, math.log(2) / math.log(1 + annual_pct / 100)

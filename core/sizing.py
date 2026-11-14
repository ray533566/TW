"""Position sizing: half-Kelly, pyramid averaging-down, rebalancing (rules 10, 15)."""
import math
import pandas as pd


def kelly_fraction(p: float, b: float) -> float:
    """Full Kelly f* = p - (1-p)/b, floored at 0. p = win rate, b = avg win / avg loss."""
    if b <= 0:
        return 0.0
    return max(0.0, p - (1 - p) / b)


def estimate_edge(close: pd.Series, horizon: int = 60):
    """Win rate and payoff ratio of holding `horizon` trading days, from history."""
    r = (close.shift(-horizon) / close - 1).dropna()
    wins, losses = r[r > 0], r[r < 0]
    if len(r) < 30 or wins.empty or losses.empty:
        return None
    return float(len(wins) / len(r)), float(wins.mean() / abs(losses.mean())), len(r)


def kelly_shares(capital: float, held_shares: int, price: float, p: float, b: float,
                 fraction: float = 0.5) -> dict:
    f = kelly_fraction(p, b) * fraction
    target_value = capital * f
    gap = target_value - held_shares * price
    return {"f": f, "target_value": target_value,
            "target_shares": math.floor(target_value / price),
            "buy_shares": max(0, math.floor(gap / price))}


def pyramid_plan(ref_high: float, price: float, budget: float, units: int = 10,
                 step: float = 0.05, units_bought: int = 0) -> dict:
    """One unit of cash for every `step` drop from `ref_high`."""
    unit_cash = budget / units
    dd = max(0.0, 1 - price / ref_high)
    triggered = min(units, math.floor(dd / step + 1e-9))
    due = max(0, triggered - units_bought)
    ladder = pd.DataFrame({
        "Level": range(1, units + 1),
        "Drop": [f"-{step * i * 100:.0f}%" for i in range(1, units + 1)],
        "Trigger price": [round(ref_high * (1 - step * i), 2) for i in range(1, units + 1)],
        "Cash": [round(unit_cash)] * units,
        "Shares": [math.floor(unit_cash / (ref_high * (1 - step * i))) for i in range(1, units + 1)],
    })
    ladder["Status"] = ["bought" if i <= units_bought else ("BUY NOW" if i <= triggered else "waiting")
                        for i in ladder["Level"]]
    return {"drawdown": dd, "triggered": triggered, "units_due": due,
            "cash_today": due * unit_cash,
            "buy_shares": math.floor(due * unit_cash / price), "ladder": ladder}


def rebalance(equity: float, bonds: float, target_pct: float, band: float = 5.0) -> dict:
    """Rule 10: if equity share > target + band, sell back to target."""
    total = equity + bonds
    if total <= 0:
        return {"equity_pct": None, "action": "none", "amount": 0.0}
    pct = equity / total * 100
    diff = equity - total * target_pct / 100
    if pct > target_pct + band:
        return {"equity_pct": pct, "action": "sell_equity", "amount": diff}
    if pct < target_pct - band:
        return {"equity_pct": pct, "action": "buy_equity", "amount": -diff}
    return {"equity_pct": pct, "action": "none", "amount": 0.0}

"""Technical indicators on pandas Series. No I/O, no Streamlit."""
import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI."""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return out.where(dn != 0, 100.0).where(up.notna())


def kd(high, low, close, n: int = 9):
    """Taiwan-style stochastic KD(9,3,3): K = 2/3*K[-1] + 1/3*RSV, seeded at 50."""
    ll, hh = low.rolling(n).min(), high.rolling(n).max()
    rsv = ((close - ll) / (hh - ll).replace(0, np.nan) * 100).fillna(50)
    k = np.full(len(close), 50.0)
    d = np.full(len(close), 50.0)
    r = rsv.to_numpy()
    for i in range(1, len(r)):
        k[i] = k[i - 1] * 2 / 3 + r[i] / 3
        d[i] = d[i - 1] * 2 / 3 + k[i] / 3
    return pd.Series(k, close.index), pd.Series(d, close.index)


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    return mid, upper, lower, (upper - lower) / mid


def bullish_divergence(low: pd.Series, rsi_s: pd.Series, recent: int = 10,
                       prior: int = 30, rsi_max: float | None = None) -> bool:
    """Price makes a lower low while RSI makes a higher low.

    Compares the lowest low of the last `recent` bars with the lowest low of
    the `prior` bars before them. `rsi_max` additionally requires RSI at the
    recent low to be below that level (e.g. 30).
    """
    if len(low) < recent + prior:
        return False
    r, p = low.iloc[-recent:], low.iloc[-(recent + prior):-recent]
    ir, ip = r.idxmin(), p.idxmin()
    a, b = rsi_s.get(ir), rsi_s.get(ip)
    if pd.isna(a) or pd.isna(b):
        return False
    ok = low[ir] < low[ip] and a > b
    return bool(ok and (rsi_max is None or a < rsi_max))

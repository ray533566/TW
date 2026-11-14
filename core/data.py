"""Data access: stock list (Excel), prices (Yahoo), macro series. No Streamlit."""
import io
import json
import re
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
COLS = ["Number", "Name", "Market", "Watch"]


# ---------- stock list ----------

def _cell(v):
    """Google Sheets exports IMPORTRANGE cells as =IFERROR(...,<cached value>)."""
    if isinstance(v, str) and v.startswith("=IFERROR("):
        m = re.search(r"\),(.*)\)$", v, re.S)
        if m:
            s = m.group(1)
            return s[1:-1].replace('""', '"') if s.startswith('"') else s
    return v


def _norm_number(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip().upper()
    return s.zfill(4) if s.isdigit() and len(s) < 4 else s


def load_stock_list(src) -> pd.DataFrame:
    """Read the stock list from a path or file-like object.

    Accepts the clean format (columns Number, Name, optional Market, Watch) or the
    raw Google-Sheets export, where a block after a run of blank rows is OTC.
    """
    import openpyxl
    ws = openpyxl.load_workbook(src, read_only=True).worksheets[0]
    rows = [[_cell(c) for c in r[:8]] for r in ws.iter_rows(values_only=True)]
    hdr = next((i for i, r in enumerate(rows) if r and str(r[0]).strip() == "Number"), None)
    if hdr is None:
        raise ValueError("No 'Number' header found in column A.")
    names = [str(c).strip() if c is not None else "" for c in rows[hdr]]
    i_mkt = names.index("Market") if "Market" in names else None
    i_watch = names.index("Watch") if "Watch" in names else None

    out, seen, blanks, otc = [], set(), 0, False
    for r in rows[hdr + 1:]:
        num = _norm_number(r[0] if r else None)
        if not num:
            blanks += 1
            continue
        if blanks >= 5 and i_mkt is None:
            otc = True
        blanks = 0
        if num == "NUMBER" or not re.fullmatch(r"[0-9A-Z]{4,6}", num) or num in seen:
            continue
        seen.add(num)
        mkt = str(r[i_mkt]).strip().upper() if i_mkt is not None and r[i_mkt] else ("OTC" if otc else "TSE")
        watch = str(r[i_watch]).strip().upper() in ("Y", "YES", "TRUE", "1") if i_watch is not None else False
        out.append([num, str(r[1] or "").strip(), "OTC" if mkt.startswith("O") else "TSE", watch])
    return pd.DataFrame(out, columns=COLS)


def stock_list_to_excel(df: pd.DataFrame) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stocks"
    ws.append(COLS)
    for r in df.sort_values(["Market", "Number"], ascending=[False, True]).itertuples(index=False):
        ws.append([str(r.Number), r.Name, r.Market, "Y" if r.Watch else None])
    for c in ws["A"]:
        c.number_format = "@"
    ws.column_dimensions["B"].width = 22
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def load_macro_inputs(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------- prices ----------

def yf_symbol(number: str, market: str) -> str:
    return f"{number}.{'TWO' if market == 'OTC' else 'TW'}"


def _split(raw, symbols) -> dict:
    out = {}
    if raw is None or raw.empty:
        return out
    for s in symbols:
        try:
            df = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            if len(df):
                df.index = pd.to_datetime(df.index).tz_localize(None)
                out[s] = df
        except KeyError:
            pass
    return out


def fetch_prices(symbols: list[str], period: str = "2y", chunk: int = 150) -> dict:
    """Daily adjusted OHLCV per Yahoo symbol. Missing symbols are simply absent."""
    import yfinance as yf
    out = {}
    symbols = list(dict.fromkeys(symbols))
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        try:
            raw = yf.download(part, period=period, interval="1d", auto_adjust=True,
                              group_by="ticker", progress=False, threads=True)
            out.update(_split(raw, part))
        except Exception:
            continue
    return out


def fetch_tw_prices(stocks: list[tuple[str, str]], period: str = "2y") -> dict:
    """stocks = [(number, market)]. Returns {number: OHLCV}. If a number has no data
    on its listed market, the other market's suffix is tried once."""
    first = {yf_symbol(n, m): n for n, m in stocks}
    got = fetch_prices(list(first), period)
    out = {first[s]: df for s, df in got.items()}
    miss = {yf_symbol(n, "TSE" if m == "OTC" else "OTC"): n for n, m in stocks if n not in out}
    if miss:
        out.update({miss[s]: df for s, df in fetch_prices(list(miss), period).items()})
    return out


def fetch_fundamentals(symbol: str) -> dict:
    """PE, annual EPS growth %, and net-current-asset inputs from Yahoo. Any may be None."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    d = {"pe": None, "eps_growth_pct": None, "current_assets": None,
         "total_liabilities": None, "shares": None, "eps": None}
    try:
        info = t.info or {}
        d["pe"], d["eps"] = info.get("trailingPE"), info.get("trailingEps")
        d["shares"] = info.get("sharesOutstanding")
        if info.get("earningsGrowth") is not None:
            d["eps_growth_pct"] = info["earningsGrowth"] * 100
    except Exception:
        pass
    try:
        inc = t.income_stmt
        for row in ("Diluted EPS", "Basic EPS"):
            if row in inc.index:
                e = inc.loc[row].dropna()
                if len(e) >= 2 and e.iloc[1] > 0:
                    d["eps_growth_pct"] = float((e.iloc[0] / e.iloc[1] - 1) * 100)
                    break
    except Exception:
        pass
    try:
        bs = t.balance_sheet
        col = bs.columns[0]
        if "Current Assets" in bs.index:
            d["current_assets"] = float(bs.loc["Current Assets", col])
        for row in ("Total Liabilities Net Minority Interest", "Total Liab"):
            if row in bs.index:
                d["total_liabilities"] = float(bs.loc[row, col])
                break
    except Exception:
        pass
    return d


# ---------- macro series ----------

def fetch_t10y2y() -> pd.Series:
    """US 10Y-2Y Treasury spread, daily, from FRED (no API key)."""
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y2Y", headers=UA, timeout=15)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    return s.dropna()


def fetch_fear_greed() -> float:
    """CNN Fear & Greed index (US market sentiment), 0-100."""
    r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", headers=UA, timeout=15)
    r.raise_for_status()
    return float(r.json()["fear_and_greed"]["score"])


def fetch_margin_balance(days: int = 40) -> pd.Series:
    """Market-wide margin purchase balance (融資餘額, TWD) by day, from FinMind."""
    start = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    r = requests.get("https://api.finmindtrade.com/api/v4/data",
                     params={"dataset": "TaiwanStockTotalMarginPurchaseShortSale", "start_date": start},
                     headers=UA, timeout=20)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["data"])
    df = df[df["name"] == "MarginPurchaseMoney"]
    s = pd.to_numeric(df["TodayBalance"], errors="coerce")
    s.index = pd.to_datetime(df["date"])
    return s.dropna().sort_index()


def pct_drop(s: pd.Series, n: int) -> float | None:
    """Percentage fall over the last n observations (positive = fell)."""
    if s is None or len(s) <= n:
        return None
    return float((1 - s.iloc[-1] / s.iloc[-1 - n]) * 100)

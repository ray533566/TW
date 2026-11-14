# Taiwan Invest Signals

A Streamlit dashboard that applies 15 mechanical investing rules to the Taiwan market and to the
stocks in `data/AllStock.xlsx`.

| Tab | What it does |
|-----|--------------|
| Market | Macro rules 1, 2, 3, 8, 9, 13 as triggered / not triggered / needs-data cards |
| Screener | Technical rules 4, 5, 6, 7, 14 across the watchlist or the whole TSE / OTC list |
| Stock | Candlestick + MA / Bollinger / RSI / KD for one stock, plus PEG and NCAV (rules 11, 12) |
| Position sizing | Half-Kelly and pyramid ladders → shares to buy today (rule 15); rebalance check (rule 10) |
| Stock list | Add, remove, and watch stocks; download the updated Excel |
| Rules | Exact definition of every rule |

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

1. Push this folder to a GitHub repository.
2. On share.streamlit.io choose **New app**, pick the repository, and set the main file to `app.py`.

## Maintaining the data

**Stock list — `data/AllStock.xlsx`**

| Column | Meaning |
|--------|---------|
| Number | Stock code, stored as text so `0050` keeps its zeros |
| Name | Display name |
| Market | `TSE` (上市, Yahoo suffix `.TW`) or `OTC` (上櫃, `.TWO`) |
| Watch | `Y` puts the stock on the default watchlist |

Edit the file and commit it, or edit in the app's **Stock list** tab, download, and commit.
A raw Google Sheets export in the original layout is also accepted. If a number has no data on its
listed market, the app retries the other one.

**Macro inputs — `data/macro_inputs.json`**

Three inputs have no dependable free API, so they are kept in this file and can be overridden in the sidebar:
the NDC business-cycle score (monthly), total market cap / GDP, and the market margin maintenance ratio
(TWSE 台股儀表板, daily). Use `null` for unknown.

## Data sources

| Data | Source | Notes |
|------|--------|-------|
| Prices, TAIEX, VIX, fundamentals | Yahoo Finance via `yfinance` | Cached 1 hour; fundamentals for Taiwan listings are often incomplete |
| 10Y–2Y spread | FRED `T10Y2Y` CSV | No key needed |
| Fear & Greed | CNN endpoint | US sentiment; unofficial endpoint, override in sidebar if it fails |
| 融資餘額 | FinMind `TaiwanStockTotalMarginPurchaseShortSale` | Free tier is rate-limited; override in sidebar if it fails |

Any source that fails leaves its rule in the "needs data" state instead of breaking the page.

## Tests

```bash
pip install pytest
python -m pytest tests -q
```

`tests/test_core.py` checks each rule against hand-built cases. `tests/test_app.py` runs the whole page
with network calls replaced by synthetic data, online and offline.

## Disclaimer

Rule outputs are for study and are not investment advice.

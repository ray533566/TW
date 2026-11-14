### How each rule is computed

| # | Rule | Where | Data | Exact definition used |
|---|------|-------|------|-----------------------|
| 1 | Market cap / GDP < 75% → strong buy | Market | manual | Sidebar or `macro_inputs.json` |
| 2 | Fear & Greed < 20 and price < 200MA → accumulate | Market | CNN (US index), Yahoo `^TWII` | TAIEX close below its 200-day SMA |
| 3 | 融資維持率 < 140% and margin balance drop > threshold → contrarian buy | Market | manual ratio; FinMind 融資餘額 | 1-day % fall in market margin balance, threshold in sidebar (default 2%) |
| 4 | MA slope ≥ 0 and price crosses above MA → trend buy | Screener | Yahoo | Close crosses above MA(60 by default) while MA ≥ MA 5 bars ago, within the lookback |
| 5 | Close > 20-day high → breakout; close < 10-day low → exit | Screener | Yahoo | Highs/lows of the *prior* 20 / 10 bars |
| 6 | Lower low + higher RSI low + RSI < 30 → reversal buy | Screener | Yahoo | Lowest low of last 10 bars vs lowest low of the 30 bars before; RSI(14) compared at those two bars |
| 7 | BB bandwidth at 6-month low + volume spike + close > upper band | Screener | Yahoo | Bandwidth hit its 126-bar low within 5 bars; volume > 2× 20-day average |
| 8 | 景氣對策信號 ≤ 16 → buy 0050; ≥ 38 → take profit | Market | manual | NDC monthly score |
| 9 | 10Y–2Y crosses above 0 after inversion → defensive | Market | FRED `T10Y2Y` | Cross within the last 365 days after ≥ 60 inverted observations |
| 10 | Equity > target + 5% → sell equity, buy bonds | Position sizing | manual | Amount needed to return to target |
| 11 | PE ÷ EPS growth < 1 → undervalued growth | Stock | Yahoo | Annual diluted EPS growth, latest year vs prior |
| 12 | Price < 0.67 × NCAV/share → deep value | Stock | Yahoo | (Current assets − total liabilities) ÷ shares |
| 13 | VIX > 30 + 融資大減 + 藍燈 | Market | Yahoo `^VIX`, FinMind, manual | 5-day margin drop > 2.5× the rule-3 threshold; score ≤ 16 |
| 14 | 日KD < 20 黃金交叉 + RSI 底背離 + 站回 20MA | Screener | Yahoo | KD(9,3,3) cross with K or D < 20 in last 5 bars; divergence as rule 6 without the RSI < 30 cap; close above MA20 after being below within 5 bars. Shown as n/3 |
| 15 | Half-Kelly or pyramid → shares to buy today | Position sizing | Yahoo + manual | Kelly f = p − (1−p)/b, halved; pyramid adds one equal unit per 5% drop from the reference high |

Prices are Yahoo Finance daily bars adjusted for splits and dividends, cached for one hour.
These are mechanical rule outputs for study. They are not investment advice.

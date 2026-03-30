# Market Sentiment Dashboard

Institutional-grade market fragility monitor with 16 independent indicators.

## Indicators

### Volatility & Fear
1. **VIX Level** — Fear gauge absolute level + percentile
2. **VIX Term Structure** — Contango/backwardation detection
3. **Put/Call Ratio** — SQQQ/TQQQ volume proxy
4. **SKEW Index** — Tail risk hedging demand

### Credit & Bonds
5. **Credit Spreads (HY-IG)** — LQD/HYG ratio as spread proxy
6. **Yield Curve (10Y-2Y)** — Inversion detection
7. **TLT Momentum** — Flight to safety indicator

### Equity Internals
8. **Market Breadth** — RSP/SPY equal-weight divergence
9. **Distance from 52W High** — S&P 500 positioning
10. **S&P 500 RSI** — Overbought/oversold

### Leverage & Positioning
11. **Leverage Activity Trend** — Combined leveraged ETF volume
12. **Bull/Bear ETF Ratio** — Retail positioning proxy

### Fund Flows & Sentiment
13. **Sentiment Momentum** — Blended price momentum proxy
14. **Fear & Greed Composite** — Multi-factor sentiment score
15. **Gold/SPY Ratio** — Risk-off rotation detection

### Macro
16. **USD Strength** — Dollar tightening conditions

## Philosophy

> "机构不预测事件，机构管理脆弱性。"
> Institutions don't predict events. They manage fragility.

## Updates

Data refreshes weekdays at 7:00 AM and 12:30 PM PT via automated cron jobs.

## Stack

- Pure HTML/CSS/JS frontend (no framework)
- Python (yfinance, pandas, numpy) for data fetching
- Vercel for hosting

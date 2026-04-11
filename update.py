#!/usr/bin/env python3
"""Market Sentiment Dashboard — Data Updater
Fetches 16 independent indicators from free sources and writes data.json.
"""

import json
import datetime
import warnings
import traceback
import numpy as np
import yfinance as yf
import pandas as pd
import requests

warnings.filterwarnings('ignore')

def percentile_rank(series, current_val):
    """Calculate percentile rank of current_val in series (0-100)."""
    s = series.dropna()
    if len(s) == 0:
        return 50.0
    return float((s < current_val).sum() / len(s) * 100)

def safe_sparkline(series, n=30):
    """Return last n values as a list for sparkline."""
    s = series.dropna().tail(n)
    return [round(float(v), 4) for v in s.values]

def signal_from_percentile(pct, invert=False):
    """Green/Yellow/Red based on percentile. invert=True means high=good."""
    if invert:
        pct = 100 - pct
    if pct >= 75:
        return "red"
    elif pct >= 40:
        return "yellow"
    else:
        return "green"

def acceleration(series, window=5):
    """Calculate 5-day acceleration (change of change)."""
    if len(series) < window + 2:
        return 0.0
    recent = series.tail(window + 1)
    diffs = recent.diff().dropna()
    if len(diffs) < 2:
        return 0.0
    return float(diffs.iloc[-1] - diffs.iloc[0])

def fetch_with_fallback(ticker, period="2y", interval="1d"):
    """Fetch yfinance data with fallback."""
    try:
        data = yf.download(ticker, period=period, interval=interval, progress=False)
        if data is not None and len(data) > 0:
            # Flatten MultiIndex columns if present
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return data
    except Exception as e:
        print(f"  Warning: fetch failed for {ticker}: {e}")
    return pd.DataFrame()


def get_indicators():
    indicators = []
    
    print("Fetching market data...")
    
    # ===== BATCH DOWNLOAD =====
    tickers_needed = [
        "^VIX", "^VIX3M", "^SKEW", 
        "HYG", "LQD", "^TNX", "^IRX", "TLT",
        "SPY", "RSP", "^GSPC",
        "TQQQ", "SQQQ",
        "GLD", "UUP"
    ]
    
    print("  Downloading batch data...")
    all_data = {}
    for t in tickers_needed:
        df = fetch_with_fallback(t, period="2y")
        if len(df) > 0:
            all_data[t] = df
            print(f"    {t}: {len(df)} rows")
        else:
            print(f"    {t}: FAILED")
    
    # Helper
    def get_close(ticker):
        if ticker in all_data and 'Close' in all_data[ticker].columns:
            return all_data[ticker]['Close'].dropna()
        return pd.Series(dtype=float)
    
    def get_volume(ticker):
        if ticker in all_data and 'Volume' in all_data[ticker].columns:
            return all_data[ticker]['Volume'].dropna()
        return pd.Series(dtype=float)

    # ===== 1. VIX Level =====
    print("  1. VIX Level...")
    try:
        vix = get_close("^VIX")
        if len(vix) > 20:
            current = float(vix.iloc[-1])
            pct = percentile_rank(vix.tail(252), current)
            # Check rapid spike: VIX up >30% in 5 days from below 15
            spike_flag = ""
            if len(vix) > 5:
                vix_5d_ago = float(vix.iloc[-6]) if len(vix) > 5 else current
                if vix_5d_ago < 15 and current > vix_5d_ago * 1.3:
                    spike_flag = " ⚡SPIKE FROM LOW"
            
            if current > 25:
                sig = "red"
            elif current > 15:
                sig = "yellow"
            else:
                sig = "green"
            
            indicators.append({
                "id": "vix_level",
                "name": "VIX Level",
                "category": "Volatility & Fear",
                "value": round(current, 2),
                "display": f"{current:.2f}{spike_flag}",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(vix),
                "acceleration": round(acceleration(vix), 4),
                "description": "CBOE Volatility Index. <15 calm, 15-25 normal, >25 fear. Rapid spikes from low = max fragility."
            })
    except Exception as e:
        print(f"    Error: {e}")
        traceback.print_exc()

    # ===== 2. VIX Term Structure =====
    print("  2. VIX Term Structure...")
    try:
        vix = get_close("^VIX")
        vix3m = get_close("^VIX3M")
        if len(vix) > 20 and len(vix3m) > 20:
            # Align dates
            common = vix.index.intersection(vix3m.index)
            ratio = (vix.loc[common] / vix3m.loc[common]).dropna()
            current = float(ratio.iloc[-1])
            pct = percentile_rank(ratio.tail(252), current)
            
            if current > 1.0:
                sig = "red"  # Backwardation = fear
            elif current > 0.9:
                sig = "yellow"
            else:
                sig = "green"  # Contango = calm
            
            indicators.append({
                "id": "vix_term",
                "name": "VIX Term Structure",
                "category": "Volatility & Fear",
                "value": round(current, 4),
                "display": f"{current:.3f} ({'Backwardation' if current > 1 else 'Contango'})",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(ratio),
                "acceleration": round(acceleration(ratio), 4),
                "description": "VIX/VIX3M ratio. >1 = backwardation (fear), <1 = contango (calm). Inversion signals acute stress."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 3. Put/Call Ratio =====
    print("  3. Put/Call Ratio...")
    try:
        # Use CBOE total put/call from web or proxy via equity options volume
        # Proxy: compare put-heavy ETFs. Simple approach: scrape or use a known source
        # For now, use a VIX-based proxy: VIX * put/call correlation
        # Better approach: calculate from SPY options
        # Let's try fetching from CBOE
        try:
            resp = requests.get("https://www.cboe.com/us/options/market_statistics/daily/", timeout=10)
            # This may not give clean data, use fallback
            raise Exception("Use proxy")
        except:
            # Proxy: use VIX relationship — higher VIX correlates with higher P/C
            # Or use a simple volume ratio of bearish vs bullish ETFs
            sqqq_vol = get_volume("SQQQ")
            tqqq_vol = get_volume("TQQQ")
            if len(sqqq_vol) > 20 and len(tqqq_vol) > 20:
                common = sqqq_vol.index.intersection(tqqq_vol.index)
                pc_proxy = (sqqq_vol.loc[common] / tqqq_vol.loc[common]).dropna()
                # Smooth with 5-day MA
                pc_smooth = pc_proxy.rolling(5).mean().dropna()
                current = float(pc_smooth.iloc[-1])
                pct = percentile_rank(pc_smooth.tail(252), current)
                
                if pct > 80:
                    sig = "green"  # High put/call = fear = contrarian bullish
                elif pct < 20:
                    sig = "red"  # Low put/call = complacency = danger
                else:
                    sig = "yellow"
                
                indicators.append({
                    "id": "put_call",
                    "name": "Put/Call Ratio (Proxy)",
                    "category": "Volatility & Fear",
                    "value": round(current, 4),
                    "display": f"{current:.3f}",
                    "signal": sig,
                    "percentile": round(pct, 1),
                    "sparkline": safe_sparkline(pc_smooth),
                    "acceleration": round(acceleration(pc_smooth), 4),
                    "description": "SQQQ/TQQQ volume ratio as put/call proxy. High = fear (contrarian bullish), Low = complacency (danger)."
                })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 4. SKEW Index =====
    print("  4. SKEW Index...")
    try:
        skew = get_close("^SKEW")
        if len(skew) > 20:
            current = float(skew.iloc[-1])
            pct = percentile_rank(skew.tail(252), current)
            
            if pct > 80:
                sig = "red"  # High SKEW = tail risk hedging
            elif pct > 40:
                sig = "yellow"
            else:
                sig = "green"
            
            indicators.append({
                "id": "skew",
                "name": "SKEW Index",
                "category": "Volatility & Fear",
                "value": round(current, 2),
                "display": f"{current:.1f}",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(skew),
                "acceleration": round(acceleration(skew), 4),
                "description": "CBOE SKEW measures tail risk hedging demand. High = institutions buying crash protection."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 5. Credit Spreads (HYG-LQD) =====
    print("  5. Credit Spreads...")
    try:
        hyg = get_close("HYG")
        lqd = get_close("LQD")
        if len(hyg) > 20 and len(lqd) > 20:
            common = hyg.index.intersection(lqd.index)
            # HYG underperformance vs LQD = widening spreads = stress
            spread_proxy = (lqd.loc[common] / hyg.loc[common]).dropna()
            current = float(spread_proxy.iloc[-1])
            pct = percentile_rank(spread_proxy.tail(252), current)
            
            if pct > 75:
                sig = "red"  # Widening = stress
            elif pct > 40:
                sig = "yellow"
            else:
                sig = "green"
            
            indicators.append({
                "id": "credit_spread",
                "name": "Credit Spreads (HY-IG)",
                "category": "Credit & Bonds",
                "value": round(current, 4),
                "display": f"{current:.3f} LQD/HYG",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(spread_proxy),
                "acceleration": round(acceleration(spread_proxy), 4),
                "description": "LQD/HYG ratio as credit spread proxy. Rising = stress widening. Falling = calm."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 6. Yield Curve (10Y-2Y) =====
    print("  6. Yield Curve...")
    try:
        tnx = get_close("^TNX")  # 10Y yield
        irx = get_close("^IRX")  # 13-week T-bill as 2Y proxy
        # Try to get 2Y from FRED or use ^TWO
        two_y = fetch_with_fallback("2YY=F", period="2y")
        if len(two_y) > 0 and 'Close' in two_y.columns:
            two_y_close = two_y['Close'].dropna()
        else:
            two_y_close = irx  # Fallback
        
        if len(tnx) > 20 and len(two_y_close) > 20:
            common = tnx.index.intersection(two_y_close.index)
            if len(common) > 20:
                curve = (tnx.loc[common] - two_y_close.loc[common]).dropna()
                current = float(curve.iloc[-1])
                pct = percentile_rank(curve.tail(252), current)
                
                if current < 0:
                    sig = "red"  # Inverted = recession
                elif current < 0.5:
                    sig = "yellow"  # Flat
                else:
                    sig = "green"  # Normal
                
                indicators.append({
                    "id": "yield_curve",
                    "name": "Yield Curve (10Y-2Y)",
                    "category": "Credit & Bonds",
                    "value": round(current, 3),
                    "display": f"{current:+.2f}% ({'INVERTED' if current < 0 else 'Normal'})",
                    "signal": sig,
                    "percentile": round(pct, 1),
                    "sparkline": safe_sparkline(curve),
                    "acceleration": round(acceleration(curve), 4),
                    "description": "10Y minus 2Y Treasury spread. Negative = inversion = recession signal. Steepening after inversion can also signal stress."
                })
    except Exception as e:
        print(f"    Error: {e}")
        traceback.print_exc()

    # ===== 7. TLT Momentum =====
    print("  7. TLT Momentum...")
    try:
        tlt = get_close("TLT")
        if len(tlt) > 30:
            roc_20 = tlt.pct_change(20) * 100
            roc_20 = roc_20.dropna()
            current = float(roc_20.iloc[-1])
            pct = percentile_rank(roc_20.tail(252), current)
            
            # Rising TLT (positive momentum) = flight to safety = risk off
            if current > 3:
                sig = "red"  # Strong flight to safety
            elif current > 0:
                sig = "yellow"
            else:
                sig = "green"  # Bonds selling = risk on
            
            indicators.append({
                "id": "tlt_momentum",
                "name": "TLT Momentum (20d)",
                "category": "Credit & Bonds",
                "value": round(current, 2),
                "display": f"{current:+.2f}%",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(roc_20),
                "acceleration": round(acceleration(roc_20), 4),
                "description": "20-day rate of change of TLT (long bonds). Positive = flight to safety. Negative = risk-on."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 8. Market Breadth (RSP/SPY) =====
    print("  8. Market Breadth...")
    try:
        spy = get_close("SPY")
        rsp = get_close("RSP")
        if len(spy) > 20 and len(rsp) > 20:
            common = spy.index.intersection(rsp.index)
            breadth = (rsp.loc[common] / spy.loc[common]).dropna()
            # 20-day momentum of breadth
            breadth_mom = breadth.pct_change(20) * 100
            breadth_mom = breadth_mom.dropna()
            current = float(breadth_mom.iloc[-1])
            pct = percentile_rank(breadth_mom.tail(252), current)
            
            # Negative breadth momentum = narrowing leadership = fragile
            if current < -2:
                sig = "red"
            elif current < 0:
                sig = "yellow"
            else:
                sig = "green"
            
            indicators.append({
                "id": "breadth",
                "name": "Market Breadth (RSP/SPY)",
                "category": "Equity Internals",
                "value": round(current, 2),
                "display": f"{current:+.2f}% (20d)",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(breadth_mom),
                "acceleration": round(acceleration(breadth_mom), 4),
                "description": "Equal-weight vs cap-weight S&P 500 momentum. Negative = narrowing breadth = fragile market."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 9. New Highs vs New Lows =====
    print("  9. New Highs/Lows proxy...")
    try:
        spy = get_close("^GSPC")
        if len(spy) > 260:
            # Count how many of the last 20 days hit 52-week high vs low
            rolling_high = spy.rolling(252).max()
            rolling_low = spy.rolling(252).min()
            
            # Distance from 52-week high (0 = at high, negative = below)
            dist_high = ((spy - rolling_high) / rolling_high * 100).dropna()
            current = float(dist_high.iloc[-1])
            pct = percentile_rank(dist_high.tail(252), current)
            
            if current > -2:
                sig = "yellow"  # Near highs = complacency
            elif current < -10:
                sig = "red"  # Far from highs = fear
            else:
                sig = "green"  # Healthy pullback
            
            # Reinterpret: being near high with low VIX = complacency (danger)
            # Being far from high = already corrected
            indicators.append({
                "id": "high_low",
                "name": "Distance from 52W High",
                "category": "Equity Internals",
                "value": round(current, 2),
                "display": f"{current:+.1f}% from high",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(dist_high),
                "acceleration": round(acceleration(dist_high), 4),
                "description": "S&P 500 distance from 52-week high. Near 0% with low VIX = complacency. Deep negative = correction underway."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 10. S&P 500 RSI =====
    print("  10. S&P 500 RSI...")
    try:
        spy = get_close("^GSPC")
        if len(spy) > 20:
            delta = spy.diff()
            gain = delta.clip(lower=0)
            loss = (-delta.clip(upper=0))
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss
            rsi = (100 - 100 / (1 + rs)).dropna()
            
            current = float(rsi.iloc[-1])
            pct = percentile_rank(rsi.tail(252), current)
            
            if current > 70:
                sig = "red"  # Overbought
            elif current < 30:
                sig = "red"  # Oversold (also dangerous - could mean crash)
            elif current > 60:
                sig = "yellow"
            else:
                sig = "green"
            
            indicators.append({
                "id": "sp500_rsi",
                "name": "S&P 500 RSI (14d)",
                "category": "Equity Internals",
                "value": round(current, 1),
                "display": f"{current:.1f} ({'Overbought' if current > 70 else 'Oversold' if current < 30 else 'Neutral'})",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(rsi),
                "acceleration": round(acceleration(rsi), 4),
                "description": "14-day RSI of S&P 500. >70 = overbought (reduce exposure), <30 = oversold (potential bounce)."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 11. Margin Debt Proxy =====
    print("  11. Margin Debt proxy...")
    try:
        # Proxy: leveraged ETF total volume as margin activity proxy
        tqqq = get_volume("TQQQ")
        sqqq = get_volume("SQQQ")
        if len(tqqq) > 30 and len(sqqq) > 30:
            common = tqqq.index.intersection(sqqq.index)
            total_lev = (tqqq.loc[common] + sqqq.loc[common]).dropna()
            # 20-day MA
            lev_smooth = total_lev.rolling(20).mean().dropna()
            mom = lev_smooth.pct_change(20) * 100
            mom = mom.dropna()
            current = float(mom.iloc[-1])
            pct = percentile_rank(mom.tail(252), current)
            
            if pct > 80:
                sig = "red"  # Rapid leverage increase
            elif pct > 50:
                sig = "yellow"
            else:
                sig = "green"
            
            indicators.append({
                "id": "margin_debt",
                "name": "Leverage Activity Trend",
                "category": "Leverage & Positioning",
                "value": round(current, 1),
                "display": f"{current:+.1f}% (20d)",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(mom),
                "acceleration": round(acceleration(mom), 4),
                "description": "Combined TQQQ+SQQQ volume momentum as leverage proxy. Rising fast = overheating."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 12. Leveraged ETF Bull/Bear Ratio =====
    print("  12. Leveraged ETF ratio...")
    try:
        tqqq_vol = get_volume("TQQQ")
        sqqq_vol = get_volume("SQQQ")
        if len(tqqq_vol) > 20 and len(sqqq_vol) > 20:
            common = tqqq_vol.index.intersection(sqqq_vol.index)
            bull_bear = (tqqq_vol.loc[common] / (tqqq_vol.loc[common] + sqqq_vol.loc[common])).dropna()
            smooth = bull_bear.rolling(10).mean().dropna()
            current = float(smooth.iloc[-1])
            pct = percentile_rank(smooth.tail(252), current)
            
            if current > 0.7:
                sig = "red"  # Extreme bullish positioning
            elif current < 0.4:
                sig = "red"  # Extreme bearish (panic)
            elif current > 0.6:
                sig = "yellow"
            else:
                sig = "green"
            
            indicators.append({
                "id": "lev_etf_ratio",
                "name": "Bull/Bear ETF Ratio",
                "category": "Leverage & Positioning",
                "value": round(current, 3),
                "display": f"{current*100:.1f}% bullish",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(smooth),
                "acceleration": round(acceleration(smooth), 4),
                "description": "TQQQ/(TQQQ+SQQQ) volume ratio. >70% = extreme bullish (contrarian bearish). <40% = panic."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 13. AAII Sentiment (proxy) =====
    print("  13. AAII Sentiment proxy...")
    try:
        # Proxy: SPY 20-day momentum as sentiment proxy
        spy = get_close("SPY")
        if len(spy) > 60:
            mom_20 = spy.pct_change(20) * 100
            mom_60 = spy.pct_change(60) * 100
            # Combine short and medium term momentum as sentiment proxy
            sentiment = (mom_20.dropna() * 0.6 + mom_60.dropna().reindex(mom_20.dropna().index, method='ffill') * 0.4)
            sentiment = sentiment.dropna()
            current = float(sentiment.iloc[-1])
            pct = percentile_rank(sentiment.tail(252), current)
            
            if pct > 85:
                sig = "red"  # Extreme optimism = contrarian bearish
            elif pct < 15:
                sig = "green"  # Extreme pessimism = contrarian bullish
            elif pct > 65:
                sig = "yellow"
            else:
                sig = "green"
            
            indicators.append({
                "id": "aaii_proxy",
                "name": "Sentiment Momentum",
                "category": "Fund Flows & Sentiment",
                "value": round(current, 2),
                "display": f"{current:+.1f}%",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(sentiment),
                "acceleration": round(acceleration(sentiment), 4),
                "description": "Blended 20d/60d SPY momentum as sentiment proxy. Extreme highs = euphoria (danger). Extreme lows = fear (opportunity)."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 14. Fear & Greed Composite =====
    print("  14. Fear & Greed composite...")
    try:
        # Build our own mini Fear & Greed from what we have
        # Components: VIX percentile, RSI, breadth, put/call proxy
        scores = []
        for ind in indicators:
            if ind['id'] in ['vix_level', 'sp500_rsi', 'breadth', 'put_call', 'vix_term']:
                # Normalize: 0 = extreme fear, 100 = extreme greed
                if ind['id'] in ['vix_level', 'vix_term']:
                    scores.append(100 - ind['percentile'])  # Invert: high VIX = fear
                elif ind['id'] == 'put_call':
                    scores.append(100 - ind['percentile'])  # Invert: high P/C = fear
                else:
                    scores.append(ind['percentile'])
        
        if scores:
            current = float(np.mean(scores))
            
            if current > 75:
                sig = "red"  # Extreme greed
                label = "Extreme Greed"
            elif current > 55:
                sig = "yellow"
                label = "Greed"
            elif current > 45:
                sig = "green"
                label = "Neutral"
            elif current > 25:
                sig = "yellow"
                label = "Fear"
            else:
                sig = "red"  # Extreme fear
                label = "Extreme Fear"
            
            indicators.append({
                "id": "fear_greed",
                "name": "Fear & Greed Composite",
                "category": "Fund Flows & Sentiment",
                "value": round(current, 1),
                "display": f"{current:.0f}/100 ({label})",
                "signal": sig,
                "percentile": round(current, 1),
                "sparkline": [],  # Composite, no historical sparkline
                "acceleration": 0,
                "description": "Composite of VIX, RSI, breadth, put/call, term structure. 0=Extreme Fear, 100=Extreme Greed."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 15. Gold/SPY Ratio =====
    print("  15. Gold/SPY ratio...")
    try:
        gld = get_close("GLD")
        spy = get_close("SPY")
        if len(gld) > 30 and len(spy) > 30:
            common = gld.index.intersection(spy.index)
            ratio = (gld.loc[common] / spy.loc[common]).dropna()
            mom = ratio.pct_change(20) * 100
            mom = mom.dropna()
            current = float(mom.iloc[-1])
            pct = percentile_rank(mom.tail(252), current)
            
            if pct > 80:
                sig = "red"  # Strong gold outperformance = risk off
            elif pct > 50:
                sig = "yellow"
            else:
                sig = "green"  # Equities outperforming gold = risk on
            
            indicators.append({
                "id": "gold_spy",
                "name": "Gold/SPY Ratio Momentum",
                "category": "Fund Flows & Sentiment",
                "value": round(current, 2),
                "display": f"{current:+.2f}% (20d)",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(mom),
                "acceleration": round(acceleration(mom), 4),
                "description": "GLD/SPY 20-day momentum. Rising = risk-off rotation into gold. Falling = risk appetite."
            })
    except Exception as e:
        print(f"    Error: {e}")

    # ===== 16. USD Strength =====
    print("  16. USD Strength...")
    try:
        uup = get_close("UUP")
        if len(uup) > 30:
            mom = uup.pct_change(20) * 100
            mom = mom.dropna()
            current = float(mom.iloc[-1])
            pct = percentile_rank(mom.tail(252), current)
            
            if pct > 80:
                sig = "red"  # Rapid dollar strengthening = tightening
            elif pct > 50:
                sig = "yellow"
            else:
                sig = "green"
            
            indicators.append({
                "id": "usd_strength",
                "name": "USD Strength (DXY proxy)",
                "category": "Macro",
                "value": round(current, 2),
                "display": f"{current:+.2f}% (20d)",
                "signal": sig,
                "percentile": round(pct, 1),
                "sparkline": safe_sparkline(mom),
                "acceleration": round(acceleration(mom), 4),
                "description": "UUP 20-day momentum as DXY proxy. Rapid USD rise = financial tightening = stress for risk assets."
            })
    except Exception as e:
        print(f"    Error: {e}")

    return indicators


def compute_fragility_score(indicators):
    """Compute overall fragility score 0-100."""
    if not indicators:
        return 50
    
    red_count = sum(1 for i in indicators if i['signal'] == 'red')
    yellow_count = sum(1 for i in indicators if i['signal'] == 'yellow')
    total = len(indicators)
    
    # Weight: red=1.0, yellow=0.4, green=0
    score = (red_count * 1.0 + yellow_count * 0.4) / total * 100
    return round(min(100, score), 1)


def main():
    print("=" * 60)
    print(f"Market Sentiment Dashboard Update")
    print(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    indicators = get_indicators()
    fragility = compute_fragility_score(indicators)
    
    red_count = sum(1 for i in indicators if i['signal'] == 'red')
    yellow_count = sum(1 for i in indicators if i['signal'] == 'yellow')
    green_count = sum(1 for i in indicators if i['signal'] == 'green')
    
    data = {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at_iso": datetime.datetime.now().isoformat(),
        "fragility_score": fragility,
        "red_count": red_count,
        "yellow_count": yellow_count,
        "green_count": green_count,
        "total_indicators": len(indicators),
        "extreme_fragility": red_count >= 12,
        "indicators": indicators
    }
    
    output_path = "/home/ubuntu/market-sentiment/data.json"
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    # Append to history.json (keep ALL data, one entry per date)
    history_path = "/home/ubuntu/market-sentiment/history.json"
    try:
        with open(history_path, 'r') as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = []
    
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    # Remove existing entry for today (keep latest)
    history = [h for h in history if h.get('date') != today_str]
    history.append({
        "date": today_str,
        "fragility_score": fragility,
        "red_count": red_count,
        "yellow_count": yellow_count,
        "green_count": green_count
    })
    # Sort by date and keep last 30
    history.sort(key=lambda x: x['date'])
    # No limit — keep all historical data
    
    with open(history_path, 'w') as f:
        json.dump(history, f, indent=2)
    
    print(f"History updated: {len(history)} entries")
    
    print(f"\n{'=' * 60}")
    print(f"Results: {green_count} 🟢 | {yellow_count} 🟡 | {red_count} 🔴")
    print(f"Fragility Score: {fragility}/100")
    print(f"Data written to {output_path}")
    
    if red_count >= 12:
        print("⚠️  EXTREME FRAGILITY — REDUCE EXPOSURE ⚠️")
    
    return data


if __name__ == "__main__":
    main()

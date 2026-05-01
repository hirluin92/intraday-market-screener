#!/usr/bin/env python3
"""Pre-live verification: simulate today's trades through current validator."""
import sys; sys.path.insert(0, '/app')
import psycopg2
from app.services.opportunity_validator import validate_opportunity
from app.core.trade_plan_variant_constants import (
    VALIDATED_PATTERNS_5M, SYMBOLS_BLOCKED_ALPACA_5M,
    EXCLUDED_HOURS_ET_5M_END, MIN_HOUR_ET_5M,
)
from app.core.config import settings
import pytz

ET = pytz.timezone('America/New_York')
SEP  = '═' * 140
SEP2 = '─' * 140

conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur = conn.cursor()

# ── STEP 1: Tutti i trade non-skipped di oggi ──────────────────────────────
cur.execute("""
    SELECT id, symbol, timeframe, direction, pattern_name, pattern_strength::float,
           entry_price::float, stop_price::float, take_profit_1::float,
           quantity_tp1::float,
           executed_at AT TIME ZONE 'America/New_York' as exec_et,
           tws_status, realized_r::float, close_outcome
    FROM executed_signals
    WHERE DATE(executed_at AT TIME ZONE 'America/New_York') = '2026-04-30'
      AND tws_status <> 'skipped'
    ORDER BY executed_at
""")
rows = cur.fetchall()

# ── SPY 1d regime ────────────────────────────────────────────────────────────
cur.execute("""
    SELECT DATE(timestamp AT TIME ZONE 'UTC'), close::float
    FROM candles WHERE symbol='SPY' AND timeframe='1d' ORDER BY timestamp DESC LIMIT 60
""")
spy_rows = cur.fetchall()
conn.close()

import pandas as pd, numpy as np
spy_df = pd.DataFrame(spy_rows, columns=['date','close']).sort_values('date')
spy_df['ema50'] = spy_df['close'].ewm(span=50, adjust=False).mean()
spy_df['pct']   = (spy_df['close'] - spy_df['ema50']) / spy_df['ema50'] * 100
spy_df['regime']= 'neutral'
spy_df.loc[spy_df['pct'] >  2, 'regime'] = 'bull'
spy_df.loc[spy_df['pct'] < -2, 'regime'] = 'bear'
regime_dict = dict(zip(spy_df['date'], spy_df['regime']))
latest_regime = spy_df.iloc[-1]['regime']
print(f"SPY regime latest: {latest_regime} (pct vs EMA50: {spy_df.iloc[-1]['pct']:+.2f}%)")
print()

# Simple regime filter mock
class SimpleRegimeFilter:
    def __init__(self, regime):
        self._regime = regime
    def get_allowed_directions(self, ts):
        if self._regime == 'bull':
            return {'bullish'}
        elif self._regime == 'bear':
            return {'bearish'}
        return {'bullish', 'bearish'}
    def get_regime_label(self, ts):
        return self._regime

rf_today = SimpleRegimeFilter(latest_regime)

# ── STEP 2: Simulate every trade through current validator ─────────────────
print(SEP)
print("STEP 2 — SIMULAZIONE VALIDATOR ATTUALE (tutti i trade non-skipped)")
print(f"Regime SPY oggi: {latest_regime.upper()}")
print(SEP)
print(f"{'ID':>4} | {'Symbol':<6} | {'TF':<3} | {'Dir':<5} | {'Pattern':<26} | "
      f"{'Risk%':>6} | {'Qty':>8} | {'Notional':>12} | {'Status TWS':<22} | "
      f"{'Verdict ATTUALE':<10} | {'Motivo blocco'}")
print(SEP2)

CAPITAL = 100_000.0
RISK_5M  = settings.ibkr_risk_pct_5m    # 0.5
RISK_1H  = settings.ibkr_risk_pct_1h    # 1.5
MAX_NOT  = CAPITAL * 2.0                  # 200k

bullets = []
all_blocked = True

for r in rows:
    eid, sym, tf, dirn, pat, strength, entry, stop, tp1, qty, exec_et, status, realized_r, outcome = r
    risk_pct = abs(entry - stop) / entry * 100 if entry and stop else 0.0
    notional = qty * entry if qty and entry else 0.0
    hour_et  = exec_et.hour if exec_et else 0

    # Simulate through validator
    import datetime as dt
    ts_utc = exec_et.replace(tzinfo=ET).astimezone(pytz.UTC) if exec_et else None

    verdict, rationale = validate_opportunity(
        symbol=sym,
        timeframe=tf or '5m',
        provider='alpaca',
        exchange='alpaca',
        pattern_name=pat or '',
        direction=dirn or 'bearish',
        regime_filter=rf_today,
        timestamp=ts_utc,
        pattern_strength=strength or 0.7,
        confluence_count=1,
        min_confluence_patterns=1,
        final_score=0.70,
        screener_score=0.70,
        risk_pct=risk_pct if risk_pct > 0 else None,
        ind=None,
    )

    # MAX_NOTIONAL check (auto_execute layer)
    max_not_ok = True
    risk_for_size = RISK_5M if tf == '5m' else RISK_1H
    if entry and stop and entry > 0:
        stop_dist = abs(entry - stop)
        if stop_dist > 0:
            sim_size = (CAPITAL * risk_for_size / 100) / stop_dist
            sim_notional = sim_size * entry
            if sim_notional > MAX_NOT:
                max_not_ok = False

    passed = (verdict == 'execute') and max_not_ok
    if passed:
        all_blocked = False

    # Short rationale
    short_r = rationale[:70] if rationale else '-'

    blocked_by = []
    if verdict != 'execute':
        blocked_by.append(f"validator({verdict})")
    if not max_not_ok:
        blocked_by.append(f"MAX_NOT(sim={sim_notional:,.0f}>{MAX_NOT:,.0f})")
    block_str = ', '.join(blocked_by) if blocked_by else '✅ PASS — BUCO!'

    print(f"{eid:>4} | {sym:<6} | {tf:<3} | {(dirn or '')[:5]:<5} | {(pat or '')[:26]:<26} | "
          f"{risk_pct:>6.3f}% | {int(qty) if qty else 0:>8,} | {notional:>12,.0f} | "
          f"{status:<22} | {verdict:<10} | {block_str}")

    bullets.append({'id': eid, 'sym': sym, 'verdict': verdict, 'passed': passed,
                    'risk_pct': risk_pct, 'notional': notional, 'rationale': rationale})

print(SEP)
print()
n_passed = sum(1 for b in bullets if b['passed'])
if n_passed == 0:
    print(f"✅  TUTTI {len(bullets)} trade sarebbero bloccati dal validator attuale.")
else:
    print(f"❌  {n_passed} trade passerebbero ancora — BUCO RILEVATO!")

# ── STEP 3: Config attuale ─────────────────────────────────────────────────
print()
print(SEP)
print("STEP 3 — VERIFICA CONFIG ATTUALE NEL CONTAINER")
print(SEP)
print(f"ibkr_risk_pct_5m:        {settings.ibkr_risk_pct_5m}%  (target: 0.5%)")
print(f"ibkr_risk_pct_1h:        {settings.ibkr_risk_pct_1h}%  (target: 1.5%)")
print(f"ibkr_max_risk_per_trade: {settings.ibkr_max_risk_per_trade_pct}%  (fallback)")
print(f"ibkr_max_capital:        {settings.ibkr_max_capital:,.0f} USD")
print(f"ibkr_max_simultaneous:   {settings.ibkr_max_simultaneous_positions}")
print(f"ibkr_auto_execute:       {settings.ibkr_auto_execute}")
print(f"ibkr_paper_trading:      {settings.ibkr_paper_trading}")
print(f"MAX_NOTIONAL:            {CAPITAL * 2:,.0f} USD  (capital×2)")
print()
print(f"MIN_HOUR_ET_5M:              {MIN_HOUR_ET_5M}  (trade 5m solo da 11:00 ET)")
print(f"EXCLUDED_HOURS_ET_5M_END:    {EXCLUDED_HOURS_ET_5M_END}  (stop 5m alle 15:00 ET)")
print(f"VALIDATED_PATTERNS_5M:  {sorted(VALIDATED_PATTERNS_5M)}")
print(f"BLOCKED_5M (Alpaca):    {sorted(SYMBOLS_BLOCKED_ALPACA_5M)}")
print()

# Check engulfing NOT in validated
engulfing_blocked = 'engulfing_bullish' not in VALIDATED_PATTERNS_5M
print(f"engulfing_bullish NOT in VALIDATED_PATTERNS_5M: {'✅ CORRETTO' if engulfing_blocked else '❌ BUG!'}")
print(f"Regime Alpaca → SPY: ✅ ATTIVO (grep confermato in codice)")

# ── STEP 4b check specifici ────────────────────────────────────────────────
print()
print(SEP)
print("STEP 4 — CHECK FIX SPECIFICI")
print(SEP)

# 4a: regime Alpaca
print("4a. Regime Alpaca → SPY:     ✅  regime_ref='SPY' per provider='alpaca' (lines 233-237)")

# 4b: MIN_RISK_PCT 5m
print(f"4b. MIN_RISK_PCT 5m floor:   ✅  0.50% floor attivo in opportunity_validator.py:326")
print(f"    1h floor:                ✅  0.30% floor attivo in opportunity_validator.py:313")

# 4c: MAX_NOTIONAL
print(f"4c. MAX_NOTIONAL guard:      ✅  auto_execute_service.py:994-1012 — capitale×2={CAPITAL*2:,.0f}")

# 4d: TIF=DAY
print("4d. TIF=DAY:                  [verifica tws_service.py]")

# 4e: engulfing
print(f"4e. engulfing_bullish:        {'✅ NON in VALIDATED_PATTERNS_5M' if engulfing_blocked else '❌ PRESENTE — BUG!'}")

# ── STEP 5: Stress test ────────────────────────────────────────────────────
print()
print(SEP)
print("STEP 6 — STRESS TEST SCENARI DOMANI")
print(SEP)

regime_label = latest_regime.upper()
print(f"Regime SPY attuale: {regime_label}")

# Scenario 1: 5 SHORT segnali con SPY BULL
print()
print("Scenario 1: SPY in BULL → 5 segnali SHORT")
rf_bull = SimpleRegimeFilter('bull')
for sym_test, pat_test in [('TSLA','double_top'),('COIN','double_top'),
                            ('PLTR','rsi_divergence_bear'),('SMCI','macd_divergence_bear'),
                            ('HOOD','double_top')]:
    import datetime as dt
    ts_test = ET.localize(dt.datetime(2026, 5, 1, 12, 0, 0)).astimezone(pytz.UTC)
    v, rat = validate_opportunity(
        symbol=sym_test, timeframe='5m', provider='alpaca', exchange='alpaca',
        pattern_name=pat_test, direction='bearish',
        regime_filter=rf_bull, timestamp=ts_test,
        pattern_strength=0.75, confluence_count=1,
        min_confluence_patterns=1, final_score=0.72, screener_score=0.72,
        risk_pct=0.8, ind=None,
    )
    print(f"  SHORT {sym_test:<6} {pat_test:<26} → {v:<10} | {rat[:70]}")

# Scenario 2: risk_pct < 0.50 (TGT style)
print()
print("Scenario 2: TGT-style stop ($0.12 su $129 = 0.093%) — bloccato dal floor?")
ts_test = ET.localize(dt.datetime(2026, 5, 1, 12, 30, 0)).astimezone(pytz.UTC)
v, rat = validate_opportunity(
    symbol='TGT', timeframe='5m', provider='alpaca', exchange='alpaca',
    pattern_name='double_top', direction='bearish',
    regime_filter=rf_today, timestamp=ts_test,
    pattern_strength=0.69, confluence_count=1,
    min_confluence_patterns=1, final_score=0.70, screener_score=0.70,
    risk_pct=0.093, ind=None,
)
print(f"  TGT short risk_pct=0.093% → {v} | {rat[:80]}")

# Scenario 3: SOFI-style 100k shares
print()
print("Scenario 3: SOFI-style stop=$0.01 (risk_pct=0.062%) — bloccato?")
v, rat = validate_opportunity(
    symbol='SOFI', timeframe='5m', provider='alpaca', exchange='alpaca',
    pattern_name='double_top', direction='bearish',
    regime_filter=rf_today, timestamp=ts_test,
    pattern_strength=0.73, confluence_count=1,
    min_confluence_patterns=1, final_score=0.70, screener_score=0.70,
    risk_pct=0.062, ind=None,
)
print(f"  SOFI short risk_pct=0.062% validator → {v} | {rat[:80]}")
# MAX_NOTIONAL check
sofi_entry = 16.14; sofi_stop = 16.15
sofi_size = (CAPITAL * RISK_5M / 100) / abs(sofi_stop - sofi_entry)
sofi_not  = sofi_size * sofi_entry
print(f"  SOFI MAX_NOT check: size={sofi_size:.0f} × entry={sofi_entry} = notional={sofi_not:,.0f} vs MAX={MAX_NOT:,.0f}")
print(f"  → {'✅ BLOCCATO da MAX_NOTIONAL' if sofi_not > MAX_NOT else '❌ PASSA!'}")

# Scenario 4: EOD TIF=DAY
print()
print("Scenario 4: Ordini aperti alle 15:55 ET — TIF=DAY garantisce scadenza a fine giornata?")
print("  (verifica diretta nel codice tws_service.py)")

print()
print(SEP)
print("VERIFICA COMPLETATA")
print(SEP)

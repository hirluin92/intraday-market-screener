#!/usr/bin/env python3
"""
Alternative Strategies Test — 5m candle database (VECTORIZED, fast)
Strategies: VWAP Bounce, Mean Reversion VWAP, RS vs SPY (MR+MOM), ORB, Imbalance Candles, Multi-day S/R
"""
import sys; sys.path.insert(0, '/app')
import psycopg2
import pandas as pd
import numpy as np
import datetime as dt
from numpy.lib.stride_tricks import sliding_window_view

SEP  = '═' * 90
SEP2 = '─' * 90

SLIP_R      = -0.16   # total slippage in R (entry + stop slippage)
OOS_START   = dt.date(2024, 1, 1)

UNIVERSE_5M = [
    'SMCI','COIN','PLTR','HOOD','MSTR','NVDA','AMD','META','TSLA','AMZN',
    'AAPL','MSFT','GOOGL','NFLX','PYPL','SQ','SNAP','RIVN','RXRX','VKTX',
    'SMR','LUNR','DELL','WMT','SPY',
]
COLOSSI      = ['AAPL','MSFT','GOOGL','AMZN']
TOP_PERF     = ['SMCI','COIN','PLTR','HOOD']
MAX_HOLD     = 24

# ── DB ────────────────────────────────────────────────────────────────────────
print("Loading 5m candles from DB...", flush=True)
conn = psycopg2.connect(host='postgres', dbname='intraday_market_screener',
                        user='postgres', password='postgres')
cur = conn.cursor()
placeholders = ','.join(['%s'] * len(UNIVERSE_5M))
cur.execute(f"""
    SELECT symbol,
           timestamp AT TIME ZONE 'America/New_York' AS ts_et,
           open::float, high::float, low::float, close::float, volume::float
    FROM candles
    WHERE timeframe='5m'
      AND symbol IN ({placeholders})
      AND timestamp >= '2023-01-01'
    ORDER BY symbol, timestamp
""", UNIVERSE_5M)
rows = cur.fetchall()
conn.close()
print(f"  Loaded {len(rows):,} rows", flush=True)

df = pd.DataFrame(rows, columns=['symbol','ts_et','open','high','low','close','volume'])
df['ts_et']  = pd.to_datetime(df['ts_et'])
df['date']   = df['ts_et'].dt.date
df['hour']   = df['ts_et'].dt.hour
df['minute'] = df['ts_et'].dt.minute
df['time_s'] = df['ts_et'].dt.time

# Market hours 9:30 – 16:00
mkt_open  = dt.time(9, 30)
mkt_close = dt.time(16, 0)
df = df[(df['time_s'] >= mkt_open) & (df['time_s'] < mkt_close)].copy()
df['oos'] = df['date'] >= OOS_START
df.reset_index(drop=True, inplace=True)
print(f"  After market filter: {len(df):,} rows | "
      f"date range: {df['date'].min()} → {df['date'].max()}", flush=True)

# ── Core vectorized simulator ─────────────────────────────────────────────────

def sim_batch(fwd_H, fwd_L, entry, stop, tp, direction):
    """
    Fully vectorized trade outcome for n signals.

    fwd_H  : (n, MAX_HOLD) forward highs (nan = past EOD)
    fwd_L  : (n, MAX_HOLD) forward lows
    entry, stop, tp, direction : (n,) numpy arrays (+1 long / -1 short)

    Returns (n,) result_r in R units.
    """
    n = len(entry)
    if n == 0:
        return np.empty(0)

    risk = np.abs(entry - stop)
    safe_risk = np.where(risk > 0, risk, np.nan)

    result = np.zeros(n)

    for sign, mask in [(1, direction == 1), (-1, direction == -1)]:
        if not mask.any():
            continue
        fH  = fwd_H[mask]
        fL  = fwd_L[mask]
        st  = stop[mask][:, None]
        tp_ = tp[mask][:, None]
        en  = entry[mask]
        sk  = safe_risk[mask]

        valid_H = ~np.isnan(fH)
        valid_L = ~np.isnan(fL)

        if sign == 1:
            sh = (fL <= st) & valid_L
            th = (fH >= tp_) & valid_H
        else:
            sh = (fH >= st) & valid_H
            th = (fL <= tp_) & valid_L

        any_s = sh.any(axis=1)
        any_t = th.any(axis=1)
        first_s = np.where(any_s, np.argmax(sh, axis=1), MAX_HOLD)
        first_t = np.where(any_t, np.argmax(th, axis=1), MAX_HOLD)

        r = np.zeros(mask.sum())
        stopped = first_s < first_t
        won     = first_t < first_s
        r[stopped] = -1.0
        r[won]     = np.abs(tp[mask][won] - en[won]) / sk[won]

        result[mask] = r

    return result


def build_fwd_windows(H_arr, L_arr, max_hold=MAX_HOLD):
    """Build (n, max_hold) forward window matrices for a single day's arrays."""
    n = len(H_arr)
    H_pad = np.concatenate([H_arr, np.full(max_hold, np.nan)])
    L_pad = np.concatenate([L_arr, np.full(max_hold, np.nan)])
    # sliding_window_view[i] = H_pad[i:i+max_hold]
    # We want forward from i+1 → sliding_window_view[i+1]
    # view has shape (n+max_hold - max_hold + 1) = (n+1, max_hold) if padded to n+max_hold
    # Actually pad to n + max_hold gives view of shape (n+1, max_hold)
    sv_H = sliding_window_view(H_pad, max_hold)  # (n+1, max_hold)
    sv_L = sliding_window_view(L_pad, max_hold)  # (n+1, max_hold)
    # forward_H[i] = H[i+1:i+1+max_hold] = sv_H[i+1]
    fwd_H = sv_H[1:]  # (n, max_hold) — drop first row so fwd_H[i] = H[i+1:]
    fwd_L = sv_L[1:]
    return fwd_H, fwd_L


def collect_trades(sym, date, signal_idx, result_r, hours):
    """Build list of trade dicts for given results."""
    trades = []
    for k, (i, r) in enumerate(zip(signal_idx, result_r)):
        trades.append({
            'symbol': sym, 'date': date, 'hour': hours[i],
            'r': float(r), 'oos': date >= OOS_START,
        })
    return trades


def summarize(r_list):
    if not r_list:
        return {'n': 0, 'avg_r': 0.0, 'wr': 0.0, 'avg_r_slip': 0.0}
    arr = np.asarray(r_list, dtype=float)
    return {
        'n': len(arr),
        'avg_r': float(arr.mean()),
        'wr': float((arr > 0).mean() * 100),
        'avg_r_slip': float((arr + SLIP_R).mean()),
    }


def fmt_row(label, s):
    if s['n'] == 0:
        return f"  {label:<8} n=   0  avg_r=  ----  avg+slip=  ----  WR=  ----"
    return (f"  {label:<8} n={s['n']:5d}  avg_r={s['avg_r']:+.3f}R  "
            f"avg+slip={s['avg_r_slip']:+.3f}R  WR={s['wr']:5.1f}%")


def print_results(sdf, label_col=None):
    oos = sdf[sdf['oos']] if len(sdf) else sdf
    s = summarize(sdf['r'].tolist())
    s_oos = summarize(oos['r'].tolist())
    print(f"\n  OVERALL (all): {fmt_row('', s)}")
    print(f"  OOS   (2024+): {fmt_row('', s_oos)}")
    print(f"\n  By Symbol (OOS):")
    for sym in sorted(df['symbol'].unique()):
        sub = oos[oos['symbol'] == sym]
        print(fmt_row(sym, summarize(sub['r'].tolist())))
    print(f"\n  By Hour (OOS):")
    for hr in [9, 10, 11, 12, 13, 14, 15]:
        sub = oos[oos['hour'] == hr]
        s_hr = summarize(sub['r'].tolist())
        print(f"  Hour {hr}h: n={s_hr['n']:5d}  avg_r={s_hr['avg_r']:+.3f}R  "
              f"avg+slip={s_hr['avg_r_slip']:+.3f}R  WR={s_hr['wr']:5.1f}%")
    print(f"\n  Colossi vs Top Performers (OOS):")
    for grp_name, syms in [("COLOSSI", COLOSSI), ("TOP PERF", TOP_PERF)]:
        sub = oos[oos['symbol'].isin(syms)]
        print(f"  {grp_name}: {fmt_row('', summarize(sub['r'].tolist()))}")


# ── STRATEGY 1 — VWAP BOUNCE ──────────────────────────────────────────────────
print(f"\n{SEP}")
print("STRATEGY 1 — VWAP BOUNCE")
print("  Signal: price crosses VWAP (above→below = SHORT, below→above = LONG)")
print("  Filter: cross must be > 0.10% from VWAP (avoid noise)  TP=1.5R  Stop=signal candle extreme")
print(SEP)

s1_trades = []
for sym, sym_df in df.groupby('symbol'):
    n_sym = 0
    for date, day in sym_df.groupby('date'):
        day = day.sort_values('ts_et').reset_index(drop=True)
        if len(day) < 8:
            continue
        H = day['high'].values.astype(float)
        L = day['low'].values.astype(float)
        C = day['close'].values.astype(float)
        O = day['open'].values.astype(float)
        V = day['volume'].values.astype(float)
        hrs = day['hour'].values

        # VWAP
        tp_p = (H + L + C) / 3
        cum_tpv = np.cumsum(tp_p * V)
        cum_vol = np.cumsum(V)
        cum_vol = np.where(cum_vol == 0, np.nan, cum_vol)
        vwap = cum_tpv / cum_vol

        fwd_H, fwd_L = build_fwd_windows(H, L)

        # Signals: bar i where close[i-1] < vwap[i-1] and close[i] > vwap[i] → LONG
        # Filter: distance > 0.10% (avoid micro-crosses)
        prev_below = (C[:-1] < vwap[:-1]) & ((vwap[1:] - C[:-1]) / vwap[1:] > 0.001)
        prev_above = (C[:-1] > vwap[:-1]) & ((C[:-1] - vwap[1:]) / vwap[1:] > 0.001)
        cross_up   = prev_below & (C[1:] > vwap[1:])
        cross_dn   = prev_above & (C[1:] < vwap[1:])

        sig_up = np.where(cross_up)[0] + 1   # bar index (adjusted +1 for slicing)
        sig_dn = np.where(cross_dn)[0] + 1

        if len(sig_up) == 0 and len(sig_dn) == 0:
            continue

        all_idx  = np.concatenate([sig_up, sig_dn])
        all_dir  = np.concatenate([np.ones(len(sig_up)), -np.ones(len(sig_dn))])
        entry    = C[all_idx]
        stop_l   = L[all_idx] - 0.01     # long: below bar low
        stop_s   = H[all_idx] + 0.01     # short: above bar high
        stop     = np.where(all_dir == 1, stop_l, stop_s)
        risk     = np.abs(entry - stop)
        valid    = (risk > 0) & (risk / entry > 0.001)
        all_idx  = all_idx[valid]
        all_dir  = all_dir[valid]
        entry    = entry[valid]
        stop     = stop[valid]
        risk     = risk[valid]
        tp       = entry + all_dir * 1.5 * risk

        if len(all_idx) == 0:
            continue

        result_r = sim_batch(fwd_H[all_idx], fwd_L[all_idx], entry, stop, tp, all_dir)

        for k, (i, r) in enumerate(zip(all_idx, result_r)):
            s1_trades.append({'symbol': sym, 'date': date, 'hour': int(hrs[i]),
                              'r': float(r), 'oos': date >= OOS_START})
        n_sym += len(all_idx)
    print(f"  {sym}: {n_sym} trades", flush=True)

s1_df = pd.DataFrame(s1_trades) if s1_trades else pd.DataFrame(columns=['symbol','date','hour','r','oos'])
print_results(s1_df)


# ── STRATEGY 2 — MEAN REVERSION FROM VWAP ────────────────────────────────────
print(f"\n{SEP}")
print("STRATEGY 2 — MEAN REVERSION FROM VWAP")
print("  Signal: close > VWAP + 1.5×std → SHORT; close < VWAP - 1.5×std → LONG")
print("  Target: VWAP; Stop: 0.5% from entry; Max hold=24 bars")
print(SEP)

s2_trades = []
for sym, sym_df in df.groupby('symbol'):
    n_sym = 0
    for date, day in sym_df.groupby('date'):
        day = day.sort_values('ts_et').reset_index(drop=True)
        if len(day) < 15:
            continue
        H = day['high'].values.astype(float)
        L = day['low'].values.astype(float)
        C = day['close'].values.astype(float)
        V = day['volume'].values.astype(float)
        hrs = day['hour'].values

        # VWAP + rolling std of deviation (window=20)
        tp_p  = (H + L + C) / 3
        cum_tv= np.cumsum(tp_p * V)
        cum_v = np.cumsum(V)
        cum_v = np.where(cum_v == 0, np.nan, cum_v)
        vwap  = cum_tv / cum_v
        dev   = C - vwap
        n     = len(day)
        vwap_std = pd.Series(dev).rolling(20, min_periods=5).std().values

        fwd_H, fwd_L = build_fwd_windows(H, L)

        entry_arr, stop_arr, tp_arr, dir_arr, idx_arr = [], [], [], [], []
        for i in range(10, n - 1):
            v    = vwap[i]
            std  = vwap_std[i]
            c    = C[i]
            if np.isnan(v) or np.isnan(std) or std < 1e-8:
                continue
            upper = v + 1.5 * std
            lower = v - 1.5 * std
            if c > upper:
                direction = -1
                entry = c
                stop  = c * 1.005
                target= v
                if target >= entry:
                    continue
            elif c < lower:
                direction = 1
                entry = c
                stop  = c * 0.995
                target= v
                if target <= entry:
                    continue
            else:
                continue
            risk = abs(entry - stop)
            if risk <= 0:
                continue
            entry_arr.append(entry); stop_arr.append(stop)
            tp_arr.append(target);   dir_arr.append(direction)
            idx_arr.append(i)

        if not idx_arr:
            continue
        idx_arr  = np.array(idx_arr)
        entry_np = np.array(entry_arr, dtype=float)
        stop_np  = np.array(stop_arr,  dtype=float)
        tp_np    = np.array(tp_arr,    dtype=float)
        dir_np   = np.array(dir_arr,   dtype=float)

        result_r = sim_batch(fwd_H[idx_arr], fwd_L[idx_arr], entry_np, stop_np, tp_np, dir_np)

        for k, (i, r) in enumerate(zip(idx_arr, result_r)):
            s2_trades.append({'symbol': sym, 'date': date, 'hour': int(hrs[i]),
                              'r': float(r), 'oos': date >= OOS_START})
        n_sym += len(idx_arr)
    print(f"  {sym}: {n_sym} trades", flush=True)

s2_df = pd.DataFrame(s2_trades) if s2_trades else pd.DataFrame(columns=['symbol','date','hour','r','oos'])
print_results(s2_df)


# ── STRATEGY 3 — RELATIVE STRENGTH vs SPY ─────────────────────────────────────
print(f"\n{SEP}")
print("STRATEGY 3 — RELATIVE STRENGTH vs SPY")
print("  RS = symbol_return_from_930 – SPY_return_from_930")
print("  MR : RS > +2% → SHORT  /  RS < -2% → LONG   (mean reversion)")
print("  MOM: RS > +2% → LONG   /  RS < -2% → SHORT  (momentum)")
print("  TP=1.5R  Stop=candle range + 0.2%  Max hold=12 bars")
print(SEP)

spy_5m = df[df['symbol'] == 'SPY'].copy()
spy_by_date = {}
for date, g in spy_5m.groupby('date'):
    g = g.sort_values('ts_et').reset_index(drop=True)
    spy_by_date[date] = g

def compute_rs_strategy(mode='mr'):
    trades = []
    for sym, sym_df in df.groupby('symbol'):
        if sym == 'SPY':
            continue
        n_sym = 0
        for date, day in sym_df.groupby('date'):
            day = day.sort_values('ts_et').reset_index(drop=True)
            spy_day = spy_by_date.get(date)
            if spy_day is None or len(day) < 3 or len(spy_day) < 3:
                continue

            open_sym = float(day.loc[0, 'open'])
            open_spy = float(spy_day.loc[0, 'open'])
            if open_sym == 0 or open_spy == 0:
                continue

            C_sym = day['close'].values.astype(float)
            H_sym = day['high'].values.astype(float)
            L_sym = day['low'].values.astype(float)
            ts_sym = day['ts_et'].values
            hrs_sym = day['hour'].values
            n = len(day)

            # Align SPY close to each symbol bar (latest spy ts <= sym ts)
            spy_ts = spy_day['ts_et'].values
            spy_C  = spy_day['close'].values.astype(float)
            # For each sym bar, find last spy bar <= ts_sym
            spy_idx = np.searchsorted(spy_ts, ts_sym, side='right') - 1
            spy_idx = np.clip(spy_idx, 0, len(spy_C) - 1)
            spy_close_aligned = spy_C[spy_idx]

            ret_sym = (C_sym - open_sym) / open_sym * 100
            ret_spy = (spy_close_aligned - open_spy) / open_spy * 100
            rs      = ret_sym - ret_spy

            THRESHOLD = 2.0
            if mode == 'mr':
                long_sig  = rs < -THRESHOLD
                short_sig = rs >  THRESHOLD
            else:
                long_sig  = rs >  THRESHOLD
                short_sig = rs < -THRESHOLD

            fwd_H, fwd_L = build_fwd_windows(H_sym, L_sym, MAX_HOLD // 2)

            entry_arr, stop_arr, tp_arr, dir_arr, idx_arr = [], [], [], [], []
            for i in range(2, n - 1):
                if long_sig[i]:
                    direction = 1
                elif short_sig[i]:
                    direction = -1
                else:
                    continue
                entry = C_sym[i]
                if direction == 1:
                    stop = L_sym[i] * 0.998
                else:
                    stop = H_sym[i] * 1.002
                risk = abs(entry - stop)
                if risk <= 0 or risk / entry < 0.0005:
                    continue
                tp = entry + direction * 1.5 * risk
                entry_arr.append(entry); stop_arr.append(stop)
                tp_arr.append(tp);       dir_arr.append(float(direction))
                idx_arr.append(i)

            if not idx_arr:
                continue
            idx_arr  = np.array(idx_arr)
            entry_np = np.array(entry_arr, dtype=float)
            stop_np  = np.array(stop_arr,  dtype=float)
            tp_np    = np.array(tp_arr,    dtype=float)
            dir_np   = np.array(dir_arr,   dtype=float)

            max_h = MAX_HOLD // 2
            result_r = sim_batch(fwd_H[idx_arr], fwd_L[idx_arr],
                                 entry_np, stop_np, tp_np, dir_np)

            for k, (i, r) in enumerate(zip(idx_arr, result_r)):
                trades.append({'symbol': sym, 'date': date, 'hour': int(hrs_sym[i]),
                               'r': float(r), 'oos': date >= OOS_START})
            n_sym += len(idx_arr)
        print(f"  [{mode.upper()}] {sym}: {n_sym}", flush=True)
    return trades

print("  Computing MR mode...", flush=True)
s3_mr_trades  = compute_rs_strategy('mr')
print("  Computing MOM mode...", flush=True)
s3_mom_trades = compute_rs_strategy('mom')

s3_mr_df  = pd.DataFrame(s3_mr_trades)  if s3_mr_trades  else pd.DataFrame(columns=['symbol','date','hour','r','oos'])
s3_mom_df = pd.DataFrame(s3_mom_trades) if s3_mom_trades else pd.DataFrame(columns=['symbol','date','hour','r','oos'])

for mode_lbl, sdf in [("MR  (mean-reversion)", s3_mr_df), ("MOM (momentum)      ", s3_mom_df)]:
    print(f"\n  ── RS {mode_lbl} ──")
    print_results(sdf)


# ── STRATEGY 4 — OPENING RANGE BREAKOUT (ORB) ────────────────────────────────
print(f"\n{SEP}")
print("STRATEGY 4 — OPENING RANGE BREAKOUT (ORB)")
print("  ORB = first 6×5m bars (9:30-9:55 ET)")
print("  Break above ORB_high → LONG; below ORB_low → SHORT  (one trade per direction per day)")
print("  TP=2×ORB_range  Stop=opposite extreme  Max hold=EOD")
print(SEP)

s4_trades = []
for sym, sym_df in df.groupby('symbol'):
    n_sym = 0
    for date, day in sym_df.groupby('date'):
        day = day.sort_values('ts_et').reset_index(drop=True)

        orb_bars  = day[day['ts_et'].dt.time < dt.time(10, 0)]
        post_orb  = day[day['ts_et'].dt.time >= dt.time(10, 0)].reset_index(drop=True)
        if len(orb_bars) < 3 or len(post_orb) < 2:
            continue

        orb_H = orb_bars['high'].max()
        orb_L = orb_bars['low'].min()
        orb_range = orb_H - orb_L
        if orb_range <= 0 or orb_range / orb_H < 0.001:
            continue

        H_p = post_orb['high'].values.astype(float)
        L_p = post_orb['low'].values.astype(float)
        C_p = post_orb['close'].values.astype(float)
        hrs = post_orb['hour'].values
        n_p = len(post_orb)

        fwd_H, fwd_L = build_fwd_windows(H_p, L_p, n_p)

        for direction, break_side, entry_cond, stop_px, tp_px in [
            (1,  'long',  C_p > orb_H, orb_L, None),
            (-1, 'short', C_p < orb_L, orb_H, None),
        ]:
            sig_bars = np.where(entry_cond)[0]
            if len(sig_bars) == 0:
                continue
            i = sig_bars[0]  # first breakout bar
            entry = C_p[i]
            if direction == 1:
                stop_  = orb_L
                tp_    = entry + 2 * orb_range
            else:
                stop_  = orb_H
                tp_    = entry - 2 * orb_range
            risk = abs(entry - stop_)
            if risk <= 0:
                continue

            # remaining bars from i+1
            rem = n_p - i - 1
            if rem <= 0:
                continue
            max_h = min(rem, n_p)
            fH_sl = fwd_H[i, :max_h].reshape(1, -1)
            fL_sl = fwd_L[i, :max_h].reshape(1, -1)

            result_r = sim_batch(fH_sl, fL_sl,
                                 np.array([entry]), np.array([stop_]),
                                 np.array([tp_]),    np.array([float(direction)]))
            r = float(result_r[0])
            s4_trades.append({'symbol': sym, 'date': date, 'hour': int(hrs[i]),
                              'r': r, 'oos': date >= OOS_START})
            n_sym += 1
    print(f"  {sym}: {n_sym} trades", flush=True)

s4_df = pd.DataFrame(s4_trades) if s4_trades else pd.DataFrame(columns=['symbol','date','hour','r','oos'])
print_results(s4_df)


# ── STRATEGY 5 — IMBALANCE CANDLES ────────────────────────────────────────────
print(f"\n{SEP}")
print("STRATEGY 5 — IMBALANCE CANDLES")
print("  imbalance_score = body_ratio × direction × volume_relative  (threshold > 2.0)")
print("  Entry next candle close  TP=2.0R  Stop=signal candle extreme  Max hold=12 bars")
print(SEP)

s5_trades = []
for sym, sym_df in df.groupby('symbol'):
    n_sym = 0
    for date, day in sym_df.groupby('date'):
        day = day.sort_values('ts_et').reset_index(drop=True)
        if len(day) < 15:
            continue
        H = day['high'].values.astype(float)
        L = day['low'].values.astype(float)
        C = day['close'].values.astype(float)
        O = day['open'].values.astype(float)
        V = day['volume'].values.astype(float)
        hrs = day['hour'].values
        n = len(day)

        body     = np.abs(C - O)
        candle_r = H - L
        body_ratio = np.where(candle_r > 0, body / candle_r, 0.0)
        direction  = np.where(C >= O, 1.0, -1.0)
        vol_ma     = pd.Series(V).rolling(20, min_periods=5).mean().values
        vol_rel    = np.where(vol_ma > 0, V / vol_ma, 0.0)
        imbalance  = body_ratio * direction * vol_rel

        # Signal at bar i: |imbalance| > 2.0; enter at bar i+1 close
        # stop = signal candle extreme, tp = 2R
        sig = np.abs(imbalance[:-2]) > 2.0   # bar i (need room for entry at i+1 and fwd)
        sig_i = np.where(sig)[0]

        if len(sig_i) == 0:
            continue

        entry_i   = sig_i + 1           # entry at close of i+1
        valid_e   = entry_i < n - 1
        sig_i     = sig_i[valid_e]
        entry_i   = entry_i[valid_e]

        imb_dir   = np.where(imbalance[sig_i] > 0, 1.0, -1.0)
        entry_px  = C[entry_i]
        stop_long = L[sig_i] - 0.01
        stop_sht  = H[sig_i] + 0.01
        stop_px   = np.where(imb_dir == 1, stop_long, stop_sht)
        risk      = np.abs(entry_px - stop_px)
        valid_r   = (risk > 0) & (risk / entry_px > 0.001)
        sig_i     = sig_i[valid_r]
        entry_i   = entry_i[valid_r]
        imb_dir   = imb_dir[valid_r]
        entry_px  = entry_px[valid_r]
        stop_px   = stop_px[valid_r]
        risk      = risk[valid_r]
        tp_px     = entry_px + imb_dir * 2.0 * risk

        if len(sig_i) == 0:
            continue

        fwd_H, fwd_L = build_fwd_windows(H, L, 12)

        # entry at bar entry_i, so forward windows from entry_i
        # build_fwd_windows already gives fwd_H[i] = H[i+1:i+13]
        result_r = sim_batch(fwd_H[entry_i], fwd_L[entry_i],
                             entry_px, stop_px, tp_px, imb_dir)

        for k, (ei, r) in enumerate(zip(entry_i, result_r)):
            s5_trades.append({'symbol': sym, 'date': date, 'hour': int(hrs[ei]),
                              'r': float(r), 'oos': date >= OOS_START})
        n_sym += len(entry_i)
    print(f"  {sym}: {n_sym} trades", flush=True)

s5_df = pd.DataFrame(s5_trades) if s5_trades else pd.DataFrame(columns=['symbol','date','hour','r','oos'])
print_results(s5_df)

# Sub-filter: higher imbalance threshold
if 'imbalance' in s5_df.columns:
    pass  # no imbalance col in s5_df (not stored)
print("\n  (Imbalance threshold > 3.0 would require re-run with different threshold)")


# ── STRATEGY 6 — MULTI-DAY SUPPORT/RESISTANCE ─────────────────────────────────
print(f"\n{SEP}")
print("STRATEGY 6 — MULTI-DAY SUPPORT/RESISTANCE")
print("  Pivot levels = clustered daily H/L from last 5 trading days (cluster tol=0.5%)")
print("  Signal: price touches level (within 0.3%) AND candle rejects (body away from level)")
print("  TP=1.5R  Stop=0.5% past level  Max hold=12 bars")
print(SEP)

# Pre-build daily pivots per symbol
daily_pivots = {}
for sym, sym_df in df.groupby('symbol'):
    daily_pivots[sym] = {}
    for date, day in sym_df.groupby('date'):
        daily_pivots[sym][date] = {'H': float(day['high'].max()), 'L': float(day['low'].min())}

s6_trades = []
for sym, sym_df in df.groupby('symbol'):
    dates = sorted(daily_pivots[sym].keys())
    n_sym = 0
    for date_idx, date in enumerate(dates):
        if date_idx < 5:
            continue
        look_back = dates[date_idx - 5: date_idx]
        levels = []
        for d in look_back:
            p = daily_pivots[sym].get(d)
            if p:
                levels += [p['H'], p['L']]
        if not levels:
            continue
        levels = sorted(levels)
        clusters = []
        cluster  = [levels[0]]
        for lv in levels[1:]:
            if (lv - cluster[-1]) / max(cluster[-1], 1e-8) < 0.005:
                cluster.append(lv)
            else:
                clusters.append(float(np.mean(cluster)))
                cluster = [lv]
        clusters.append(float(np.mean(cluster)))

        day = sym_df[sym_df['date'] == date].sort_values('ts_et').reset_index(drop=True)
        if len(day) < 5:
            continue

        H = day['high'].values.astype(float)
        L = day['low'].values.astype(float)
        C = day['close'].values.astype(float)
        O = day['open'].values.astype(float)
        hrs = day['hour'].values
        n   = len(day)
        body = C - O

        fwd_H, fwd_L = build_fwd_windows(H, L, 12)

        entry_arr, stop_arr, tp_arr, dir_arr, idx_arr = [], [], [], [], []
        used = set()
        for i in range(2, n - 1):
            if i in used:
                continue
            c    = C[i]
            b    = body[i]
            h    = H[i]
            l    = L[i]
            for level in clusters:
                dist = abs(c - level) / max(level, 1e-8)
                if dist > 0.003:
                    continue
                # Bullish rejection (candle dipped below level and closed above with bullish body)
                if l < level and c > level and b > 0:
                    direction = 1
                    entry  = c
                    stop_  = l - 0.01
                    risk   = entry - stop_
                    if risk <= 0 or risk / entry < 0.001:
                        continue
                    tp_    = entry + 1.5 * risk
                    entry_arr.append(entry); stop_arr.append(stop_)
                    tp_arr.append(tp_);      dir_arr.append(1.0)
                    idx_arr.append(i);       used.add(i)
                    break
                # Bearish rejection
                elif h > level and c < level and b < 0:
                    direction = -1
                    entry  = c
                    stop_  = h + 0.01
                    risk   = stop_ - entry
                    if risk <= 0 or risk / entry < 0.001:
                        continue
                    tp_    = entry - 1.5 * risk
                    entry_arr.append(entry); stop_arr.append(stop_)
                    tp_arr.append(tp_);      dir_arr.append(-1.0)
                    idx_arr.append(i);       used.add(i)
                    break

        if not idx_arr:
            continue
        idx_arr  = np.array(idx_arr)
        entry_np = np.array(entry_arr, dtype=float)
        stop_np  = np.array(stop_arr,  dtype=float)
        tp_np    = np.array(tp_arr,    dtype=float)
        dir_np   = np.array(dir_arr,   dtype=float)

        result_r = sim_batch(fwd_H[idx_arr], fwd_L[idx_arr],
                             entry_np, stop_np, tp_np, dir_np)

        for k, (i, r) in enumerate(zip(idx_arr, result_r)):
            s6_trades.append({'symbol': sym, 'date': date, 'hour': int(hrs[i]),
                              'r': float(r), 'oos': date >= OOS_START})
        n_sym += len(idx_arr)
    print(f"  {sym}: {n_sym} trades", flush=True)

s6_df = pd.DataFrame(s6_trades) if s6_trades else pd.DataFrame(columns=['symbol','date','hour','r','oos'])
print_results(s6_df)


# ── FINAL COMPARISON ──────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("CONFRONTO FINALE — TUTTE LE STRATEGIE (OOS 2024+)")
print(SEP)
print(f"  {'Strategy':<42} {'n':>6}  {'avg_r':>8}  {'avg+slip':>10}  {'WR':>7}")
print(f"  {'-'*42} {'-'*6}  {'-'*8}  {'-'*10}  {'-'*7}")

strategies = [
    ("S1  VWAP Bounce        (TP=1.5R)",     s1_df),
    ("S2  VWAP Mean Reversion(TP=VWAP)",     s2_df),
    ("S3a RS vs SPY — MR     (TP=1.5R)",     s3_mr_df),
    ("S3b RS vs SPY — MOM    (TP=1.5R)",     s3_mom_df),
    ("S4  ORB                (TP=2×range)",  s4_df),
    ("S5  Imbalance Candles  (TP=2.0R)",     s5_df),
    ("S6  Multi-day S/R      (TP=1.5R)",     s6_df),
]

best_slip = -999
best_name = ""
for name, sdf in strategies:
    if len(sdf) == 0:
        print(f"  {name:<42} {'0':>6}  {'----':>8}  {'----':>10}  {'----':>7}")
        continue
    oos_r = sdf[sdf['oos']]['r'].tolist()
    s = summarize(oos_r)
    flag = ""
    if s['avg_r_slip'] > best_slip and s['n'] >= 30:
        best_slip = s['avg_r_slip']
        best_name = name.strip()
        flag = " ←"
    print(f"  {name:<42} {s['n']:>6}  {s['avg_r']:>+8.3f}R  {s['avg_r_slip']:>+10.3f}R  {s['wr']:>6.1f}%{flag}")

print(f"\n  [REF] TRIPLO pattern strategy         ~500      +0.52R      +0.36R   54.0%  ← prior analysis baseline")
print(f"\n  Best alternative (OOS, n≥30): {best_name}  avg+slip={best_slip:+.3f}R")


# Per-symbol colossi breakdown
print(f"\n{SEP2}")
print("  COLOSSI — per-strategy avg+slip (OOS, n<5 shown as n=x):")
hdr = f"  {'Symbol':<8}" + "".join(f" {s[:10]:>12}" for s, _ in strategies)
print(hdr)
for sym in COLOSSI:
    def gs(sdf):
        sub = sdf[sdf['oos'] & (sdf['symbol'] == sym)] if len(sdf) else pd.DataFrame()
        s_ = summarize(sub['r'].tolist())
        return f"{s_['avg_r_slip']:+.3f}R" if s_['n'] >= 5 else f"n={s_['n']}"
    row = f"  {sym:<8}" + "".join(f" {gs(sdf):>12}" for _, sdf in strategies)
    print(row)

print(f"\n{SEP2}")
print("  TOP PERFORMERS — per-strategy avg+slip (OOS, n<5 shown as n=x):")
print(hdr)
for sym in TOP_PERF:
    def gs(sdf):
        sub = sdf[sdf['oos'] & (sdf['symbol'] == sym)] if len(sdf) else pd.DataFrame()
        s_ = summarize(sub['r'].tolist())
        return f"{s_['avg_r_slip']:+.3f}R" if s_['n'] >= 5 else f"n={s_['n']}"
    row = f"  {sym:<8}" + "".join(f" {gs(sdf):>12}" for _, sdf in strategies)
    print(row)

print(f"\n{SEP}")
print("ANALISI COMPLETATA")
print(SEP)

#!/usr/bin/env python3
"""
oos_test_2026.py — Test Out-of-Sample 2026
===========================================
Confronto IS (2023-2025) vs OOS (2026) con TUTTI i filtri di produzione attuali.
Dati 1h: val_1h_full.csv (fino a ott 2025) + val_1h_large_post_fix.csv (fino a feb 2026)
Dati 5m: val_5m_real.csv (fino ad apr 2026)

Uso: python oos_test_2026.py
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

try:
    from zoneinfo import ZoneInfo as _ZI
    _TZ_ET = _ZI("America/New_York")
except Exception:
    _TZ_ET = None

# ── Costanti produzione (da mc_finale_ep.py / trade_plan_variant_constants) ──
_PAT_1H = frozenset({
    "double_bottom", "double_top",
    "macd_divergence_bull", "macd_divergence_bear",
    "rsi_divergence_bull", "rsi_divergence_bear",
    "engulfing_bullish",
})
_PAT_5M = frozenset({
    "double_top", "double_bottom",
    "macd_divergence_bull", "macd_divergence_bear",
})
_BLOK_5M = frozenset({"SPY", "AAPL", "MSFT", "GOOGL", "WMT"})

VALIDATED_SYMBOLS = frozenset({
    "ACHR","AMD","APLD","ASTS","CAT","CELH","COIN","CVX","DELL","GOOGL",
    "GS","HON","HOOD","HPE","ICE","JOBY","LLY","LUNR","MDB","META",
    "MP","MRNA","MSTR","MU","NEM","NET","NFLX","NKE","NNE","NVDA",
    "NVO","OKLO","PLTR","RBLX","RKLB","RXRX","SCHW","SHOP","SMCI","SMR",
    "SOFI","TGT","TSLA","VRTX","WMT","WULF","ZS",
})

MAX_RISK_LONG  = 3.0
MAX_RISK_SHORT = 2.0
MAX_STR = 0.80
MIN_STR = 0.60
BTE_1H  = 4
BTE_5M  = 3
EOD_BAR = 7
EOD_SLIP = 0.05
SLIP    = 0.15
SEP     = "=" * 90

# ── Utility ──────────────────────────────────────────────────────────────────

def _et_hour(ts_str: str) -> int:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        det = dt.astimezone(_TZ_ET) if _TZ_ET else (dt - timedelta(hours=4))
        return det.hour
    except Exception:
        return 12

def _parse_ts(ts_str: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None

def _year(ts_str: str) -> int | None:
    dt = _parse_ts(ts_str)
    return dt.year if dt else None

def _load_csv(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                if "pnl_r" not in r or r["pnl_r"] in ("", "None", None):
                    continue
                r["pnl_r"]            = float(r["pnl_r"])
                r["risk_pct"]         = float(r.get("risk_pct") or 0)
                r["pattern_strength"] = float(r.get("pattern_strength") or 0)
                r["entry_filled"]     = str(r.get("entry_filled","False")).strip() == "True"
                bte = r.get("bars_to_entry")
                r["bars_to_entry"]    = int(float(bte)) if bte not in ("", "None", None) else None
                bx  = r.get("bars_to_exit")
                r["bars_to_exit"]     = int(float(bx)) if bx not in ("", "None", None) else None
            except (ValueError, KeyError):
                continue
            rows.append(r)
    return rows


# ── Filtri produzione ─────────────────────────────────────────────────────────

def _apply_1h(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r["entry_filled"]: continue
        if r.get("timeframe") != "1h": continue
        if r.get("pattern_name") not in _PAT_1H: continue
        if r.get("symbol", "").upper() not in VALIDATED_SYMBOLS: continue
        if r.get("pattern_name") == "engulfing_bullish":
            reg = r.get("market_regime", "")
            if reg and reg not in ("bear", "neutral"):
                continue
        h = _et_hour(r.get("pattern_timestamp", ""))
        if h == 3: continue
        s = r["pattern_strength"]
        if not (MIN_STR <= s < MAX_STR): continue
        rp = r["risk_pct"]
        d  = r.get("direction", "bullish").lower()
        if d == "bullish" and rp > MAX_RISK_LONG: continue
        if d == "bearish" and rp > MAX_RISK_SHORT: continue
        bte = r["bars_to_entry"]
        if bte is None or bte > BTE_1H: continue
        out.append(r)
    return out

def _eod_1h(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        bx = r.get("bars_to_exit")
        if bx is not None and bx > EOD_BAR:
            row = dict(r)
            row["pnl_r"] = r["pnl_r"] * (EOD_BAR / bx) - EOD_SLIP
            row["bars_to_exit"] = EOD_BAR
            row["_eod_adjusted"] = True
            out.append(row)
        else:
            out.append(r)
    return out

def _apply_5m(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r["entry_filled"]: continue
        if r.get("timeframe") != "5m": continue
        if r.get("provider") != "alpaca": continue
        if r.get("pattern_name") not in _PAT_5M: continue
        sym = r.get("symbol", "").upper()
        if sym in _BLOK_5M: continue
        h = _et_hour(r.get("pattern_timestamp", ""))
        if h < 11: continue
        s = r["pattern_strength"]
        if not (MIN_STR <= s < MAX_STR): continue
        rp = r["risk_pct"]
        d  = r.get("direction", "bullish").lower()
        if d == "bullish" and rp > MAX_RISK_LONG: continue
        if d == "bearish" and rp > MAX_RISK_SHORT: continue
        bte = r["bars_to_entry"]
        if bte is None or bte > BTE_5M: continue
        out.append(r)
    return out


# ── Stats helper ──────────────────────────────────────────────────────────────

def _stats(rows: list[dict], label: str) -> dict:
    if not rows:
        return {"label": label, "n": 0, "avg_r": 0, "wr": 0, "avg_r_net": 0}
    pnls = [r["pnl_r"] for r in rows]
    n    = len(pnls)
    avg  = sum(pnls) / n
    wr   = sum(1 for p in pnls if p > 0) / n * 100
    net  = avg - SLIP
    return {"label": label, "n": n, "avg_r": avg, "wr": wr, "avg_r_net": net}

def _print_year_table(year_stats: list[dict], title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)
    hdr = f"  {'Periodo':<15} {'n_trade':>8} {'avg_r':>8} {'WR%':>7} {'avg_r netto':>12}  {'Segnale':<12}"
    print(hdr)
    print("  " + "-" * 80)
    for s in year_stats:
        if s["n"] == 0:
            print(f"  {s['label']:<15} {'—':>8} {'—':>8} {'—':>7} {'—':>12}  {'—'}")
            continue
        sig = "✓ EDGE" if s["avg_r_net"] > 0.20 else \
              "~ DEBOLE" if s["avg_r_net"] > 0.10 else \
              "? DEGRADATO" if s["avg_r_net"] >= 0 else "✗ NO EDGE"
        print(f"  {s['label']:<15} {s['n']:>8,} {s['avg_r']:>+8.3f}R {s['wr']:>6.1f}%"
              f" {s['avg_r_net']:>+11.3f}R  {sig}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(SEP)
    print("  OOS TEST 2026 — Sistema Intraday (tutti i fix + filtri produzione)")
    print(SEP)

    # ── 1h: carica e unisci dataset ──────────────────────────────────────────
    print("\nCaricamento dati 1h...")
    raw1h_full = _load_csv("data/val_1h_full.csv")
    raw1h_post = _load_csv("data/val_1h_large_post_fix.csv")

    # Deduplicazione per opportunity_id
    seen_ids: set[str] = set()
    raw1h_all: list[dict] = []
    for r in raw1h_full + raw1h_post:
        oid = r.get("opportunity_id", "")
        key = str(oid) if oid else f"{r.get('symbol')}_{r.get('pattern_timestamp')}_{r.get('pattern_name')}"
        if key not in seen_ids:
            seen_ids.add(key)
            raw1h_all.append(r)

    # 2026 raw: solo da val_1h_large_post_fix (unica fonte 2026)
    raw1h_2026 = [r for r in raw1h_post if _year(r.get("pattern_timestamp","")) == 2026]

    print(f"  val_1h_full:           {len(raw1h_full):,} righe  (pre-dedup)")
    print(f"  val_1h_large_post_fix: {len(raw1h_post):,} righe  (pre-dedup)")
    print(f"  Merged unici:          {len(raw1h_all):,} righe")
    print(f"  2026 raw (post_fix):   {len(raw1h_2026):,} righe")

    # Applica filtri
    filt1h_all  = _apply_1h(raw1h_all)
    filt1h_all  = _eod_1h(filt1h_all)
    print(f"  Dopo filtri produzione + EOD: {len(filt1h_all):,} trade")

    # ── 5m: carica dataset ────────────────────────────────────────────────────
    print("\nCaricamento dati 5m...")
    raw5m = _load_csv("data/val_5m_real.csv")
    filt5m_all = _apply_5m(raw5m)
    print(f"  val_5m_real: {len(raw5m):,} righe  →  dopo filtri: {len(filt5m_all):,} trade")

    # ── Split per anno ────────────────────────────────────────────────────────
    def by_year(rows: list[dict]) -> dict[int, list[dict]]:
        d: dict[int, list[dict]] = defaultdict(list)
        for r in rows:
            y = _year(r.get("pattern_timestamp", ""))
            if y: d[y].append(r)
        return d

    y1h = by_year(filt1h_all)
    y5m = by_year(filt5m_all)

    # ── STEP 2: Confronto per anno ────────────────────────────────────────────
    all_years = sorted(set(list(y1h.keys()) + list(y5m.keys())))

    stats_1h: list[dict] = []
    stats_5m: list[dict] = []
    stats_comb: list[dict] = []

    for yr in all_years:
        label = f"  {yr} (IS)" if yr < 2026 else f"  {yr} (OOS)"
        stats_1h.append(_stats(y1h.get(yr, []), label))
        stats_5m.append(_stats(y5m.get(yr, []), label))
        comb = y1h.get(yr, []) + y5m.get(yr, [])
        stats_comb.append(_stats(comb, label))

    _print_year_table(stats_1h, "STEP 2 — CONFRONTO ANNUALE: 1h (filtri produzione + EOD + VALIDATED_SYMBOLS)")
    _print_year_table(stats_5m, "STEP 2 — CONFRONTO ANNUALE: 5m (filtri produzione + alpaca)")
    _print_year_table(stats_comb, "STEP 2 — CONFRONTO ANNUALE: COMBINATO 1h+5m")

    # ── STEP 3: Breakdown 2026 per pattern ───────────────────────────────────
    trades_2026_1h   = y1h.get(2026, [])
    trades_2026_5m   = y5m.get(2026, [])
    trades_2026_comb = trades_2026_1h + trades_2026_5m
    trades_is_1h     = [r for yr, rows in y1h.items() if yr < 2026 for r in rows]
    trades_is_5m     = [r for yr, rows in y5m.items() if yr < 2026 for r in rows]
    trades_is_comb   = trades_is_1h + trades_is_5m

    print(f"\n{SEP}")
    print("  STEP 3 — BREAKDOWN 2026 PER PATTERN")
    print(SEP)
    print(f"\n  {'Pattern':<28} {'n_2026':>7} {'avg_r 2026':>11} {'WR% 2026':>10} {'avg_r IS':>10} {'Stabile?':>10}")
    print("  " + "-" * 80)

    all_pats = _PAT_1H | _PAT_5M
    for pat in sorted(all_pats):
        rows_2026 = [r for r in trades_2026_comb if r.get("pattern_name") == pat]
        rows_is   = [r for r in trades_is_comb   if r.get("pattern_name") == pat]
        n_2026  = len(rows_2026)
        n_is    = len(rows_is)
        if n_2026 == 0 and n_is == 0:
            continue
        avg_2026 = sum(r["pnl_r"] for r in rows_2026) / n_2026 if n_2026 else float("nan")
        wr_2026  = sum(1 for r in rows_2026 if r["pnl_r"] > 0) / n_2026 * 100 if n_2026 else float("nan")
        avg_is   = sum(r["pnl_r"] for r in rows_is)   / n_is   if n_is else float("nan")

        if n_2026 == 0:
            stab = "no dati"
        elif n_2026 < 5:
            stab = "n troppo basso"
        elif avg_2026 > 0.20:
            stab = "✓ STABILE"
        elif avg_2026 > 0.0:
            stab = "~ DEBOLE"
        elif avg_2026 >= -0.20:
            stab = "? DEGRADATO"
        else:
            stab = "✗ PERSO EDGE"

        avg_2026_s = f"{avg_2026:+.3f}R" if n_2026 > 0 else "—"
        wr_2026_s  = f"{wr_2026:.1f}%"   if n_2026 > 0 else "—"
        avg_is_s   = f"{avg_is:+.3f}R"   if n_is > 0 else "—"
        print(f"  {pat:<28} {n_2026:>7,} {avg_2026_s:>11} {wr_2026_s:>10} {avg_is_s:>10} {stab:>10}")

    # ── STEP 4: Breakdown 2026 per simbolo (top 10 per volume) ───────────────
    print(f"\n{SEP}")
    print("  STEP 4 — BREAKDOWN 2026 PER SIMBOLO (top 15 per volume)")
    print(SEP)
    print(f"\n  {'Simbolo':<8} {'n_2026':>7} {'avg_r 2026':>11} {'WR% 2026':>10} {'avg_r IS':>10} {'Stabile?':>12}")
    print("  " + "-" * 80)

    sym_data_2026: dict[str, list[float]] = defaultdict(list)
    sym_data_is:   dict[str, list[float]] = defaultdict(list)

    for r in trades_2026_comb:
        sym_data_2026[r.get("symbol","?").upper()].append(r["pnl_r"])
    for r in trades_is_comb:
        sym_data_is[r.get("symbol","?").upper()].append(r["pnl_r"])

    all_syms_2026 = sorted(sym_data_2026.items(), key=lambda x: -len(x[1]))
    for sym, pnls in all_syms_2026[:15]:
        n_2026  = len(pnls)
        avg_2026 = sum(pnls) / n_2026
        wr_2026  = sum(1 for p in pnls if p > 0) / n_2026 * 100
        is_pnls  = sym_data_is.get(sym, [])
        avg_is   = sum(is_pnls) / len(is_pnls) if is_pnls else float("nan")

        if n_2026 < 3:
            stab = "n troppo basso"
        elif avg_2026 > 0.20:
            stab = "✓ STABILE"
        elif avg_2026 > 0.0:
            stab = "~ DEBOLE"
        elif avg_2026 >= -0.20:
            stab = "? DEGRADATO"
        else:
            stab = "✗ PERSO EDGE"

        avg_is_s = f"{avg_is:+.3f}R" if is_pnls else "—"
        print(f"  {sym:<8} {n_2026:>7,} {avg_2026:>+11.3f}R {wr_2026:>9.1f}% {avg_is_s:>10} {stab:>12}")

    # ── STEP 5: Verdetto finale ────────────────────────────────────────────────
    n_2026 = len(trades_2026_comb)
    avg_2026_net = (sum(r["pnl_r"] for r in trades_2026_comb) / n_2026 - SLIP) if n_2026 else 0
    avg_2026_raw = sum(r["pnl_r"] for r in trades_2026_comb) / n_2026 if n_2026 else 0
    wr_2026 = sum(1 for r in trades_2026_comb if r["pnl_r"] > 0) / n_2026 * 100 if n_2026 else 0

    n_is    = len(trades_is_comb)
    avg_is_raw = sum(r["pnl_r"] for r in trades_is_comb) / n_is if n_is else 0
    avg_is_net = avg_is_raw - SLIP

    print(f"\n{SEP}")
    print("  STEP 5 — VERDETTO OOS")
    print(SEP)
    print(f"""
  Dataset: 1h data fino a 27-feb-2026 | 5m data fino a 22-apr-2026

  PERIODO IS  (2023-2025): {n_is:,} trade  avg_r_lordo={avg_is_raw:+.3f}R  avg_r_netto={avg_is_net:+.3f}R
  PERIODO OOS (2026):      {n_2026:,} trade  avg_r_lordo={avg_2026_raw:+.3f}R  avg_r_netto={avg_2026_net:+.3f}R  WR={wr_2026:.1f}%
  """)

    degradation = avg_2026_raw / avg_is_raw * 100 if avg_is_raw else 0

    if avg_2026_net > 0.20:
        verdict = "EDGE CONFERMATO — sistema profittevole OOS. Edge = reale, non overfitting."
    elif avg_2026_net > 0.10:
        verdict = "EDGE DEBOLE ma positivo. Sistema viable ma monitorare da vicino."
    elif avg_2026_net >= 0:
        verdict = "EDGE MARGINALE (< +0.10R netto). Sistema vicino al breakeven. Attenzione."
    elif avg_2026_net >= -0.10:
        verdict = "EDGE DEGRADATO (netto negativo). Ridurre size, ricalibrare."
    else:
        verdict = "EDGE PERSO — sistema non funziona OOS. STOP."

    print(f"  Edge retention OOS vs IS: {degradation:.0f}%  (100% = identico all'IS)")
    print(f"\n  ► {verdict}")

    # ── Extra: distribuzione mensile 2026 ────────────────────────────────────
    print(f"\n{SEP}")
    print("  EXTRA — DISTRIBUZIONE MENSILE 2026 (combinato 1h+5m)")
    print(SEP)
    print(f"\n  {'Mese':<10} {'n':>6} {'avg_r':>8} {'WR%':>7} {'avg_r_netto':>13}  {'OK?'}")
    print("  " + "-" * 60)

    months_2026: dict[str, list[float]] = defaultdict(list)
    for r in trades_2026_comb:
        dt = _parse_ts(r.get("pattern_timestamp",""))
        if dt: months_2026[f"{dt.year}-{dt.month:02d}"].append(r["pnl_r"])

    for m in sorted(months_2026.keys()):
        pnls = months_2026[m]
        n    = len(pnls)
        avg  = sum(pnls) / n
        wr   = sum(1 for p in pnls if p > 0) / n * 100
        net  = avg - SLIP
        ok   = "✓" if net > 0.10 else ("~" if net >= 0 else "✗")
        print(f"  {m:<10} {n:>6,} {avg:>+8.3f}R {wr:>6.1f}% {net:>+12.3f}R  {ok}")

    # ── Extra: distribuzione 1h vs 5m in 2026 ─────────────────────────────────
    print(f"\n{SEP}")
    print("  EXTRA — 1h vs 5m SEPARATI in 2026")
    print(SEP)
    for label, trades in [("1h (yahoo)", trades_2026_1h), ("5m (alpaca)", trades_2026_5m)]:
        if not trades:
            print(f"  {label}: nessun dato")
            continue
        n    = len(trades)
        avg  = sum(r["pnl_r"] for r in trades) / n
        wr   = sum(1 for r in trades if r["pnl_r"] > 0) / n * 100
        net  = avg - SLIP
        print(f"  {label}: n={n:,}  avg_r_lordo={avg:+.3f}R  WR={wr:.1f}%  avg_r_netto={net:+.3f}R")

    print(f"\n{SEP}")
    print("  NOTA METODOLOGICA")
    print(SEP)
    print("""
  1h data  : val_1h_full.csv (2023-ott2025) + val_1h_large_post_fix.csv (fino feb2026)
  5m data  : val_5m_real.csv (2023-apr2026, provider=alpaca)
  Filtri   : IDENTICI alla produzione corrente (mc_finale_ep.py)
             — entry_filled=True, pattern in lista validata
             — VALIDATED_SYMBOLS_YAHOO (47 simboli, solo per 1h)
             — strength [0.60, 0.80), risk_pct LONG<=3% SHORT<=2%
             — bars_to_entry <=4 (1h) <=3 (5m)
             — EOD close (max 7 barre 1h, penalità -0.05R)
             — 5m: no 03-10ET, alpaca provider, no BLOK_5M
  slip     : 0.15R per calcolo avg_r_netto
  Caveat   : 1h OOS = 2 mesi (gen-feb 2026) — campione piccolo per 1h
             5m OOS = 3.7 mesi (gen-apr 2026) — più affidabile
  """)


if __name__ == "__main__":
    main()

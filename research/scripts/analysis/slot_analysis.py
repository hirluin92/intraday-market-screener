#!/usr/bin/env python3
"""
slot_analysis.py — Analisi strategie di slot management (max 5 posizioni)
==========================================================================
Analisi 1: FIFO regret — quanto perdiamo rispetto all'ottimo?
Analisi 2: Confronto 5 strategie (A=FIFO, B=Score-based, C=Reservation,
           D=Time-weighted, E=Slot separation 1h/5m)
Analisi 3: Raccomandazione strategia migliore
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _TZ_ET = _ZoneInfo("America/New_York")
except Exception:
    _TZ_ET = None  # type: ignore[assignment]

# ── Configurazione ────────────────────────────────────────────────────────────
MAX_POS      = 5
RISK         = 0.005
CAPITAL      = 100_000.0
SLIP         = 0.15      # slippage default 0.15R
REPL_PNL     = 0.0       # pnl_r assegnato al trade "chiuso forzatamente" per rimpiazzo

# Soglia per HIGH_EDGE (Strategy C)
HIGH_EDGE_THRESHOLD = 9  # screener_score <= 9

# Pattern weights (basati su avg_r storico osservato)
_PATTERN_W: dict[str, float] = {
    "macd_divergence_bull": 1.00,
    "macd_divergence_bear": 1.00,
    "double_bottom":        0.85,
    "double_top":           0.85,
    "rsi_divergence_bull":  0.65,
    "rsi_divergence_bear":  0.65,
}

# ── Filtri produzione (copia da final_monte_carlo.py) ────────────────────────
_PATTERNS_1H  = frozenset({"double_bottom","double_top","macd_divergence_bull",
                            "rsi_divergence_bull","macd_divergence_bear",
                            "rsi_divergence_bear","engulfing_bullish"})
_PATTERNS_5M  = frozenset({"double_top","double_bottom",
                            "macd_divergence_bull","macd_divergence_bear"})
_BLOCKED_5M   = frozenset({"SPY","AAPL","MSFT","GOOGL","WMT"})
MAX_RISK_LONG  = 3.0
MAX_RISK_SHORT = 2.0
MAX_STRENGTH   = 0.80
MIN_STRENGTH   = 0.60
MAX_BTE_1H     = 4
MAX_BTE_5M     = 3
EOD_CUTOFF     = 7


# ── Utilità ───────────────────────────────────────────────────────────────────

def _et_hm(ts: str) -> tuple[int, int]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        det = dt.astimezone(_TZ_ET) if _TZ_ET else (dt - timedelta(hours=4))
        return det.hour, det.minute
    except Exception:
        return 12, 0


def _parse_ts(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None


def _load_csv(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["pnl_r"]            = float(r["pnl_r"])
                r["risk_pct"]         = float(r.get("risk_pct") or 0)
                r["pattern_strength"] = float(r.get("pattern_strength") or 0)
                r["entry_filled"]     = r.get("entry_filled","False") == "True"
                bte = r.get("bars_to_entry")
                r["bars_to_entry"]    = int(float(bte)) if bte not in ("","None",None) else None
                bx  = r.get("bars_to_exit")
                r["bars_to_exit"]     = int(float(bx))  if bx  not in ("","None",None) else None
                sc  = r.get("screener_score")
                r["screener_score"]   = int(float(sc))  if sc  not in ("","None",None) else 10
            except (ValueError, KeyError):
                continue
            rows.append(r)
    return rows


def _data_years(rows: list[dict]) -> float:
    ts = [_parse_ts(r.get("pattern_timestamp","")) for r in rows]
    ts = [t for t in ts if t]
    if len(ts) < 2:
        return 2.5
    return max(0.5, (max(ts) - min(ts)).total_seconds() / 86400 / 365.25)


def _stats(trades: list[dict]) -> tuple[int, float, float]:
    if not trades:
        return 0, 0.0, 0.0
    pnls = [r["pnl_r"] for r in trades]
    n    = len(pnls)
    avg  = sum(pnls) / n
    wr   = sum(1 for p in pnls if p > 0) / n * 100
    return n, avg, wr


# ── Filtri produzione ─────────────────────────────────────────────────────────

def _filt_1h(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r["entry_filled"] or r.get("timeframe") != "1h":
            continue
        if r.get("pattern_name") not in _PATTERNS_1H:
            continue
        if r.get("pattern_name") == "engulfing_bullish":
            reg = r.get("market_regime","")
            if reg and reg not in ("bear","neutral"):
                continue
        h, _ = _et_hm(r.get("pattern_timestamp",""))
        if h == 3:
            continue
        s = r["pattern_strength"]
        if not (MIN_STRENGTH <= s < MAX_STRENGTH):
            continue
        rp = r["risk_pct"]
        d  = r.get("direction","bullish").lower()
        if d == "bullish" and rp > MAX_RISK_LONG:
            continue
        if d == "bearish" and rp > MAX_RISK_SHORT:
            continue
        bte = r["bars_to_entry"]
        if bte is None or bte > MAX_BTE_1H:
            continue
        out.append(r)
    return out


def _filt_5m(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not r["entry_filled"] or r.get("timeframe") != "5m":
            continue
        if r.get("provider") != "alpaca":
            continue
        if r.get("pattern_name") not in _PATTERNS_5M:
            continue
        if r.get("symbol","").upper() in _BLOCKED_5M:
            continue
        h, _ = _et_hm(r.get("pattern_timestamp",""))
        if h < 11:
            continue
        s = r["pattern_strength"]
        if not (MIN_STRENGTH <= s < MAX_STRENGTH):
            continue
        rp = r["risk_pct"]
        d  = r.get("direction","bullish").lower()
        if d == "bullish" and rp > MAX_RISK_LONG:
            continue
        if d == "bearish" and rp > MAX_RISK_SHORT:
            continue
        bte = r["bars_to_entry"]
        if bte is None or bte > MAX_BTE_5M:
            continue
        out.append(r)
    return out


def _eod_1h(rows: list[dict]) -> list[dict]:
    adj = []
    for r in rows:
        bx = r.get("bars_to_exit")
        if bx is not None and bx > EOD_CUTOFF:
            row = dict(r)
            row["pnl_r"]      = r["pnl_r"] * (EOD_CUTOFF / bx) - 0.05
            row["bars_to_exit"] = EOD_CUTOFF
            row["outcome"]    = "eod_close"
            adj.append(row)
        else:
            adj.append(r)
    return adj


def _tif_day(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        h, m = _et_hm(r.get("pattern_timestamp",""))
        tf   = r.get("timeframe","1h")
        bte  = r.get("bars_to_entry")
        if bte is None:
            out.append(r); continue
        if tf == "1h":
            rem = max(0, 16 - h)
        elif tf == "5m":
            rem = max(0, (960 - h*60 - m) // 5)
        else:
            out.append(r); continue
        if bte <= rem:
            out.append(r)
    return out


# ── Preparazione trade (entry_time, exit_time, priority) ─────────────────────

def _compute_times(r: dict) -> tuple[datetime | None, datetime | None]:
    ts  = _parse_ts(r.get("pattern_timestamp",""))
    bte = r.get("bars_to_entry") or 1
    bx  = r.get("bars_to_exit")  or EOD_CUTOFF
    tf  = r.get("timeframe","1h")
    if not ts:
        return None, None
    dur = timedelta(hours=1) if tf == "1h" else timedelta(minutes=5)
    entry = ts + bte * dur
    exit_ = entry + bx * dur
    return entry, exit_


def _priority_score(r: dict) -> float:
    """Priority 0-1, higher = migliore segnale da eseguire."""
    sc  = r.get("screener_score", 10)
    sc  = min(12, max(8, int(sc)))
    score_comp = (12 - sc) / 4  # 1.0 per sc=8, 0.0 per sc=12

    pat = r.get("pattern_name","")
    pat_w = _PATTERN_W.get(pat, 0.80)

    risk = r.get("risk_pct", 1.0)
    risk_comp = 1.0 / (1.0 + risk * 0.5)  # lower risk = higher priority

    return score_comp * pat_w * risk_comp


def _time_multiplier(r: dict) -> float:
    """Moltiplicatore orario per Strategy D."""
    h, _ = _et_hm(r.get("pattern_timestamp",""))
    if h >= 14:
        return 2.0
    if h >= 11:
        return 1.5
    return 1.0


def _prepare(rows_1h_raw: list[dict], rows_5m_raw: list[dict]) -> list[dict]:
    """Applica filtri produzione, EOD, TIF=DAY e arricchisce ogni trade."""
    r1 = _tif_day(_eod_1h(_filt_1h(rows_1h_raw)))
    r5 = _tif_day(_filt_5m(rows_5m_raw))

    combined = []
    for r in r1 + r5:
        entry, exit_ = _compute_times(r)
        if entry is None or exit_ is None:
            continue
        t = dict(r)
        t["entry_time"]  = entry
        t["exit_time"]   = exit_
        t["priority"]    = _priority_score(r)
        t["prio_timed"]  = _priority_score(r) * _time_multiplier(r)
        h, _m = _et_hm(r.get("pattern_timestamp",""))
        t["hour_et"]     = h
        t["is_high_edge"] = (r.get("screener_score",10) <= HIGH_EDGE_THRESHOLD)
        combined.append(t)

    combined.sort(key=lambda x: (x["entry_time"], -x["priority"]))
    return combined


# ── Simulazioni ───────────────────────────────────────────────────────────────
# Ogni simulazione ritorna:
#   executed:  lista di trade con pnl_r (eseguiti a piena conclusione)
#   skipped:   lista di trade saltati (slot pieni)
#   replaced:  lista di trade chiusi in anticipo (pnl_r = REPL_PNL)

def _expire(active: list[dict], entry_time: datetime) -> list[dict]:
    return [a for a in active if a["exit_time"] > entry_time]


# --- Strategy A: FIFO --------------------------------------------------------

def strategy_a(trades: list[dict], max_pos: int = MAX_POS) -> tuple[list, list, list]:
    executed, skipped, replaced = [], [], []
    active: list[dict] = []
    for t in trades:
        active = _expire(active, t["entry_time"])
        if len(active) < max_pos:
            active.append(t)
            executed.append(t)
        else:
            skipped.append({**t, "_worst_active_pnl": min(a["pnl_r"] for a in active),
                            "_worst_active_prio": min(a["priority"] for a in active)})
    return executed, skipped, replaced


# --- Strategy B: Score-based replacement -------------------------------------

def strategy_b(trades: list[dict], max_pos: int = MAX_POS,
               min_improvement: float = 0.05) -> tuple[list, list, list]:
    """
    Se slot pieni: confronta priority del nuovo con il trade aperto con
    priority piu' bassa. Se il nuovo e' migliore di min_improvement: rimpiazza.
    Il trade rimpiazzato ottiene pnl_r = REPL_PNL (chiusura forzata).
    """
    executed, skipped, replaced = [], [], []
    active: list[dict] = []
    for t in trades:
        active = _expire(active, t["entry_time"])
        if len(active) < max_pos:
            active.append(t)
            executed.append(t)
        else:
            # Trova il trade aperto con la priority piu' bassa
            worst_idx = min(range(len(active)), key=lambda i: active[i]["priority"])
            worst = active[worst_idx]
            if t["priority"] > worst["priority"] + min_improvement:
                # Rimpiazza: il vecchio esce a REPL_PNL
                rep = dict(worst)
                rep["pnl_r"] = REPL_PNL
                rep["_replaced_by"] = t.get("opportunity_id","")
                replaced.append(rep)
                active[worst_idx] = t
                executed.append(t)
            else:
                skipped.append({**t, "_worst_active_pnl": min(a["pnl_r"] for a in active),
                               "_worst_active_prio": worst["priority"]})
    # I rimpiazzati vengono inclusi nel conto P&L come pnl_r=REPL_PNL
    return executed, skipped, replaced


# --- Strategy C: Reservation system ------------------------------------------

def strategy_c(trades: list[dict],
               normal_slots: int = 4,
               reserved_slots: int = 1) -> tuple[list, list, list]:
    """
    Slot 1-4: FIFO per tutti i trade.
    Slot 5: riservato solo per HIGH_EDGE (screener_score <= HIGH_EDGE_THRESHOLD).
      - Se HIGH_EDGE arriva e slot 5 libero: usa slot 5.
      - Se slot 5 occupato da HIGH_EDGE e il nuovo ha priority > occupante: rimpiazza.
      - Se nessun HIGH_EDGE: slot 5 rimane vuoto.
    """
    executed, skipped, replaced = [], [], []
    # active_normal: max normal_slots, any trade
    # active_reserved: max reserved_slots, only HIGH_EDGE
    active_normal:   list[dict] = []
    active_reserved: list[dict] = []

    for t in trades:
        active_normal   = _expire(active_normal,   t["entry_time"])
        active_reserved = _expire(active_reserved, t["entry_time"])

        if t["is_high_edge"]:
            # Prova slot normali prima
            if len(active_normal) < normal_slots:
                active_normal.append(t)
                executed.append(t)
            elif len(active_reserved) < reserved_slots:
                active_reserved.append(t)
                executed.append(t)
            else:
                # Slot 5 occupato da HIGH_EDGE: confronta priority
                worst_idx = min(range(len(active_reserved)),
                                key=lambda i: active_reserved[i]["priority"])
                worst = active_reserved[worst_idx]
                if t["priority"] > worst["priority"] + 0.05:
                    rep = dict(worst)
                    rep["pnl_r"] = REPL_PNL
                    replaced.append(rep)
                    active_reserved[worst_idx] = t
                    executed.append(t)
                else:
                    skipped.append(t)
        else:
            # Trade normale: solo slot 1-4
            if len(active_normal) < normal_slots:
                active_normal.append(t)
                executed.append(t)
            else:
                skipped.append({**t, "_worst_active_pnl": min(a["pnl_r"] for a in active_normal),
                               "_worst_active_prio": min(a["priority"] for a in active_normal)})
    return executed, skipped, replaced


# --- Strategy D: Time-weighted priority --------------------------------------

def strategy_d(trades: list[dict], max_pos: int = MAX_POS,
               min_improvement: float = 0.08) -> tuple[list, list, list]:
    """
    Come B, ma usa prio_timed (priority × time_multiplier) come metrica.
    Pomeriggio (>=14h ET) ha peso 2x, mattina 1x.
    """
    executed, skipped, replaced = [], [], []
    active: list[dict] = []
    for t in trades:
        active = _expire(active, t["entry_time"])
        if len(active) < max_pos:
            active.append(t)
            executed.append(t)
        else:
            worst_idx = min(range(len(active)), key=lambda i: active[i]["prio_timed"])
            worst = active[worst_idx]
            if t["prio_timed"] > worst["prio_timed"] + min_improvement:
                rep = dict(worst)
                rep["pnl_r"] = REPL_PNL
                replaced.append(rep)
                active[worst_idx] = t
                executed.append(t)
            else:
                skipped.append(t)
    return executed, skipped, replaced


# --- Strategy E: Slot separation 1h/5m  (3 + 2) -----------------------------

def strategy_e(trades: list[dict],
               slots_1h: int = 3,
               slots_5m: int = 2) -> tuple[list, list, list]:
    """
    3 slot dedicati 1h, 2 slot dedicati 5m.
    Il 1h puo' usare slot 5m se quelli 1h sono pieni e quelli 5m liberi.
    Il 5m NON puo' usare slot 1h.
    """
    executed, skipped, replaced = [], [], []

    # Ogni active ha un campo 'slot_type': '1h_own' | '1h_borrow' | '5m'
    active: list[dict] = []

    def _count_slots(active: list[dict]) -> tuple[int, int, int]:
        n1_own = sum(1 for a in active if a["_slot"] == "1h_own")
        n1_bor = sum(1 for a in active if a["_slot"] == "1h_borrow")
        n5     = sum(1 for a in active if a["_slot"] == "5m")
        return n1_own, n1_bor, n5

    for t in trades:
        active = _expire(active, t["entry_time"])
        n1_own, n1_bor, n5 = _count_slots(active)
        tf = t.get("timeframe","1h")

        if tf == "1h":
            entry_t = dict(t)
            if n1_own < slots_1h:
                entry_t["_slot"] = "1h_own"
                active.append(entry_t)
                executed.append(t)
            elif (n1_bor + n5) < slots_5m:
                # Prende in prestito un slot 5m
                entry_t["_slot"] = "1h_borrow"
                active.append(entry_t)
                executed.append(t)
            else:
                skipped.append(t)
        else:  # 5m
            # 5m puo' usare solo slot 5m (non quelli 1h)
            n5m_free = slots_5m - n1_bor - n5  # slot 5m liberi
            if n5m_free > 0:
                entry_t = dict(t)
                entry_t["_slot"] = "5m"
                active.append(entry_t)
                executed.append(t)
            else:
                skipped.append(t)
    return executed, skipped, replaced


# ── Output helpers ────────────────────────────────────────────────────────────

def _annual_stats(all_trades: list[dict], years: float) -> dict:
    """Calcola metriche annualizzate: trades/anno, avg_r_gross, avg_r_net, WR, rend_semplice."""
    if not all_trades:
        return {"tpy": 0, "avg_gross": 0, "avg_net": 0, "wr": 0, "rend": 0}
    pnls = [r["pnl_r"] for r in all_trades]
    n    = len(pnls)
    avg  = sum(pnls) / n
    wr   = sum(1 for p in pnls if p > 0) / n * 100
    tpy  = n / years
    avg_net = avg - SLIP
    rend = tpy * avg_net * RISK * 100  # % annuo semplice
    return {"tpy": tpy, "avg_gross": avg, "avg_net": avg_net, "wr": wr, "rend": rend, "n": n}


def _equity_compound_12m(tpy: float, avg_r_net: float) -> float:
    """Equity mediana stimata — semplificata (non MC, usa mean-of-log approx)."""
    if tpy <= 0 or avg_r_net <= -1:
        return CAPITAL
    monthly_trades = tpy / 12
    factor_per_trade = 1.0 + avg_r_net * RISK
    if factor_per_trade <= 0:
        return 0.0
    import math
    # geometrica: (1 + avg_r_net * RISK)^(12 * monthly_trades)
    annual_factor = factor_per_trade ** (12 * monthly_trades)
    return CAPITAL * annual_factor


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    base = Path(__file__).parent

    # Carica dati
    p1h = base / "data" / "val_1h_production.csv"
    p5m = base / "data" / "val_5m_expanded.csv"

    print("Caricamento dati...")
    raw_1h = _load_csv(p1h)
    raw_5m = _load_csv(p5m)
    print(f"  1h raw: {len(raw_1h):,}  |  5m raw: {len(raw_5m):,}")

    trades = _prepare(raw_1h, raw_5m)
    years  = _data_years(trades)
    n_1h   = sum(1 for t in trades if t.get("timeframe") == "1h")
    n_5m   = sum(1 for t in trades if t.get("timeframe") == "5m")
    print(f"  Trade combinati dopo filtri+EOD+TIF: {len(trades):,}  ({n_1h} 1h + {n_5m} 5m)")
    print(f"  Dati: {years:.2f} anni  =>  {len(trades)/years:.0f} trade/anno baseline\n")

    # ── ANALISI 1 — FIFO regret ────────────────────────────────────────────────
    ex_a, sk_a, rep_a = strategy_a(trades)

    print("=" * 80)
    print("ANALISI 1 — FIFO regret (quanto perdiamo con lo skip passivo?)")
    print("=" * 80)

    n_exec  = len(ex_a)
    n_skip  = len(sk_a)
    n_total = n_exec + n_skip

    avg_r_exec = sum(t["pnl_r"] for t in ex_a) / max(1, n_exec)
    avg_r_skip = sum(t["pnl_r"] for t in sk_a) / max(1, n_skip)

    # Regret: skippati che erano migliori del peggiore attivo
    regret_count  = sum(1 for s in sk_a if s["pnl_r"] > s["_worst_active_pnl"])
    skip_gt_1r    = sum(1 for s in sk_a if s["pnl_r"] > 1.0)
    skip_gt_2r    = sum(1 for s in sk_a if s["pnl_r"] > 2.0)
    skip_negative = sum(1 for s in sk_a if s["pnl_r"] < 0.0)

    # Regret per timeframe
    sk_1h = [s for s in sk_a if s.get("timeframe") == "1h"]
    sk_5m = [s for s in sk_a if s.get("timeframe") == "5m"]
    avg_skip_1h = sum(t["pnl_r"] for t in sk_1h) / max(1, len(sk_1h))
    avg_skip_5m = sum(t["pnl_r"] for t in sk_5m) / max(1, len(sk_5m))

    # Pattern breakdown dei skippati (top 5)
    from collections import Counter
    skip_by_pat = defaultdict(list)
    for s in sk_a:
        skip_by_pat[s.get("pattern_name","?")].append(s["pnl_r"])

    rows_table1 = [
        ("Trade totali (pre-slot)",          f"{n_total:,}"),
        ("Trade eseguiti (FIFO)",            f"{n_exec:,}   ({n_exec/n_total*100:.1f}%)"),
        ("Trade skippati (slot pieni)",      f"{n_skip:,}   ({n_skip/n_total*100:.1f}%)"),
        ("avg_r eseguiti",                   f"+{avg_r_exec:.3f}R"),
        ("avg_r skippati",                   f"+{avg_r_skip:.3f}R"),
        ("Skippati con pnl_r > peggiore aperto (RIMPIANTI)", f"{regret_count:,}  ({regret_count/max(1,n_skip)*100:.1f}% degli skip)"),
        ("Skippati con avg_r > 1.0R",        f"{skip_gt_1r:,}  ({skip_gt_1r/max(1,n_skip)*100:.1f}%)"),
        ("Skippati con avg_r > 2.0R",        f"{skip_gt_2r:,}  ({skip_gt_2r/max(1,n_skip)*100:.1f}%)"),
        ("Skippati con pnl_r < 0 (bullet dodged)", f"{skip_negative:,}  ({skip_negative/max(1,n_skip)*100:.1f}%)"),
        ("avg_r skippati 1h",                f"+{avg_skip_1h:.3f}R  ({len(sk_1h):,} trade)"),
        ("avg_r skippati 5m",                f"+{avg_skip_5m:.3f}R  ({len(sk_5m):,} trade)"),
    ]

    col1 = max(len(r[0]) for r in rows_table1) + 2
    for label, val in rows_table1:
        print(f"  {label:<{col1}} {val}")

    print()
    print("  Dettaglio skippati per pattern:")
    print(f"  {'Pattern':<28} {'n_skip':>7}  {'avg_r':>8}  {'WR%':>6}")
    print("  " + "-" * 55)
    for pat, pnls in sorted(skip_by_pat.items(), key=lambda x: -len(x[1])):
        avg_p = sum(pnls) / len(pnls)
        wr_p  = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        print(f"  {pat:<28} {len(pnls):>7}  {avg_p:>+8.3f}R  {wr_p:>5.1f}%")

    # Distribuzione pnl_r degli skippati vs eseguiti
    def _bucket(pnl: float) -> str:
        if pnl < -1:   return "< -1R"
        if pnl < 0:    return "-1R - 0R"
        if pnl < 1:    return " 0R - 1R"
        if pnl < 2:    return " 1R - 2R"
        if pnl < 3:    return " 2R - 3R"
        return "> 3R"

    buckets_order = ["< -1R","-1R - 0R"," 0R - 1R"," 1R - 2R"," 2R - 3R","> 3R"]
    exec_dist  = Counter(_bucket(t["pnl_r"]) for t in ex_a)
    skip_dist  = Counter(_bucket(t["pnl_r"]) for t in sk_a)

    print()
    print("  Distribuzione pnl_r: Eseguiti vs Skippati")
    print(f"  {'Bucket':<12} {'Exec%':>7}  {'Skip%':>7}")
    print("  " + "-" * 30)
    for b in buckets_order:
        ep = exec_dist.get(b, 0) / max(1, n_exec) * 100
        sp = skip_dist.get(b, 0) / max(1, n_skip) * 100
        print(f"  {b:<12} {ep:>6.1f}%  {sp:>6.1f}%")

    print()
    print("  INTERPRETAZIONE:")
    if avg_r_skip > avg_r_exec:
        diff = avg_r_skip - avg_r_exec
        print(f"  *** Gli skippati hanno avg_r SUPERIORE (+{diff:.3f}R) ai trade eseguiti!")
        print(f"      Il FIFO sta eseguendo trade di qualita' inferiore.")
    elif avg_r_skip < 0:
        print(f"  Gli skippati hanno avg_r NEGATIVO ({avg_r_skip:.3f}R).")
        print(f"  Il FIFO evita casualmente trade perdenti (\"bullet dodged\"): {skip_negative/max(1,n_skip)*100:.1f}% negativi.")
    else:
        print(f"  Gli skippati hanno avg_r simile o inferiore agli eseguiti. FIFO e' ragionevole.")
    print(f"  Rimpianti netti: {regret_count} trade ({regret_count/max(1,n_skip)*100:.1f}%) con pnl_r migliore del peggiore aperto.")

    # ── ANALISI 2 — Confronto strategie ───────────────────────────────────────
    print()
    print("=" * 80)
    print("ANALISI 2 — Confronto strategie slot management")
    print("=" * 80)
    print("  (tutte vs dataset combinato 1h+5m dopo filtri+EOD+TIF=DAY)")
    print()

    # Calcola stats per ogni strategia
    strategies = {
        "A — FIFO (attuale)":             strategy_a,
        "B — Score-based replacement":    strategy_b,
        "C — Reservation (1 slot HE)":   strategy_c,
        "D — Time-weighted replace":      strategy_d,
        "E — Slot separation (3+2)":      strategy_e,
    }

    results: dict[str, dict] = {}
    for name, fn in strategies.items():
        ex, sk, rep = fn(trades)
        # P&L totale = eseguiti (full pnl_r) + rimpiazzati (pnl_r=REPL_PNL=0)
        all_positions = ex + rep
        stats = _annual_stats(all_positions, years)
        results[name] = {
            "n_exec": len(ex),
            "n_skip": len(sk),
            "n_repl": len(rep),
            "n_total_positions": len(all_positions),
            "stats": stats,
        }

    # Header tabella
    col_s = 34
    header = (f"  {'Strategia':<{col_s}} "
              f"{'n_pos':>6}  {'n_skip':>6}  {'n_repl':>6}  "
              f"{'avg_r(G)':>9}  {'avg_r(N)':>9}  {'WR%':>6}  "
              f"{'Rend.sem./a':>11}  {'BE slip':>7}")
    print(header)
    print("  " + "-" * (len(header) - 2))

    best_rend   = max(v["stats"]["rend"] for v in results.values())
    best_avgnet = max(v["stats"]["avg_net"] for v in results.values())

    for name, r in results.items():
        s   = r["stats"]
        rend = s["rend"]
        be_slip = s["avg_gross"]  # breakeven slippage = avg_r_gross
        flag_rend = " <-- BEST rend" if abs(rend - best_rend) < 0.01 else ""
        flag_avg  = " <-- BEST avg_r" if abs(s["avg_net"] - best_avgnet) < 0.0001 else ""
        print(f"  {name:<{col_s}} "
              f"{r['n_total_positions']:>6,}  {r['n_skip']:>6,}  {r['n_repl']:>6,}  "
              f"{s['avg_gross']:>+9.3f}R  {s['avg_net']:>+9.3f}R  {s['wr']:>5.1f}%  "
              f"{rend:>+10.1f}%  {be_slip:>6.3f}R"
              f"{flag_rend}{flag_avg}")

    print()
    print("  LEGENDA:")
    print("  n_pos    = posizioni totali entrate (incl. replacement che escono a 0R)")
    print("  n_skip   = segnali saltati per slot pieni")
    print("  n_repl   = trade chiusi anticipatamente (rimpiazzati, pnl_r=0R — conservativo)")
    print("  avg_r(G) = avg pnl_r lordo (prima del slippage)")
    print("  avg_r(N) = avg pnl_r netto (lordo - 0.15R slippage)")
    print("  Rend.sem.= trades/anno x avg_r_netto x 0.5% risk (non composto)")
    print("  BE slip  = slippage al quale avg_r_netto = 0 (= avg_r_gross)")

    # ── Dettaglio per timeframe nelle strategie chiave ────────────────────────
    print()
    print("  Dettaglio 1h vs 5m — strategia B vs E:")

    for strat_name, fn in [("B — Score-based", strategy_b), ("E — Slot sep. 3+2", strategy_e)]:
        ex, sk, rep = fn(trades)
        ex1h = [t for t in ex if t.get("timeframe") == "1h"]
        ex5m = [t for t in ex if t.get("timeframe") == "5m"]
        n1h, a1h, w1h = _stats(ex1h)
        n5m, a5m, w5m = _stats(ex5m)
        print(f"  {strat_name}:")
        print(f"    1h: {n1h:>5,} trade  avg_r={a1h:+.3f}R  WR={w1h:.1f}%")
        print(f"    5m: {n5m:>5,} trade  avg_r={a5m:+.3f}R  WR={w5m:.1f}%")

    # ── Distribuzione pnl_r per strategia ─────────────────────────────────────
    print()
    print("  Distribuzione pnl_r per strategia:")
    print(f"  {'Bucket':<12}", end="")
    for name in results:
        short = name.split("—")[0].strip()
        print(f"  {short:>6}", end="")
    print()
    print("  " + "-" * (14 + 8 * len(results)))

    for b in buckets_order:
        print(f"  {b:<12}", end="")
        for name, r in results.items():
            ex_t, sk_t, rep_t = strategies[name](trades)
            all_p = ex_t + rep_t
            pct = sum(1 for t in all_p if _bucket(t["pnl_r"]) == b) / max(1, len(all_p)) * 100
            print(f"  {pct:>5.1f}%", end="")
        print()

    # ── ANALISI 3 — Raccomandazione ────────────────────────────────────────────
    print()
    print("=" * 80)
    print("ANALISI 3 — Raccomandazione strategia migliore")
    print("=" * 80)

    # Trova la migliore per rendimento netto semplice
    best_by_rend = max(results.items(), key=lambda x: x[1]["stats"]["rend"])
    best_by_avg  = max(results.items(), key=lambda x: x[1]["stats"]["avg_net"])

    print()
    print(f"  Miglior rendimento semplice: {best_by_rend[0]}")
    print(f"    => {best_by_rend[1]['stats']['rend']:+.1f}%/a | {best_by_rend[1]['stats']['tpy']:.0f} trade/a | avg_r_net={best_by_rend[1]['stats']['avg_net']:+.3f}R")
    print()
    print(f"  Miglior avg_r netto:         {best_by_avg[0]}")
    print(f"    => avg_r_net={best_by_avg[1]['stats']['avg_net']:+.3f}R | {best_by_avg[1]['stats']['tpy']:.0f} trade/a")

    # Analisi del trade-off qualita' vs quantita'
    print()
    print("  TRADE-OFF qualita' vs quantita':")
    ref_rend = results["A — FIFO (attuale)"]["stats"]["rend"]
    ref_avg  = results["A — FIFO (attuale)"]["stats"]["avg_net"]
    for name, r in results.items():
        dr = r["stats"]["rend"] - ref_rend
        da = r["stats"]["avg_net"] - ref_avg
        dv = r["n_skip"] - results["A — FIFO (attuale)"]["n_skip"]
        sign_dr = "+" if dr >= 0 else ""
        sign_da = "+" if da >= 0 else ""
        sign_dv = "+" if dv >= 0 else ""
        print(f"  {name:<34}  delta_rend={sign_dr}{dr:+.1f}%  delta_avg_r={sign_da}{da:+.3f}R  "
              f"delta_skip={sign_dv}{dv:+,}")

    # Analisi per High-Edge
    he_exec = [t for t in ex_a if t.get("is_high_edge")]
    he_skip_a = [t for t in sk_a if t.get("is_high_edge")]
    ne_exec = [t for t in ex_a if not t.get("is_high_edge")]
    ne_skip_a = [t for t in sk_a if not t.get("is_high_edge")]
    print()
    print(f"  Analisi HIGH_EDGE (screener_score <= {HIGH_EDGE_THRESHOLD}):")
    print(f"    Eseguiti HE: {len(he_exec):,}  avg_r={sum(t['pnl_r'] for t in he_exec)/max(1,len(he_exec)):+.3f}R")
    print(f"    Skippati HE: {len(he_skip_a):,}  avg_r={sum(t['pnl_r'] for t in he_skip_a)/max(1,len(he_skip_a)):+.3f}R")
    print(f"    Eseguiti NE: {len(ne_exec):,}  avg_r={sum(t['pnl_r'] for t in ne_exec)/max(1,len(ne_exec)):+.3f}R")
    print(f"    Skippati NE: {len(ne_skip_a):,}  avg_r={sum(t['pnl_r'] for t in ne_skip_a)/max(1,len(ne_skip_a)):+.3f}R")

    # ── Codice implementazione ─────────────────────────────────────────────────
    # Determina la strategia da mostrare in codice
    best_name = best_by_rend[0]
    print()
    print("=" * 80)
    print(f"CODICE IMPLEMENTAZIONE — {best_name}")
    print("=" * 80)
    _print_implementation_code(best_name, results[best_name])


def _print_implementation_code(strategy_name: str, strategy_result: dict) -> None:
    if "FIFO" in strategy_name:
        print("""
  Strategia FIFO e' gia' implementata. Nessuna modifica necessaria.
""")
    elif "Score-based" in strategy_name or "Score" in strategy_name:
        _print_code_b()
    elif "Reservation" in strategy_name:
        _print_code_c()
    elif "Time-weighted" in strategy_name:
        _print_code_d()
    elif "Slot sep" in strategy_name or "3+2" in strategy_name:
        _print_code_e()
    else:
        print(f"  (strategia '{strategy_name}' — vedere simulazione per logica)")


def _print_code_b() -> None:
    print("""
  # In auto_execute_service.py — funzione execute_signal()
  # Sostituisce il blocco attuale "max posizioni simultanee"

  # ── Costanti config (aggiungere in config.py) ──────────────────────────────
  # ibkr_max_simultaneous_positions: int = 5
  # ibkr_slot_strategy: str = "score_based"  # "fifo" | "score_based"
  # ibkr_slot_min_improvement: float = 0.05  # min delta priority per rimpiazzare

  # ── In execute_signal() ────────────────────────────────────────────────────

  def _compute_priority(signal: dict, settings) -> float:
      \"\"\"Priority 0-1, higher = trade migliore da eseguire/mantenere.\"\"\"
      PATTERN_W = {
          "macd_divergence_bull": 1.00, "macd_divergence_bear": 1.00,
          "double_bottom": 0.85,        "double_top": 0.85,
          "rsi_divergence_bull": 0.65,  "rsi_divergence_bear": 0.65,
      }
      sc    = getattr(signal, "screener_score", 10)
      sc    = min(12, max(8, int(sc or 10)))
      score = (12 - sc) / 4
      pat_w = PATTERN_W.get(getattr(signal, "pattern_name", ""), 0.80)
      risk  = float(getattr(signal, "risk_pct", 1.0) or 1.0)
      risk_w = 1.0 / (1.0 + risk * 0.5)
      return score * pat_w * risk_w


  # Blocco slot management (sostituisce il semplice controllo len >= max_pos):
  max_pos = settings.ibkr_max_simultaneous_positions

  if len(open_positions) < max_pos:
      pass  # slot libero, procedi normalmente
  elif settings.ibkr_slot_strategy == "score_based":
      # Calcola priority del nuovo segnale
      new_priority = _compute_priority(opportunity, settings)

      # Trova la posizione aperta con priority piu' bassa
      worst_pos  = None
      worst_prio = float("inf")
      for pos in open_positions:
          # Recupera la priority originale del segnale (salvata in metadata)
          pos_prio = pos.get("entry_priority", 0.0)
          if pos_prio < worst_prio:
              worst_prio = pos_prio
              worst_pos  = pos

      min_improvement = getattr(settings, "ibkr_slot_min_improvement", 0.05)

      if worst_pos is not None and new_priority > worst_prio + min_improvement:
          # Chiudi la posizione peggiore e apri la nuova
          logger.info(
              f"Slot replacement: chiudo {worst_pos['symbol']} "
              f"(prio={worst_prio:.3f}) per {opportunity.symbol} (prio={new_priority:.3f})"
          )
          close_result = await tws.place_market_close_order(
              symbol=worst_pos["symbol"],
              quantity=worst_pos["quantity"],
              direction=worst_pos["direction"],
          )
          if close_result.get("status") != "ok":
              return {"status": "skipped",
                      "reason": f"Rimpiazzo fallito: impossibile chiudere {worst_pos['symbol']}"}
          # Procedi con l'esecuzione del nuovo segnale
          # (il codice continua normalmente dopo questo blocco)
      else:
          return {
              "status": "skipped",
              "reason": (
                  f"Slot pieni ({len(open_positions)}/{max_pos}), "
                  f"nessun trade sostituibile "
                  f"(nuovo={new_priority:.3f}, peggiore_aperto={worst_prio:.3f})"
              ),
          }
  else:  # FIFO
      return {
          "status": "skipped",
          "reason": f"Max {max_pos} posizioni simultanee raggiunte ({len(open_positions)} aperte)",
      }

  # NOTA: salvare la priority nell'ordine/DB al momento dell'esecuzione:
  # order_metadata["entry_priority"] = _compute_priority(opportunity, settings)
""")


def _print_code_c() -> None:
    print("""
  # Strategia C: Reservation system
  # 4 slot FIFO per tutti + 1 slot riservato HIGH_EDGE (screener_score <= 9)

  HIGH_EDGE_THRESHOLD = 9  # aggiungere in config.py

  is_high_edge = (opportunity.screener_score or 10) <= settings.ibkr_high_edge_threshold

  # Conta posizioni per tipo (serve che il DB/metadata registri is_high_edge)
  normal_pos   = [p for p in open_positions if not p.get("is_high_edge", False)]
  reserved_pos = [p for p in open_positions if p.get("is_high_edge", False)]

  NORMAL_SLOTS   = 4
  RESERVED_SLOTS = 1

  if is_high_edge:
      if len(normal_pos) < NORMAL_SLOTS:
          pass  # usa slot normale
      elif len(reserved_pos) < RESERVED_SLOTS:
          pass  # usa slot riservato
      else:
          # Slot riservato occupato: confronta priority
          new_prio  = _compute_priority(opportunity, settings)
          worst_he  = min(reserved_pos, key=lambda p: p.get("entry_priority", 0.0))
          if new_prio > worst_he.get("entry_priority", 0.0) + 0.05:
              # Rimpiazza il HIGH_EDGE peggiore
              await tws.place_market_close_order(...)
          else:
              return {"status": "skipped", "reason": "Slot riservato HE occupato, priority insufficiente"}
  else:
      if len(normal_pos) < NORMAL_SLOTS:
          pass  # slot normale disponibile
      else:
          return {"status": "skipped",
                  "reason": f"4 slot normali pieni ({len(normal_pos)} pos), trade non HIGH_EDGE"}
""")


def _print_code_d() -> None:
    print("""
  # Strategia D: Time-weighted priority
  # Identica a B ma moltiplica la priority per un fattore orario

  from datetime import datetime
  import pytz

  def _time_weight(signal_time_et_hour: int) -> float:
      if signal_time_et_hour >= 14:
          return 2.0
      if signal_time_et_hour >= 11:
          return 1.5
      return 1.0

  et_hour = opportunity.pattern_timestamp.astimezone(
      pytz.timezone("America/New_York")
  ).hour

  new_priority = _compute_priority(opportunity, settings) * _time_weight(et_hour)

  # Resto identico a Strategy B, usando new_priority e comparando con
  # entry_priority_timed (salvato con time_weight al momento dell'esecuzione)
""")


def _print_code_e() -> None:
    print("""
  # Strategia E: Slot separation 1h (3 slot) + 5m (2 slot)
  # 1h puo' usare slot 5m se i suoi 3 sono pieni e i 5m sono liberi
  # 5m NON puo' usare slot 1h

  SLOTS_1H = 3
  SLOTS_5M = 2

  pos_1h = [p for p in open_positions if p.get("timeframe") == "1h"]
  pos_5m = [p for p in open_positions if p.get("timeframe") == "5m"]
  # Slot 5m usati da 1h in prestito
  pos_1h_borrowed = [p for p in pos_1h if p.get("slot_type") == "borrowed"]

  n_5m_used = len(pos_5m) + len(pos_1h_borrowed)  # slot 5m occupati (5m + 1h borrowed)

  if opportunity.timeframe == "1h":
      if len(pos_1h) < SLOTS_1H:
          order_metadata["slot_type"] = "own"
          # procedi normalmente
      elif n_5m_used < SLOTS_5M:
          order_metadata["slot_type"] = "borrowed"
          logger.info(f"1h trade {opportunity.symbol} usa slot 5m in prestito")
          # procedi normalmente
      else:
          return {"status": "skipped",
                  "reason": f"Tutti e 5 gli slot pieni: {len(pos_1h)} pos 1h + {n_5m_used} slot 5m occupati"}

  elif opportunity.timeframe == "5m":
      n_5m_free = SLOTS_5M - n_5m_used
      if n_5m_free > 0:
          order_metadata["slot_type"] = "5m"
          # procedi normalmente
      else:
          return {"status": "skipped",
                  "reason": f"2 slot 5m pieni (usati: {n_5m_used}/2) — 5m non puo' usare slot 1h"}
""")


if __name__ == "__main__":
    main()

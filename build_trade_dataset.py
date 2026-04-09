#!/usr/bin/env python3
"""
Costruisce un dataset ML (CSV + meta JSON) da CandlePattern nel DB PostgreSQL.

Ogni riga = un segnale (pattern) con feature al momento del segnale e outcome forward.
Richiede: backend configurato (.env con DATABASE_URL / postgres_*), eseguire da root repo:

  cd backend && set PYTHONPATH=. && cd .. && python build_trade_dataset.py

oppure (PowerShell):

  $env:PYTHONPATH="c:\\...\\intraday-market-screener\\backend"; python build_trade_dataset.py

Assunzioni principali (vedi anche trade_dataset_v1_meta.json["assumptions"]):
- pattern_strength in DB come ``CandlePattern.pattern_strength``; soglia default ``SIGNAL_MIN_STRENGTH`` (0.70), allineata al validator v4.2.
- Universo simboli: default = scheduler Yahoo 1h o Binance 1h (``trade_plan_variant_constants``), coerente con live. Usa ``--no-symbol-filter`` per tutti i simboli nel DB.
- ``regime_spy`` = etichetta giornaliera SPY/BTC da ``RegimeFilter.get_regime_label`` (bullish/bearish/neutral),
  mappata su bull/bear/neutral per il CSV.
- ``symbol_group``: mappa euristica su ticker (nessuna tabella dedicata nel progetto); assente → "unknown".
- Outcome controfattuale (non eseguito): entry = open della prima candela dopo il segnale; stop/TP assoluti
  dal ``TradePlanV1`` generato come in produzione (stesso motore di ``build_trade_plan_v1_for_stored_pattern``).
- WR v4.2 vs script: stesso motore simulazione; allinea **periodo** (``--date-from`` / ``--date-to``) e
  **ordinamento**: con ``--pattern-timestamp-order asc`` (default API) e ``--pattern-row-limit N`` si
  selezionano i **N segnali più vecchi** tra i filtri; con ``desc`` i **N più recenti**. Dopo la query,
  righe e simulazione sono ordinate cronologicamente per il compounding.
- Esempio IS tipo cutoff 2025-01-01: ``--date-to 2025-01-01`` (e eventualmente ``--date-from ...``).
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import calendar as _calendar
import csv
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# Path backend (app.*)
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from tqdm import tqdm

from app.core.trade_plan_variant_constants import (
    BACKTEST_TOTAL_COST_RATE_DEFAULT,
    SCHEDULER_SYMBOLS_BINANCE_1H,
    SCHEDULER_SYMBOLS_YAHOO_1H,
    SIGNAL_MIN_STRENGTH,
)
from app.db.session import AsyncSessionLocal
from app.services.simulation_service import SIMULATION_PATTERN_HARD_CAP
from app.models.candle import Candle
from app.models.candle_context import CandleContext
from app.models.candle_feature import CandleFeature
from app.models.candle_indicator import CandleIndicator
from app.models.candle_pattern import CandlePattern
from app.schemas.backtest import PatternBacktestAggregateRow
from app.services.backtest_simulation import run_backtest_simulation
from app.services.pattern_backtest import pattern_quality_lookup_by_name_tf
from app.services.regime_filter_service import load_regime_filter, normalize_regime_variant
from app.services.trade_plan_backtest import (
    MAX_BARS_AFTER_ENTRY,
    _cost_r,
    _d,
    _entry_scan_start_idx,
    _eligible_plan,
    _find_entry_bar,
    _simulate_long_after_entry,
    _simulate_short_after_entry,
    build_trade_plan_v1_for_stored_pattern,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("build_trade_dataset")

OUTPUT_CSV = _ROOT / "trade_dataset_v1.csv"
OUTPUT_META = _ROOT / "trade_dataset_v1_meta.json"

# Mappa euristica ticker → gruppo (universo v4.2 completo)
_SYMBOL_GROUP_HINTS: list[tuple[str, str]] = [
    # Tech / Mega-cap
    ("GOOGL", "tech"), ("GOOG", "tech"),
    ("META", "tech"),
    ("AMZN", "tech"),
    ("MSFT", "tech"),
    ("AAPL", "tech"),
    ("NFLX", "tech"),
    ("SHOP", "tech"),
    ("DELL", "tech"),
    ("HPE", "tech"),
    # Semis
    ("NVDA", "semis"),
    ("AMD", "semis"),
    ("SMCI", "semis"),
    # Fintech / Brokers
    ("COIN", "crypto_fintech"),
    ("HOOD", "crypto_fintech"),
    ("SCHW", "broker"),
    # Crypto treasury / proxy
    ("MSTR", "crypto_proxy"),
    # Software / SaaS
    ("ZS", "saas"),
    ("NET", "saas"),
    ("MDB", "saas"),
    ("PLTR", "saas"),
    # Biotech / Pharma
    ("NVO", "biotech"),
    ("LLY", "biotech"),
    ("MRNA", "biotech"),
    ("RXRX", "biotech"),
    ("CELH", "biotech"),
    # EV / Mobility
    ("TSLA", "ev_mobility"),
    # Space / Defense / Energy
    ("ACHR", "space_defense"),
    ("ASTS", "space_defense"),
    ("JOBY", "space_defense"),
    ("RKLB", "space_defense"),
    # Nuclear / Energy
    ("NNE", "nuclear_energy"),
    ("OKLO", "nuclear_energy"),
    ("SMR", "nuclear_energy"),
    ("WULF", "crypto_mining"),
    ("APLD", "crypto_mining"),
    # Consumer
    ("NKE", "consumer"),
    ("TGT", "consumer"),
    ("WMT", "consumer"),
    # Commodities
    ("NEM", "commodities"),
    # Gaming / Metaverse
    ("RBLX", "gaming"),
    ("SOFI", "fintech"),
    # ETF / Index (SPY)
    ("SPY", "etf_index"),
    ("QQQ", "etf_index"),
    ("IWM", "etf_index"),
    # Crypto (Binance)
    ("BTC", "crypto"),
    ("ETH", "crypto"),
    ("SOL", "crypto"),
    ("WLD", "crypto"),
    ("DOGE", "crypto"),
    ("ADA", "crypto"),
    ("MATIC", "crypto"),
]


def symbol_group_for(ticker: str) -> str:
    t = (ticker or "").upper().replace("/USDT", "").replace("/USD", "")
    for prefix, grp in _SYMBOL_GROUP_HINTS:
        if t.startswith(prefix):
            return grp
    return "unknown"


def default_symbols_for_provider(provider: str) -> list[str]:
    """Universo operativo v4.2 / scheduler (stesso ordine delle costanti backend)."""
    p = (provider or "").strip().lower()
    if p == "yahoo_finance":
        return [sym for sym, tf in SCHEDULER_SYMBOLS_YAHOO_1H if tf == "1h"]
    if p == "binance":
        return [sym for sym, tf in SCHEDULER_SYMBOLS_BINANCE_1H if tf == "1h"]
    return []


def _utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _direction_long_short(pat_dir: str) -> str:
    d = (pat_dir or "").strip().lower()
    if d in ("bearish", "short", "sell", "bear"):
        return "short"
    return "long"


def _regime_spy_label(raw: str) -> str:
    x = (raw or "").lower()
    if x == "bullish":
        return "bull"
    if x == "bearish":
        return "bear"
    return "neutral"


def _ctx_raw(raw: str | None) -> str | None:
    """
    Passa il valore raw di CandleContext al CSV senza normalizzazione.

    I valori nel DB sono (da context_extraction.py):
    - market_regime:     "trend" | "range"
    - volatility_regime: "high"  | "normal" | "low"
    - candle_expansion:  "expansion" | "normal" | "compression"
    - direction_bias:    "bullish" | "bearish" | "neutral"

    Questi sono gli stessi valori usati da screener_scoring.py. Alterarli qui
    creerebbe una discrepanza tra dataset e sistema live.
    """
    return raw if raw else None


def _candle_body_metrics(candle) -> tuple[float | None, float | None, float | None]:
    """
    Ritorna (body_pct, upper_wick_pct, lower_wick_pct) normalizzati su (high-low).
    Tutti 0-1; None se high==low (doji assoluto).
    """
    try:
        hi = float(candle.high)
        lo = float(candle.low)
        op = float(candle.open)
        cl = float(candle.close)
        rng = hi - lo
        if rng <= 0:
            return None, None, None
        body = abs(cl - op) / rng
        upper = (hi - max(op, cl)) / rng
        lower = (min(op, cl) - lo) / rng
        return round(body, 6), round(upper, 6), round(lower, 6)
    except Exception:
        return None, None, None


# ─────────────────────────────────────────────────────────────────────────────
# Tranche A — Feature esterne: VIX, Earnings, Calendario, FOMC
# ─────────────────────────────────────────────────────────────────────────────

_NO_EARNINGS_SYMBOLS: frozenset[str] = frozenset({
    "SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLK", "XLF", "XLE", "XLV",
    "XLI", "XLB", "XLP", "XLU", "XLRE", "VXX", "UVXY",
})
_CRYPTO_PREFIXES: tuple[str, ...] = (
    "BTC", "ETH", "SOL", "WLD", "DOGE", "ADA", "MATIC", "BNB",
    "XRP", "AVAX", "LINK", "UNI", "LTC", "ATOM", "ALGO", "DOT",
)


def _is_no_earnings_symbol(sym: str) -> bool:
    s = sym.upper().replace("/USDT", "").replace("/USD", "").replace("/BTC", "")
    if s in _NO_EARNINGS_SYMBOLS:
        return True
    return any(s.startswith(p) for p in _CRYPTO_PREFIXES)


async def fetch_vix_history(
    dt_from: datetime | None,
    dt_to: datetime | None,
) -> dict[str, float]:
    """
    Scarica storia VIX (^VIX) via yfinance.
    Restituisce {YYYY-MM-DD: close_price}.
    Finestra estesa di 365+30 g per calcolare il percentile 1y anche sul primo segnale.
    """
    try:
        import yfinance as yf  # noqa: PLC0415
        start = (
            (dt_from - timedelta(days=365 + 30)).strftime("%Y-%m-%d")
            if dt_from
            else "2021-01-01"
        )
        end = (
            (dt_to + timedelta(days=2)).strftime("%Y-%m-%d")
            if dt_to
            else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )

        def _download() -> dict[str, float]:
            df = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=False)
            if df is None or df.empty:
                return {}
            # yfinance >= 0.2.x restituisce MultiIndex (Price, Ticker) con un solo ticker
            if hasattr(df.columns, "levels"):
                for label in ("Adj Close", "Close"):
                    if (label, "^VIX") in df.columns:
                        ser = df[(label, "^VIX")]
                        break
                else:
                    ser = df.iloc[:, 0]
            else:
                close_col = next(
                    (c for c in ("Adj Close", "Close") if c in df.columns),
                    df.columns[0],
                )
                ser = df[close_col]
            out: dict[str, float] = {}
            for idx, val in zip(df.index, ser):
                try:
                    out[idx.strftime("%Y-%m-%d")] = float(val)
                except Exception:
                    continue
            return out

        result = await asyncio.to_thread(_download)
        logger.info("VIX history: %d righe (%s … %s)", len(result), start, end)
        return result
    except Exception as exc:
        logger.warning("fetch_vix_history: %s — VIX features saranno None.", exc)
        return {}


def _vix_lookup(vix_history: dict[str, float], signal_dt: datetime) -> float | None:
    if not vix_history:
        return None
    dates = sorted(vix_history.keys())
    target = signal_dt.strftime("%Y-%m-%d")
    idx = bisect.bisect_right(dates, target) - 1
    if idx < 0:
        return None
    found = dates[idx]
    if (datetime.fromisoformat(target) - datetime.fromisoformat(found)).days > 5:
        return None
    return vix_history[found]


def _vix_percentile_1y(vix_history: dict[str, float], signal_dt: datetime) -> float | None:
    if not vix_history:
        return None
    dates = sorted(vix_history.keys())
    target = signal_dt.strftime("%Y-%m-%d")
    idx = bisect.bisect_right(dates, target) - 1
    if idx < 30:
        return None
    window = dates[max(0, idx - 252) : idx + 1]
    current = vix_history[dates[idx]]
    vals = [vix_history[d] for d in window]
    return round(sum(1 for v in vals if v <= current) / len(vals), 4)


def _vix_regime(vix_val: float | None) -> str | None:
    if vix_val is None:
        return None
    if vix_val < 15:
        return "low"
    if vix_val < 25:
        return "normal"
    if vix_val < 35:
        return "elevated"
    return "high"


async def fetch_earnings_calendar(symbols: list[str]) -> dict[str, list[date]]:
    """
    Scarica il calendario earnings per ogni simbolo valido via yfinance.
    Restituisce {symbol_upper: [sorted list of date]}.
    ETF e token crypto vengono saltati (_is_no_earnings_symbol).
    """
    result: dict[str, list[date]] = {}
    filtered = [s for s in symbols if not _is_no_earnings_symbol(s)]
    if not filtered:
        return result

    async def _fetch_one(sym: str) -> tuple[str, list[date]]:
        try:
            import yfinance as yf  # noqa: PLC0415

            ticker = yf.Ticker(sym)

            def _get_dates() -> list[date]:
                try:
                    df = ticker.get_earnings_dates(limit=40)
                except AttributeError:
                    df = ticker.earnings_dates
                if df is None or len(df) == 0:
                    return []
                out: list[date] = []
                for idx in df.index:
                    try:
                        dt_val = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else datetime.fromisoformat(str(idx)[:10])
                        out.append(dt_val.date())
                    except Exception:
                        continue
                return sorted(set(out))

            dates = await asyncio.to_thread(_get_dates)
            return sym.upper(), dates
        except Exception as exc:
            logger.debug("earnings %s: %s", sym, exc)
            return sym.upper(), []

    items = await asyncio.gather(*[_fetch_one(s) for s in filtered], return_exceptions=True)
    for item in items:
        if isinstance(item, tuple):
            sym, dates = item
            if dates:
                result[sym] = dates
    logger.info("Earnings calendar: %d/%d simboli con dati", len(result), len(filtered))
    return result


def _earnings_proximity(
    earnings_cal: dict[str, list[date]],
    symbol: str,
    signal_dt: datetime,
) -> tuple[int | None, int | None, int]:
    """
    Restituisce (days_to_earnings, days_from_earnings, in_earnings_window).
    - days_to_earnings  : giorni al prossimo earnings (None se > 90g o non disponibile)
    - days_from_earnings: giorni dall'ultimo earnings  (None se > 90g o non disponibile)
    - in_earnings_window: 1 se segnale entro 5g prima o 2g dopo un earnings, altrimenti 0
    """
    sym = symbol.upper().replace("/USDT", "").replace("/USD", "")
    dates = earnings_cal.get(sym, [])
    if not dates:
        return None, None, 0
    sig = signal_dt.date()
    future = [d for d in dates if d > sig]
    past = [d for d in dates if d <= sig]
    days_to = (min(future) - sig).days if future else None
    if days_to is not None and days_to > 90:
        days_to = None
    days_from = (sig - max(past)).days if past else None
    if days_from is not None and days_from > 90:
        days_from = None
    in_window = int(
        (days_to is not None and days_to <= 5)
        or (days_from is not None and days_from <= 2)
    )
    return days_to, days_from, in_window


# FOMC announcement dates (ultimo giorno del meeting, quando viene pubblicata la decisione)
_FOMC_DATES: list[date] = sorted([
    date(2022, 3, 16), date(2022, 5, 4), date(2022, 6, 15), date(2022, 7, 27),
    date(2022, 9, 21), date(2022, 11, 2), date(2022, 12, 14),
    date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3), date(2023, 6, 14),
    date(2023, 7, 26), date(2023, 9, 20), date(2023, 11, 1), date(2023, 12, 13),
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12),
    date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18),
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7), date(2025, 6, 18),
    date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10),
])


def _days_to_fomc(signal_dt: datetime) -> int | None:
    """Giorni al prossimo FOMC (0 = giorno FOMC, None se > 60g o nessuna data futura)."""
    sig = signal_dt.date()
    future = [d for d in _FOMC_DATES if d >= sig]
    if not future:
        return None
    delta = (future[0] - sig).days
    return delta if delta <= 60 else None


def _third_friday(y: int, m: int) -> date:
    first = date(y, m, 1)
    first_friday = first + timedelta(days=(4 - first.weekday()) % 7)
    return first_friday + timedelta(weeks=2)


def _is_opex_week(d: date) -> int:
    opex = _third_friday(d.year, d.month)
    return int(d.isocalendar()[1] == opex.isocalendar()[1])


def _calendar_features(signal_dt: datetime) -> dict[str, object]:
    d = signal_dt.date()
    mo = d.month
    last_day = _calendar.monthrange(d.year, mo)[1]
    return {
        "month_of_year": mo,
        "week_of_year": int(d.isocalendar()[1]),
        "is_opex_week": _is_opex_week(d),
        "is_quarter_start": int(mo in (1, 4, 7, 10) and d.day <= 14),
        "is_quarter_end": int(mo in (3, 6, 9, 12) and d.day >= last_day - 13),
    }


# ─────────────────────────────────────────────────────────────────────────────


def session_bucket_utc(hour_utc: int) -> str:
    if hour_utc < 8:
        return "open"
    if hour_utc < 16:
        return "midday"
    return "close"


def _float_or_none(x: object) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _dec_or_none(x: object) -> Decimal | None:
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except Exception:
        return None


def map_skip_to_bucket(reason: str | None, *, strength: float, alert_min_strength: float) -> str | None:
    """Raggruppa motivi audit motore in categorie compatte per ML."""
    if reason is None:
        return None
    if reason in ("capital_constraint", "regime_filter"):
        return reason
    if reason == "trade_plan_not_triggered":
        return "below_quality"
    if reason == "not_in_simulation" and strength < alert_min_strength:
        return "below_strength"
    if reason in ("hour_filter", "allowed_hours_utc", "cooldown", "symbol_filter", "no_ohlc_data", "equity_floor"):
        return "other"
    return "other"


def verify_no_leakage(
    *,
    signal_ts: datetime,
    feature_ts: datetime | None,
    entry_ts: datetime | None,
    outcome_ts_max: datetime | None,
) -> bool:
    """Controlli statici anti-leakage (feature ≤ segnale; outcome > entry)."""
    s = _utc(signal_ts)
    if feature_ts is not None and _utc(feature_ts) > s:
        return False
    if entry_ts is not None and _utc(entry_ts) <= s:
        return False
    if outcome_ts_max is not None and entry_ts is not None and _utc(outcome_ts_max) < _utc(entry_ts):
        return False
    return True


class TradeDatasetLeakageChecks:
    """Wrapper esplicito richiesto per validazione leakage (feature vs segnale vs outcome)."""

    @staticmethod
    def verify_no_leakage(
        *,
        signal_ts: datetime,
        feature_ts: datetime | None,
        entry_ts: datetime | None,
        outcome_ts_max: datetime | None,
    ) -> bool:
        return verify_no_leakage(
            signal_ts=signal_ts,
            feature_ts=feature_ts,
            entry_ts=entry_ts,
            outcome_ts_max=outcome_ts_max,
        )


def _pnl_close_long(
    candles: list[Candle],
    exit_idx: int,
    entry: Decimal,
    stop: Decimal,
    cost_rate: float,
) -> float | None:
    if exit_idx >= len(candles):
        return None
    risk = entry - stop
    if risk <= 0:
        return None
    cl = _d(candles[exit_idx].close)
    cr = _cost_r(entry, risk, cost_rate)
    return float((cl - entry) / risk) - cr


def _pnl_close_short(
    candles: list[Candle],
    exit_idx: int,
    entry: Decimal,
    stop: Decimal,
    cost_rate: float,
) -> float | None:
    if exit_idx >= len(candles):
        return None
    risk = stop - entry
    if risk <= 0:
        return None
    cl = _d(candles[exit_idx].close)
    cr = _cost_r(entry, risk, cost_rate)
    return float((entry - cl) / risk) - cr


def mfe_mae_r_long(
    candles: list[Candle],
    entry_idx: int,
    entry: Decimal,
    stop: Decimal,
    *,
    max_bars: int,
) -> tuple[float | None, float | None]:
    risk = entry - stop
    if risk <= 0:
        return None, None
    end = min(entry_idx + max_bars, len(candles))
    mfe = 0.0
    mae = 0.0
    fe = float(entry)
    fr = float(risk)
    for k in range(entry_idx, end):
        c = candles[k]
        hi, lo = float(c.high), float(c.low)
        mfe = max(mfe, (hi - fe) / fr)
        mae = max(mae, (fe - lo) / fr)
    return mfe, mae


def mfe_mae_r_short(
    candles: list[Candle],
    entry_idx: int,
    entry: Decimal,
    stop: Decimal,
    *,
    max_bars: int,
) -> tuple[float | None, float | None]:
    risk = stop - entry
    if risk <= 0:
        return None, None
    end = min(entry_idx + max_bars, len(candles))
    mfe = 0.0
    mae = 0.0
    fe = float(entry)
    fr = float(risk)
    for k in range(entry_idx, end):
        c = candles[k]
        hi, lo = float(c.high), float(c.low)
        mfe = max(mfe, (fe - lo) / fr)
        mae = max(mae, (hi - fe) / fr)
    return mfe, mae


def outcome_bundle(
    *,
    candles: list[Candle],
    pattern_idx: int,
    plan,
    cost_rate: float,
    counterfactual_open_entry: bool,
) -> dict[str, object | None]:
    """
    Calcola outcome forward. Se counterfactual_open_entry=True, entry = open barra successiva al segnale
    e stop/tp assoluti dal plan; altrimenti usa il motore standard (entry da piano / touch).
    """
    empty = {
        "pnl_final_r": None,
        "tp1_hit": None,
        "tp2_hit": None,
        "stop_hit": None,
        "bars_to_exit": None,
        "mfe_r": None,
        "mae_r": None,
        "pnl_4h_r": None,
        "pnl_12h_r": None,
        "pnl_24h_r": None,
        "pnl_48h_r": None,
        "early_exit_better": None,
        "entry_timestamp": None,
    }
    if not _eligible_plan(plan):
        return empty
    assert plan.entry_price is not None and plan.stop_loss is not None
    assert plan.take_profit_1 is not None and plan.take_profit_2 is not None

    entry_px = _d(plan.entry_price)
    stop = _d(plan.stop_loss)
    tp1 = _d(plan.take_profit_1)
    tp2 = _d(plan.take_profit_2)

    if counterfactual_open_entry:
        if pattern_idx + 1 >= len(candles):
            return empty
        entry_bar = pattern_idx + 1
        entry_px = _d(candles[entry_bar].open)
    else:
        scan_from = _entry_scan_start_idx(pattern_idx, plan.entry_strategy)
        eb = _find_entry_bar(candles, scan_from, entry_px, 20)
        if eb is None:
            return empty
        entry_bar = eb

    entry_ts = candles[entry_bar].timestamp
    direction = plan.trade_direction

    if direction == "long":
        out_l, pnl_final_r, exit_k = _simulate_long_after_entry(
            candles,
            entry_bar,
            entry=entry_px,
            stop=stop,
            tp1=tp1,
            tp2=tp2,
            max_bars=MAX_BARS_AFTER_ENTRY,
            cost_rate=cost_rate,
        )
        t1 = out_l in ("tp1", "tp2")
        t2 = out_l == "tp2"
        st = out_l == "stop"
        mfe, mae = mfe_mae_r_long(
            candles,
            entry_bar,
            entry_px,
            stop,
            max_bars=min(48, MAX_BARS_AFTER_ENTRY),
        )

        def _pnl_h(nbars: int) -> float | None:
            j = entry_bar + nbars
            return _pnl_close_long(candles, j, entry_px, stop, cost_rate)

    elif direction == "short":
        out_s, pnl_final_r, exit_k = _simulate_short_after_entry(
            candles,
            entry_bar,
            entry=entry_px,
            stop=stop,
            tp1=tp1,
            tp2=tp2,
            max_bars=MAX_BARS_AFTER_ENTRY,
            cost_rate=cost_rate,
        )
        t1 = out_s in ("tp1", "tp2")
        t2 = out_s == "tp2"
        st = out_s == "stop"
        mfe, mae = mfe_mae_r_short(
            candles,
            entry_bar,
            entry_px,
            stop,
            max_bars=min(48, MAX_BARS_AFTER_ENTRY),
        )

        def _pnl_h(nbars: int) -> float | None:
            j = entry_bar + nbars
            return _pnl_close_short(candles, j, entry_px, stop, cost_rate)

    else:
        return empty

    bars_to_exit = int(exit_k - entry_bar + 1) if exit_k >= entry_bar else None
    p4 = _pnl_h(4)
    p12 = _pnl_h(12)
    p24 = _pnl_h(24)
    p48 = _pnl_h(48)
    early = None
    if p4 is not None and pnl_final_r is not None:
        early = bool(p4 > pnl_final_r)

    return {
        "pnl_final_r": pnl_final_r,
        "tp1_hit": t1,
        "tp2_hit": t2,
        "stop_hit": st,
        "bars_to_exit": bars_to_exit,
        "mfe_r": mfe,
        "mae_r": mae,
        "pnl_4h_r": p4,
        "pnl_12h_r": p12,
        "pnl_24h_r": p24,
        "pnl_48h_r": p48,
        "early_exit_better": early,
        "entry_timestamp": entry_ts.isoformat() if entry_ts else None,
    }


async def load_patterns(
    session: AsyncSession,
    *,
    min_strength: float,
    provider: str,
    timeframe: str,
    dt_from: datetime | None,
    dt_to: datetime | None,
    pattern_names: list[str] | None,
    row_limit: int,
    timestamp_order: str = "asc",
    include_symbols: list[str] | None = None,
) -> list[tuple[CandlePattern, Candle, CandleContext, CandleIndicator | None]]:
    stmt = (
        select(CandlePattern, Candle, CandleContext, CandleIndicator)
        .join(CandleFeature, CandlePattern.candle_feature_id == CandleFeature.id)
        .join(Candle, CandleFeature.candle_id == Candle.id)
        .join(CandleContext, CandleContext.candle_feature_id == CandleFeature.id)
        .outerjoin(CandleIndicator, CandleIndicator.candle_id == Candle.id)
        .where(
            CandlePattern.provider == provider,
            CandlePattern.timeframe == timeframe,
            CandlePattern.pattern_strength >= min_strength,
        )
    )
    if include_symbols:
        stmt = stmt.where(CandlePattern.symbol.in_(include_symbols))
    if pattern_names:
        stmt = stmt.where(CandlePattern.pattern_name.in_(pattern_names))
    if dt_from is not None:
        stmt = stmt.where(CandlePattern.timestamp >= dt_from)
    if dt_to is not None:
        stmt = stmt.where(CandlePattern.timestamp <= dt_to)
    if timestamp_order == "desc":
        stmt = stmt.order_by(CandlePattern.timestamp.desc(), CandlePattern.id.desc())
    else:
        stmt = stmt.order_by(CandlePattern.timestamp.asc(), CandlePattern.id.asc())
    if row_limit <= 0:
        eff_lim = SIMULATION_PATTERN_HARD_CAP
    else:
        eff_lim = min(row_limit, SIMULATION_PATTERN_HARD_CAP)
    stmt = stmt.limit(eff_lim)
    r = await session.execute(stmt)
    out = list(r.all())
    out.sort(key=lambda row: (_utc(row[0].timestamp), row[0].id))
    return out


async def main_async() -> int:
    ap = argparse.ArgumentParser(description="Dataset ML trade signals v1")
    ap.add_argument("--provider", default="yahoo_finance")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument(
        "--min-strength",
        type=float,
        default=SIGNAL_MIN_STRENGTH,
        help=(
            f"Include pattern con strength >= soglia (default {SIGNAL_MIN_STRENGTH}, "
            "allineato al validator v4.2)"
        ),
    )
    ap.add_argument(
        "--symbols",
        default=None,
        metavar="LIST",
        help=(
            "Lista simboli separati da virgola (es. GOOGL,TSLA,SPY). "
            "Default: universo scheduler per --provider (vedi trade_plan_variant_constants)."
        ),
    )
    ap.add_argument(
        "--no-symbol-filter",
        action="store_true",
        help="Non filtrare per simbolo: include tutti i CandlePattern che passano gli altri filtri (comportamento precedente).",
    )
    ap.add_argument("--date-from", default=None, help="YYYY-MM-DD UTC")
    ap.add_argument("--date-to", default=None, help="YYYY-MM-DD UTC")
    ap.add_argument("--initial-capital", type=float, default=10_000.0)
    ap.add_argument("--risk-pct", type=float, default=1.0)
    ap.add_argument("--cost-rate", type=float, default=BACKTEST_TOTAL_COST_RATE_DEFAULT)
    ap.add_argument("--max-simultaneous", type=int, default=3)
    ap.add_argument("--use-regime-filter", action="store_true", default=True)
    ap.add_argument("--no-regime-filter", action="store_true")
    ap.add_argument("--regime-variant", default="ema50")
    ap.add_argument("--track-capital", action="store_true", default=True)
    ap.add_argument("--no-track-capital", action="store_true")
    ap.add_argument("--use-temporal-quality", action="store_true", default=True)
    ap.add_argument("--no-temporal-quality", action="store_true")
    ap.add_argument(
        "--pattern-row-limit",
        type=int,
        default=50_000,
        help=(
            "Max righe CandlePattern dopo i filtri. 0 = fino a "
            f"{SIMULATION_PATTERN_HARD_CAP} (stesso hard cap della simulazione). "
            "ATTENZIONE: con order=asc (default) e limit N si prendono i N segnali più VECCHI; "
            "con --pattern-timestamp-order desc i N più RECENTI."
        ),
    )
    ap.add_argument(
        "--pattern-timestamp-order",
        choices=["asc", "desc"],
        default="asc",
        help=(
            "Ordine SQL su (timestamp, id): asc = cronologico dal passato (come GET /backtest/simulation); "
            "desc = più recenti prima — stesso motore della simulazione se passi lo stesso valore lì."
        ),
    )
    ap.add_argument("--alert-min-strength", type=float, default=0.70, help="Soglia per bucket below_strength")
    ap.add_argument("--expected-wr", type=float, default=59.0, help="WR atteso backtest v4.2 (sanity check)")
    ap.add_argument("--batch-size", type=int, default=100)
    ap.add_argument("--overwrite", action="store_true", help="Sovrascrivi CSV senza prompt")
    ap.add_argument(
        "--quality-legacy-global",
        action="store_true",
        help=(
            "Usa un solo pattern_quality globale (senza dt_to). "
            "Default: lookup temporale per timestamp segnale (anti-leakage, come use_temporal_quality)."
        ),
    )
    ap.add_argument(
        "--no-external-data",
        action="store_true",
        help=(
            "Salta il download di VIX e Earnings Calendar (Tranche A). "
            "Utile per velocità o quando yfinance non è disponibile; le feature esterne saranno None."
        ),
    )
    args = ap.parse_args()

    if args.no_symbol_filter:
        include_symbols_eff: list[str] | None = None
        symbol_filter_mode = "none"
    elif args.symbols is not None:
        include_symbols_eff = [s.strip() for s in args.symbols.split(",") if s.strip()]
        symbol_filter_mode = "explicit"
    else:
        include_symbols_eff = default_symbols_for_provider(args.provider)
        symbol_filter_mode = "scheduler_default"

    if args.symbols is not None and args.no_symbol_filter:
        print("ERRORE: non usare --symbols insieme a --no-symbol-filter.")
        return 1
    if args.symbols is not None and not [s for s in args.symbols.split(",") if s.strip()]:
        print("ERRORE: --symbols vuoto; ometti l'opzione o specifica almeno un ticker.")
        return 1

    use_regime = args.use_regime_filter and not args.no_regime_filter
    track_capital = args.track_capital and not args.no_track_capital
    use_temporal_q = args.use_temporal_quality and not args.no_temporal_quality

    if OUTPUT_CSV.exists() and not args.overwrite:
        ans = input(f"File {OUTPUT_CSV} esiste. Sovrascrivere? [y/N]: ").strip().lower()
        if ans != "y":
            print("Uscita.")
            return 1

    dt_from = None
    dt_to = None
    if args.date_from:
        dt_from = datetime.fromisoformat(args.date_from[:10]).replace(tzinfo=timezone.utc)
    if args.date_to:
        d = datetime.fromisoformat(args.date_to[:10])
        dt_to = d.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)

    async with AsyncSessionLocal() as session:
        sim = await run_backtest_simulation(
            session,
            provider=args.provider,
            timeframe=args.timeframe,
            pattern_names=[],
            initial_capital=args.initial_capital,
            risk_per_trade_pct=args.risk_pct,
            cost_rate=args.cost_rate,
            pattern_row_limit=args.pattern_row_limit,
            include_trades=True,
            max_simultaneous=args.max_simultaneous,
            dt_from=dt_from,
            dt_to=dt_to,
            use_regime_filter=use_regime,
            track_capital=track_capital,
            use_temporal_quality=use_temporal_q,
            regime_variant=normalize_regime_variant(args.regime_variant),
            min_strength=args.min_strength,
            include_symbols=include_symbols_eff,
            include_pattern_audit=True,
            pattern_timestamp_order=args.pattern_timestamp_order,
        )

        audit_by_id: dict[int, object] = {a.candle_pattern_id: a for a in sim.pattern_simulation_audit}
        trade_pnl_by_id: dict[int, float] = {}
        for t in sim.trades:
            if t.candle_pattern_id is not None:
                trade_pnl_by_id[t.candle_pattern_id] = t.pnl_r

        pq_temporal_cache: dict[str, dict[tuple[str, str], PatternBacktestAggregateRow]] = {}
        pq_lookup_global: dict[tuple[str, str], PatternBacktestAggregateRow] | None = None
        if args.quality_legacy_global:
            pq_lookup_global = await pattern_quality_lookup_by_name_tf(
                session,
                symbol=None,
                exchange=None,
                provider=args.provider,
                asset_type=None,
                timeframe=args.timeframe,
            )

        async def pq_lookup_for_signal(ts_signal: datetime) -> dict[tuple[str, str], PatternBacktestAggregateRow]:
            if args.quality_legacy_global:
                assert pq_lookup_global is not None
                return pq_lookup_global
            k = _utc(ts_signal).isoformat()
            if k not in pq_temporal_cache:
                pq_temporal_cache[k] = await pattern_quality_lookup_by_name_tf(
                    session,
                    symbol=None,
                    exchange=None,
                    provider=args.provider,
                    asset_type=None,
                    timeframe=args.timeframe,
                    dt_to=_utc(ts_signal),
                )
            return pq_temporal_cache[k]

        rf_prov = (
            "yahoo_finance"
            if (args.provider or "").strip().lower() == "yahoo_finance"
            else "binance"
        )
        regime_filter = await load_regime_filter(
            session,
            dt_from=dt_from,
            dt_to=dt_to,
            provider=rf_prov,
            variant=normalize_regime_variant(args.regime_variant),
        )

        # ── Tranche A: dati esterni (VIX + Earnings) ─────────────────────────
        if args.no_external_data:
            vix_history: dict[str, float] = {}
            earnings_cal: dict[str, list[date]] = {}
            logger.info("--no-external-data: feature VIX/Earnings saranno None.")
        else:
            logger.info("Download VIX history…")
            vix_history = await fetch_vix_history(dt_from, dt_to)
            ext_symbols = include_symbols_eff or []
            logger.info("Download Earnings calendar per %d simboli…", len(ext_symbols))
            earnings_cal = await fetch_earnings_calendar(ext_symbols)

        rows_db = await load_patterns(
            session,
            min_strength=args.min_strength,
            provider=args.provider,
            timeframe=args.timeframe,
            dt_from=dt_from,
            dt_to=dt_to,
            pattern_names=None,
            row_limit=args.pattern_row_limit,
            timestamp_order=args.pattern_timestamp_order,
            include_symbols=include_symbols_eff,
        )

        # Serie candele per (exchange, symbol, tf)
        series_keys: set[tuple[str, str, str]] = set()
        for pat, candle, ctx, _ind in rows_db:
            series_keys.add((pat.exchange, pat.symbol, pat.timeframe))

        or_parts = [
            and_(Candle.exchange == ex, Candle.symbol == sym, Candle.timeframe == tf) for ex, sym, tf in series_keys
        ]
        if not or_parts:
            print("Nessuna serie; esco.")
            return 1
        c_stmt = select(Candle).where(or_(*or_parts)).order_by(
            Candle.exchange,
            Candle.symbol,
            Candle.timeframe,
            Candle.timestamp.asc(),
        )
        all_candles = list((await session.execute(c_stmt)).scalars().all())
        by_series: dict[tuple[str, str, str], list[Candle]] = defaultdict(list)
        for c in all_candles:
            by_series[(c.exchange, c.symbol, c.timeframe)].append(c)
        id_to_index: dict[tuple[str, str, str], dict[int, int]] = {}
        for key, clist in by_series.items():
            id_to_index[key] = {c.id: i for i, c in enumerate(clist)}

        counts = Counter()
        for a in sim.pattern_simulation_audit:
            if a.executed:
                counts["eseguiti"] += 1
            else:
                r = a.skip_reason or ""
                if r == "capital_constraint":
                    counts["saltati_capitale"] += 1
                elif r == "regime_filter":
                    counts["saltati_regime"] += 1
                elif r in ("hour_filter", "allowed_hours_utc", "cooldown"):
                    counts["saltati_capitale"] += 1
                elif r == "trade_plan_not_triggered":
                    counts["saltati_piano"] += 1
                else:
                    counts["saltati_altro"] += 1

        fieldnames = [
            # ── Identificatori ──────────────────────────────────────────────
            "signal_id",
            "symbol",
            "symbol_group",
            "provider",
            "pattern_name",
            "direction",
            "timeframe",
            "signal_timestamp",
            "entry_timestamp",
            # ── Label esecuzione ────────────────────────────────────────────
            "was_executed",
            "skip_reason",
            "skip_reason_bucket",
            # ── Feature segnale (pattern) ───────────────────────────────────
            "strength",
            "quality_score",
            "has_quality_score",
            # ── Regime ──────────────────────────────────────────────────────
            "regime_spy",           # SPY/BTC daily: bull/bear/neutral
            "ctx_market_regime",    # regime locale della serie (candle_contexts)
            "ctx_volatility_regime",
            "ctx_candle_expansion",
            "ctx_direction_bias",
            # ── Momentum / Trend ────────────────────────────────────────────
            "rs_vs_spy",
            "rs_vs_spy_5",
            "rs_signal",
            "rsi_14",
            "price_vs_ema9_pct",
            "ema_20",
            "ema_50",
            # ── Volatilità ──────────────────────────────────────────────────
            "atr_14",
            "atr_pct",
            # ── Volume ──────────────────────────────────────────────────────
            "volume_ratio",
            "cvd_trend",
            "cvd_normalized",
            # ── Prezzi chiave ───────────────────────────────────────────────
            "price_vs_vwap_pct",
            "price_vs_or_high_pct",
            "price_vs_or_low_pct",
            # ── Struttura / Swing ────────────────────────────────────────────
            "dist_to_swing_high_pct",
            "dist_to_swing_low_pct",
            "price_position_in_range",
            "structural_range_pct",
            # ── Fibonacci ────────────────────────────────────────────────────
            "dist_to_fib_382_pct",
            "dist_to_fib_500_pct",
            "dist_to_fib_618_pct",
            # ── Fair Value Gap ────────────────────────────────────────────────
            "in_fvg_bullish",
            "in_fvg_bearish",
            "dist_to_fvg_pct",
            # ── Order Block ──────────────────────────────────────────────────
            "in_ob_bullish",
            "in_ob_bearish",
            "dist_to_ob_pct",
            "ob_strength",
            # ── Trade plan ───────────────────────────────────────────────────
            "stop_distance_pct",
            "rr_tp1",
            "rr_tp2",
            # ── Candle body / wick ────────────────────────────────────────────
            "candle_body_pct",
            "upper_wick_pct",
            "lower_wick_pct",
            # ── Temporali ───────────────────────────────────────────────────
            "hour_utc",
            "day_of_week",
            "session",
            "month_of_year",
            "week_of_year",
            "is_opex_week",
            "is_quarter_start",
            "is_quarter_end",
            # ── Macro / Volatilità sistemica (Tranche A) ─────────────────────
            "vix_close",
            "vix_percentile_1y",
            "vix_regime",
            "days_to_earnings",
            "days_from_earnings",
            "in_earnings_window",
            "days_to_fomc",
            # ── Portfolio state ──────────────────────────────────────────────
            "n_open_positions",
            "capital_available_pct",
            # ── Outcome / Label ──────────────────────────────────────────────
            "pnl_final_r",
            "tp1_hit",
            "tp2_hit",
            "stop_hit",
            "bars_to_exit",
            "mfe_r",
            "mae_r",
            "pnl_4h_r",
            "pnl_12h_r",
            "pnl_24h_r",
            "pnl_48h_r",
            "early_exit_better",
            # ── Qualità dataset ──────────────────────────────────────────────
            "leakage_ok",
        ]

        csv_rows: list[dict[str, object]] = []
        sample_executed: list[dict[str, object]] = []

        for i in tqdm(range(0, len(rows_db), args.batch_size), desc="batch"):
            chunk = rows_db[i : i + args.batch_size]
            for pat, candle, ctx, ind in chunk:
                try:
                    key_s = (pat.exchange, pat.symbol, pat.timeframe)
                    clist = by_series.get(key_s)
                    idx_map = id_to_index.get(key_s)
                    idx = idx_map.get(candle.id) if idx_map else None

                    audit = audit_by_id.get(pat.id)
                    was_ex = bool(audit and audit.executed)
                    skip_raw = None if was_ex else (audit.skip_reason if audit else "not_in_simulation")
                    strength_f = float(pat.pattern_strength)
                    bucket = map_skip_to_bucket(
                        skip_raw,
                        strength=strength_f,
                        alert_min_strength=args.alert_min_strength,
                    )

                    pq_lookup = await pq_lookup_for_signal(pat.timestamp)
                    pq = pq_lookup.get((pat.pattern_name, pat.timeframe))
                    quality = pq.pattern_quality_score if pq else None

                    if regime_filter is not None and regime_filter.has_data:
                        regime_raw = regime_filter.get_regime_label(pat.timestamp)
                    else:
                        regime_raw = "neutral"
                    regime_spy = _regime_spy_label(regime_raw)

                    close_px = _float_or_none(candle.close) or 0.0
                    # ── Indicatori tecnici ───────────────────────────────────
                    ema9 = _float_or_none(ind.ema_9 if ind else None)
                    ema20_pct = _float_or_none(ind.price_vs_ema20_pct) if ind else None
                    ema50_pct = _float_or_none(ind.price_vs_ema50_pct) if ind else None
                    ema9_pct = ((close_px - ema9) / ema9 * 100.0) if ema9 and ema9 != 0 else None
                    atr = _float_or_none(ind.atr_14) if ind else None
                    atr_pct = (atr / close_px * 100.0) if atr and close_px else None
                    volr = _float_or_none(ind.volume_ratio_vs_ma20) if ind else None
                    pvwap = _float_or_none(ind.price_vs_vwap_pct) if ind else None
                    rsi14 = _float_or_none(ind.rsi_14) if ind else None
                    rs_spy = _float_or_none(ind.rs_vs_spy) if ind else None
                    rs_spy_5 = _float_or_none(ind.rs_vs_spy_5) if ind else None
                    rs_sig = ind.rs_signal if ind else None
                    # ── CVD ──────────────────────────────────────────────────
                    cvd_trend_val = (ind.cvd_trend or None) if ind else None
                    cvd_norm = _float_or_none(ind.cvd_normalized) if ind else None
                    # ── Struttura / Swing ─────────────────────────────────────
                    d_sh = _float_or_none(ind.dist_to_swing_high_pct) if ind else None
                    d_sl = _float_or_none(ind.dist_to_swing_low_pct) if ind else None
                    ppr = _float_or_none(ind.price_position_in_range) if ind else None
                    srng = _float_or_none(ind.structural_range_pct) if ind else None
                    # ── Opening Range ─────────────────────────────────────────
                    por_hi = _float_or_none(ind.price_vs_or_high_pct) if ind else None
                    por_lo = _float_or_none(ind.price_vs_or_low_pct) if ind else None
                    # ── Fibonacci ─────────────────────────────────────────────
                    d_f382 = _float_or_none(ind.dist_to_fib_382_pct) if ind else None
                    d_f500 = _float_or_none(ind.dist_to_fib_500_pct) if ind else None
                    d_f618 = _float_or_none(ind.dist_to_fib_618_pct) if ind else None
                    # ── FVG ───────────────────────────────────────────────────
                    fvg_bull = int(bool(ind.in_fvg_bullish)) if ind else None
                    fvg_bear = int(bool(ind.in_fvg_bearish)) if ind else None
                    d_fvg = _float_or_none(ind.dist_to_fvg_pct) if ind else None
                    # ── Order Block ───────────────────────────────────────────
                    ob_bull = int(bool(ind.in_ob_bullish)) if ind else None
                    ob_bear = int(bool(ind.in_ob_bearish)) if ind else None
                    d_ob = _float_or_none(ind.dist_to_ob_pct) if ind else None
                    ob_str = _float_or_none(ind.ob_strength) if ind else None
                    # ── CandleContext (valori raw dal DB, coerenti con screener_scoring.py) ─
                    ctx_mkt_regime = _ctx_raw(ctx.market_regime if ctx else None)
                    ctx_vol = _ctx_raw(ctx.volatility_regime if ctx else None)
                    ctx_exp = _ctx_raw(ctx.candle_expansion if ctx else None)
                    ctx_bias = _ctx_raw(ctx.direction_bias if ctx else None)
                    # ── Candle body / wick ────────────────────────────────────
                    body_pct, uw_pct, lw_pct = _candle_body_metrics(candle)

                    # ── Tranche A: VIX, Earnings, Calendario, FOMC ───────────
                    ts_signal = _utc(pat.timestamp)
                    vix_val = _vix_lookup(vix_history, ts_signal)
                    vix_pct1y = _vix_percentile_1y(vix_history, ts_signal)
                    vix_reg = _vix_regime(vix_val)
                    days_to_earn, days_from_earn, in_earn_win = _earnings_proximity(
                        earnings_cal, pat.symbol, ts_signal
                    )
                    fomc_d = _days_to_fomc(ts_signal)
                    cal_f = _calendar_features(ts_signal)

                    plan = build_trade_plan_v1_for_stored_pattern(pat, candle, ctx, pq_lookup)
                    stop_d_pct = None
                    rr1 = None
                    rr2 = None
                    if (
                        plan.entry_price
                        and plan.stop_loss
                        and plan.take_profit_1
                        and plan.take_profit_2
                        and _eligible_plan(plan)
                    ):
                        ep = _d(plan.entry_price)
                        st = _d(plan.stop_loss)
                        t1 = _d(plan.take_profit_1)
                        t2 = _d(plan.take_profit_2)
                        if plan.trade_direction == "long":
                            risk = ep - st
                            if risk > 0 and ep > 0:
                                stop_d_pct = float(risk / ep) * 100.0
                                rr1 = float((t1 - ep) / risk)
                                rr2 = float((t2 - ep) / risk)
                        elif plan.trade_direction == "short":
                            risk = st - ep
                            if risk > 0 and ep > 0:
                                stop_d_pct = float(risk / ep) * 100.0
                                rr1 = float((ep - t1) / risk)
                                rr2 = float((ep - t2) / risk)

                    ts = ts_signal
                    hour_utc = ts.hour
                    dow = ts.weekday()
                    sess = session_bucket_utc(hour_utc)

                    n_open = audit.open_positions_at_signal if audit else 0
                    cap_pct = audit.capital_available_pct if audit else 0.0

                    pnl_sim = trade_pnl_by_id.get(pat.id) if was_ex else None
                    use_cf = not was_ex
                    ob: dict[str, object | None] = {}
                    if clist is not None and idx is not None:
                        ob = outcome_bundle(
                            candles=clist,
                            pattern_idx=idx,
                            plan=plan,
                            cost_rate=args.cost_rate,
                            counterfactual_open_entry=use_cf,
                        )
                    else:
                        ob = {}

                    if was_ex and pnl_sim is not None:
                        ob["pnl_final_r"] = pnl_sim

                    entry_ts = ob.get("entry_timestamp")
                    entry_dt = None
                    if isinstance(entry_ts, str):
                        entry_dt = datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))

                    leak_ok = TradeDatasetLeakageChecks.verify_no_leakage(
                        signal_ts=pat.timestamp,
                        feature_ts=candle.timestamp,
                        entry_ts=entry_dt,
                        outcome_ts_max=entry_dt,
                    )

                    row_out = {
                        # ── Identificatori ──────────────────────────────────
                        "signal_id": pat.id,
                        "symbol": pat.symbol,
                        "symbol_group": symbol_group_for(pat.symbol),
                        "provider": pat.provider,
                        "pattern_name": pat.pattern_name,
                        "direction": _direction_long_short(pat.direction),
                        "timeframe": pat.timeframe,
                        "signal_timestamp": pat.timestamp.isoformat(),
                        "entry_timestamp": ob.get("entry_timestamp"),
                        # ── Label esecuzione ────────────────────────────────
                        "was_executed": was_ex,
                        "skip_reason": skip_raw,
                        "skip_reason_bucket": bucket,
                        # ── Feature segnale ──────────────────────────────────
                        "strength": strength_f,
                        "quality_score": quality,
                        "has_quality_score": quality is not None,
                        # ── Regime ───────────────────────────────────────────
                        "regime_spy": regime_spy,
                        "ctx_market_regime": ctx_mkt_regime,
                        "ctx_volatility_regime": ctx_vol,
                        "ctx_candle_expansion": ctx_exp,
                        "ctx_direction_bias": ctx_bias,
                        # ── Momentum / Trend ─────────────────────────────────
                        "rs_vs_spy": rs_spy,
                        "rs_vs_spy_5": rs_spy_5,
                        "rs_signal": rs_sig,
                        "rsi_14": rsi14,
                        "price_vs_ema9_pct": ema9_pct,
                        "ema_20": ema20_pct,
                        "ema_50": ema50_pct,
                        # ── Volatilità ───────────────────────────────────────
                        "atr_14": atr,
                        "atr_pct": atr_pct,
                        # ── Volume ───────────────────────────────────────────
                        "volume_ratio": volr,
                        "cvd_trend": cvd_trend_val,
                        "cvd_normalized": cvd_norm,
                        # ── Prezzi chiave ────────────────────────────────────
                        "price_vs_vwap_pct": pvwap,
                        "price_vs_or_high_pct": por_hi,
                        "price_vs_or_low_pct": por_lo,
                        # ── Struttura / Swing ────────────────────────────────
                        "dist_to_swing_high_pct": d_sh,
                        "dist_to_swing_low_pct": d_sl,
                        "price_position_in_range": ppr,
                        "structural_range_pct": srng,
                        # ── Fibonacci ────────────────────────────────────────
                        "dist_to_fib_382_pct": d_f382,
                        "dist_to_fib_500_pct": d_f500,
                        "dist_to_fib_618_pct": d_f618,
                        # ── Fair Value Gap ───────────────────────────────────
                        "in_fvg_bullish": fvg_bull,
                        "in_fvg_bearish": fvg_bear,
                        "dist_to_fvg_pct": d_fvg,
                        # ── Order Block ──────────────────────────────────────
                        "in_ob_bullish": ob_bull,
                        "in_ob_bearish": ob_bear,
                        "dist_to_ob_pct": d_ob,
                        "ob_strength": ob_str,
                        # ── Trade plan ───────────────────────────────────────
                        "stop_distance_pct": stop_d_pct,
                        "rr_tp1": rr1,
                        "rr_tp2": rr2,
                        # ── Candle body ──────────────────────────────────────
                        "candle_body_pct": body_pct,
                        "upper_wick_pct": uw_pct,
                        "lower_wick_pct": lw_pct,
                        # ── Temporali ────────────────────────────────────────
                        "hour_utc": hour_utc,
                        "day_of_week": dow,
                        "session": sess,
                        **cal_f,
                        # ── Macro / Volatilità sistemica (Tranche A) ─────────
                        "vix_close": vix_val,
                        "vix_percentile_1y": vix_pct1y,
                        "vix_regime": vix_reg,
                        "days_to_earnings": days_to_earn,
                        "days_from_earnings": days_from_earn,
                        "in_earnings_window": in_earn_win,
                        "days_to_fomc": fomc_d,
                        # ── Portfolio state ──────────────────────────────────
                        "n_open_positions": n_open,
                        "capital_available_pct": cap_pct,
                        # ── Outcome / Label ──────────────────────────────────
                        "pnl_final_r": ob.get("pnl_final_r"),
                        "tp1_hit": ob.get("tp1_hit"),
                        "tp2_hit": ob.get("tp2_hit"),
                        "stop_hit": ob.get("stop_hit"),
                        "bars_to_exit": ob.get("bars_to_exit"),
                        "mfe_r": ob.get("mfe_r"),
                        "mae_r": ob.get("mae_r"),
                        "pnl_4h_r": ob.get("pnl_4h_r"),
                        "pnl_12h_r": ob.get("pnl_12h_r"),
                        "pnl_24h_r": ob.get("pnl_24h_r"),
                        "pnl_48h_r": ob.get("pnl_48h_r"),
                        "early_exit_better": ob.get("early_exit_better"),
                        # ── Qualità dataset ──────────────────────────────────
                        "leakage_ok": leak_ok,
                    }
                    csv_rows.append(row_out)
                    if was_ex and len(sample_executed) < 5:
                        sample_executed.append(dict(row_out))
                except Exception as e:
                    logger.exception("signal_id=%s: %s", getattr(pat, "id", "?"), e)
                    continue

        n_distinct_pq_cutoffs = (
            len(pq_temporal_cache) if not args.quality_legacy_global else None
        )

    # Statistiche
    n_tot = len(csv_rows)
    n_ex = sum(1 for r in csv_rows if r["was_executed"])
    pct_ex = (n_ex / n_tot * 100.0) if n_tot else 0.0
    wins = sum(
        1
        for r in csv_rows
        if r["was_executed"] and r.get("pnl_final_r") is not None and float(r["pnl_final_r"]) > 0
    )
    wr_exec = (wins / n_ex * 100.0) if n_ex else 0.0

    by_pattern = Counter(str(r["pattern_name"]) for r in csv_rows)
    by_symbol = Counter(str(r["symbol"]) for r in csv_rows)

    skip_reason_hist = Counter(
        (a.skip_reason or "null")
        for a in sim.pattern_simulation_audit
        if not a.executed
    )
    n_skipped = sum(1 for r in csv_rows if not r["was_executed"])
    skipped_cf_win = sum(
        1
        for r in csv_rows
        if not r["was_executed"]
        and r.get("pnl_final_r") is not None
        and float(r["pnl_final_r"]) > 0
    )
    n_leak_bad = sum(1 for r in csv_rows if r.get("leakage_ok") is False)
    pct_leak_bad = round(n_leak_bad / n_tot * 100.0, 4) if n_tot else 0.0

    ts_vals = [str(r["signal_timestamp"]) for r in csv_rows if r.get("signal_timestamp")]
    ts_min = min(ts_vals) if ts_vals else None
    ts_max = max(ts_vals) if ts_vals else None
    eff_lim_meta = (
        SIMULATION_PATTERN_HARD_CAP
        if args.pattern_row_limit <= 0
        else min(args.pattern_row_limit, SIMULATION_PATTERN_HARD_CAP)
    )

    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol_filter_mode": symbol_filter_mode,
        "include_symbols": include_symbols_eff,
        "min_strength": args.min_strength,
        "pattern_timestamp_order": args.pattern_timestamp_order,
        "pattern_row_limit_requested": args.pattern_row_limit,
        "pattern_row_limit_effective": eff_lim_meta,
        "signal_timestamp_range_utc": {"min": ts_min, "max": ts_max},
        "ordering_note": (
            "La simulazione GET /backtest/simulation e questo script usano lo stesso ORDER BY. "
            "Con order=asc e limit N si includono i N segnali più vecchi tra i filtri; "
            "con order=desc i N più recenti. Per allineare il WR a un backtest IS (es. fino a 2025-01-01) "
            "usa --date-to e coerenza con --pattern-timestamp-order."
        ),
        "quality_score_mode": ("legacy_global" if args.quality_legacy_global else "temporal_per_signal_ts"),
        "quality_score_note": (
            "Con temporal_per_signal_ts, pattern_quality usa solo CandlePattern con timestamp <= segnale "
            "(stesso criterio di use_temporal_quality / Fix anti-leakage)."
        ),
        "n_distinct_quality_cutoffs": n_distinct_pq_cutoffs,
        "simulation_win_rate_pct": sim.win_rate,
        "simulation_total_trades": sim.total_trades,
        "dataset_rows": n_tot,
        "pct_was_executed": round(pct_ex, 4),
        "win_rate_executed_dataset_pct": round(wr_exec, 4),
        "expected_wr_v42_pct": args.expected_wr,
        "wr_sanity_delta_vs_expected": round(wr_exec - args.expected_wr, 4),
        "counts_from_simulation_audit": dict(counts),
        "skip_reason_histogram": dict(skip_reason_hist.most_common()),
        "skipped_rows_counterfactual_winners": skipped_cf_win,
        "skipped_rows_total": n_skipped,
        "pct_skipped_that_would_have_won": round(skipped_cf_win / n_skipped * 100.0, 4) if n_skipped else None,
        "leakage_ok_false_count": n_leak_bad,
        "leakage_ok_false_pct": pct_leak_bad,
        "distribution_pattern": dict(by_pattern.most_common(50)),
        "distribution_symbol": dict(by_symbol.most_common(50)),
        "feature_groups": {
            "pattern": ["strength", "quality_score", "has_quality_score", "pattern_name", "direction"],
            "regime": ["regime_spy", "ctx_market_regime", "ctx_volatility_regime", "ctx_candle_expansion", "ctx_direction_bias"],
            "momentum": ["rsi_14", "price_vs_ema9_pct", "ema_20", "ema_50", "rs_vs_spy", "rs_vs_spy_5", "rs_signal"],
            "volatility": ["atr_14", "atr_pct", "structural_range_pct"],
            "volume": ["volume_ratio", "cvd_trend", "cvd_normalized"],
            "price_levels": ["price_vs_vwap_pct", "price_vs_or_high_pct", "price_vs_or_low_pct", "price_position_in_range"],
            "structure": ["dist_to_swing_high_pct", "dist_to_swing_low_pct", "dist_to_fib_382_pct", "dist_to_fib_500_pct", "dist_to_fib_618_pct"],
            "smc": ["in_fvg_bullish", "in_fvg_bearish", "dist_to_fvg_pct", "in_ob_bullish", "in_ob_bearish", "dist_to_ob_pct", "ob_strength"],
            "trade_plan": ["stop_distance_pct", "rr_tp1", "rr_tp2"],
            "candle": ["candle_body_pct", "upper_wick_pct", "lower_wick_pct"],
            "temporal": ["hour_utc", "day_of_week", "session", "month_of_year", "week_of_year",
                         "is_opex_week", "is_quarter_start", "is_quarter_end"],
            "macro": ["vix_close", "vix_percentile_1y", "vix_regime",
                      "days_to_earnings", "days_from_earnings", "in_earnings_window", "days_to_fomc"],
            "portfolio": ["n_open_positions", "capital_available_pct"],
        },
        "assumptions": [
            "Feature da candle_indicators legati alla candela del segnale (timestamp = barra pattern).",
            "ctx_* da candle_contexts: regime/volatilita'/espansione/bias locali della serie.",
            "Outcome forward solo su candele con timestamp > signal_timestamp; controfattuale usa open barra+1.",
            "verify_no_leakage() controlla feature_ts <= signal_ts e entry > signal.",
            "has_quality_score=False indica che non c'erano abbastanza pattern storici prima del segnale per calcolare il quality_score.",
            "regime_spy da RegimeFilter SPY 1d (Yahoo) o BTC 1d (Binance) quando ci sono dati giornalieri.",
            "symbol_group mappa euristica su universo v4.2; unknown = simbolo non in lista.",
            "quality_score: default anti-leakage (lookup con dt_to = timestamp del segnale); --quality-legacy-global per confronto.",
            "candle_body_pct/upper_wick_pct/lower_wick_pct: frazioni 0-1 del range (high-low).",
            "Tranche A (VIX): vix_close/vix_percentile_1y da yfinance ^VIX; lookup al giorno del segnale (anti-leakage).",
            "Tranche A (Earnings): days_to/from_earnings da yfinance per simboli con earnings; ETF/crypto = None.",
            "Tranche A (Calendario): month_of_year, week_of_year, is_opex_week, is_quarter_start/end calcolati da signal_timestamp.",
            "Tranche A (FOMC): days_to_fomc da lista hardcoded meeting Fed 2022-2025; None se > 60g o nessuna data futura.",
            "Usa --no-external-data per saltare download VIX/Earnings (feature esterne saranno None).",
        ],
    }

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in csv_rows:
            w.writerow({k: r.get(k) for k in fieldnames})

    with OUTPUT_META.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print("\n--- Validazione ---")
    print(f"Righe dataset: {n_tot} | was_executed: {pct_ex:.2f}% | WR eseguiti (dataset): {wr_exec:.2f}%")
    print(f"WR simulazione API: {sim.win_rate:.2f}% | trade totali sim: {sim.total_trades}")
    print(f"Conteggio audit simulazione: {dict(counts)}")
    if abs(wr_exec - args.expected_wr) > 12:
        print(
            "ATTENZIONE: WR eseguiti nel dataset diverge >12 punti dall'atteso v4.2 — verificare filtri DB e parametri."
        )
    print("\nPrimi 5 trade eseguiti (ispezione):")
    for row in sample_executed:
        print(json.dumps(row, indent=2, default=str, ensure_ascii=False))

    print(f"\nSalvato: {OUTPUT_CSV}\nSalvato: {OUTPUT_META}")
    return 0


def main() -> None:
    # Su Windows, ProactorEventLoop (default Python 3.12) può fallire con WinError 64
    # durante la negoziazione SSL su connessioni localhost. SelectorEventLoop è stabile.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()

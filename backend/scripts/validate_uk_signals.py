"""
Fase 3C — Validazione statistica segnali UK (LSE, 1h, 3 anni).

Interroga il DB (candle_patterns + candle_contexts) e produce un report
di validazione per verificare che i segnali UK siano coerenti e significativi.
NON richiede connessione TWS/IBKR.

Uso:
    python -m scripts.validate_uk_signals [--top-patterns N] [--min-strength F]

Esempi:
    python -m scripts.validate_uk_signals
    python -m scripts.validate_uk_signals --top-patterns 10 --min-strength 0.5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import case, func, select, and_

from app.core.uk_universe import UK_SYMBOLS_FTSE100_TOP30, UK_EXCHANGE, UK_PROVIDER
from app.db.session import AsyncSessionLocal
from app.models.candle_context import CandleContext
from app.models.candle_pattern import CandlePattern

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_TF = "1h"


# ── query helpers ─────────────────────────────────────────────────────────────

async def _pattern_stats(min_strength: float) -> dict:
    """Conta pattern per simbolo, tipo e direzione."""
    async with AsyncSessionLocal() as session:
        # Totali per simbolo
        stmt = (
            select(
                CandlePattern.symbol,
                func.count().label("total"),
                func.sum(
                    case((CandlePattern.direction == "bullish", 1), else_=0)
                ).label("bull"),
                func.sum(
                    case((CandlePattern.direction == "bearish", 1), else_=0)
                ).label("bear"),
                func.avg(CandlePattern.pattern_strength).label("avg_strength"),
            )
            .where(
                CandlePattern.exchange == UK_EXCHANGE,
                CandlePattern.provider == UK_PROVIDER,
                CandlePattern.timeframe == _TF,
                CandlePattern.pattern_strength >= Decimal(str(min_strength)),
            )
            .group_by(CandlePattern.symbol)
            .order_by(CandlePattern.symbol)
        )
        result = await session.execute(stmt)
        by_symbol = {r.symbol: dict(r._mapping) for r in result.all()}

        # Top pattern globali per nome
        stmt2 = (
            select(
                CandlePattern.pattern_name,
                CandlePattern.direction,
                func.count().label("cnt"),
                func.avg(CandlePattern.pattern_strength).label("avg_str"),
            )
            .where(
                CandlePattern.exchange == UK_EXCHANGE,
                CandlePattern.provider == UK_PROVIDER,
                CandlePattern.timeframe == _TF,
                CandlePattern.pattern_strength >= Decimal(str(min_strength)),
            )
            .group_by(CandlePattern.pattern_name, CandlePattern.direction)
            .order_by(func.count().desc())
        )
        result2 = await session.execute(stmt2)
        by_name = [dict(r._mapping) for r in result2.all()]

    return {"by_symbol": by_symbol, "by_name": by_name}


async def _context_stats() -> dict:
    """Distribuzione regimi di mercato per simbolo UK."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(
                CandleContext.market_regime,
                CandleContext.direction_bias,
                func.count().label("cnt"),
            )
            .where(
                CandleContext.exchange == UK_EXCHANGE,
                CandleContext.provider == UK_PROVIDER,
                CandleContext.timeframe == _TF,
            )
            .group_by(CandleContext.market_regime, CandleContext.direction_bias)
            .order_by(func.count().desc())
        )
        result = await session.execute(stmt)
        regime_dist = [dict(r._mapping) for r in result.all()]

        # Totale context rows per simbolo
        stmt2 = (
            select(
                CandleContext.symbol,
                func.count().label("ctx_count"),
                func.min(CandleContext.timestamp).label("first_ts"),
                func.max(CandleContext.timestamp).label("last_ts"),
            )
            .where(
                CandleContext.exchange == UK_EXCHANGE,
                CandleContext.provider == UK_PROVIDER,
                CandleContext.timeframe == _TF,
            )
            .group_by(CandleContext.symbol)
            .order_by(CandleContext.symbol)
        )
        result2 = await session.execute(stmt2)
        by_symbol = {r.symbol: dict(r._mapping) for r in result2.all()}

    return {"regime_dist": regime_dist, "by_symbol": by_symbol}


# ── formattazione report ──────────────────────────────────────────────────────

def _bar(value: int, total: int, width: int = 20) -> str:
    if total == 0:
        return " " * width
    filled = round(value / total * width)
    return "█" * filled + "░" * (width - filled)


def _fmt_pct(num: int, den: int) -> str:
    if den == 0:
        return "  n/a"
    return f"{num/den*100:5.1f}%"


def _print_report(
    pat: dict,
    ctx: dict,
    top_n: int,
    min_strength: float,
) -> None:
    sep = "=" * 72

    # ── Header ────────────────────────────────────────────────────────────────
    print(f"\n{sep}")
    print(f"  UK SIGNAL VALIDATION — Fase 3C")
    print(f"  Exchange: {UK_EXCHANGE}  Provider: {UK_PROVIDER}  Timeframe: {_TF}")
    print(f"  Filtro forza pattern: >= {min_strength}")
    print(f"{sep}\n")

    # ── Sezione 1: Pattern per simbolo ────────────────────────────────────────
    print("─── Pattern per Simbolo ─────────────────────────────────────────────\n")
    print(f"  {'Symbol':<8}  {'Total':>6}  {'Bull%':>6}  {'Bear%':>6}  {'AvgStr':>7}  {'Density':>8}  {'Barre ctx':>10}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*7}  {'-'*8}  {'-'*10}")

    total_patterns = 0
    symbols_ok = []
    symbols_warn = []

    for sym in sorted(UK_SYMBOLS_FTSE100_TOP30):
        p = pat["by_symbol"].get(sym, {})
        c = ctx["by_symbol"].get(sym, {})

        total = p.get("total", 0) or 0
        bull = int(p.get("bull", 0) or 0)
        bear = int(p.get("bear", 0) or 0)
        avg_str = float(p.get("avg_strength", 0) or 0)
        ctx_count = c.get("ctx_count", 0) or 0

        # Densità: pattern per 100 barre
        density = total / ctx_count * 100 if ctx_count > 0 else 0
        total_patterns += total

        bull_pct = _fmt_pct(bull, total)
        bear_pct = _fmt_pct(bear, total)

        flag = ""
        if total == 0:
            flag = " ⚠ NO PATTERNS"
            symbols_warn.append(sym)
        elif density < 5:
            flag = " ⚠ bassa densità"
            symbols_warn.append(sym)
        else:
            symbols_ok.append(sym)

        print(
            f"  {sym:<8}  {total:>6}  {bull_pct}  {bear_pct}  {avg_str:>7.4f}"
            f"  {density:>7.1f}%  {ctx_count:>10}{flag}"
        )

    print(f"\n  Totale pattern: {total_patterns:,}  |  Simboli OK: {len(symbols_ok)}  |  Warning: {len(symbols_warn)}")

    # ── Sezione 2: Top pattern globali ───────────────────────────────────────
    print(f"\n─── Top {top_n} Pattern per Frequenza ────────────────────────────────────\n")
    print(f"  {'Pattern':<35}  {'Dir':<8}  {'Count':>6}  {'AvgStr':>7}")
    print(f"  {'-'*35}  {'-'*8}  {'-'*6}  {'-'*7}")

    for row in pat["by_name"][:top_n]:
        print(
            f"  {row['pattern_name']:<35}  {row['direction']:<8}"
            f"  {int(row['cnt']):>6}  {float(row['avg_str']):>7.4f}"
        )

    # ── Sezione 3: Distribuzione regimi ──────────────────────────────────────
    print(f"\n─── Distribuzione Regimi di Mercato (tutti i simboli) ───────────────\n")

    regime_total = sum(r["cnt"] for r in ctx["regime_dist"])
    print(f"  {'Regime':<14}  {'Bias':<12}  {'Count':>6}  {'%':>6}  {'Bar':>22}")
    print(f"  {'-'*14}  {'-'*12}  {'-'*6}  {'-'*6}  {'-'*22}")
    for row in ctx["regime_dist"][:15]:
        cnt = row["cnt"]
        pct = cnt / regime_total * 100 if regime_total > 0 else 0
        bar = _bar(cnt, regime_total, 20)
        print(f"  {row['market_regime']:<14}  {row['direction_bias']:<12}  {cnt:>6}  {pct:>5.1f}%  {bar}")

    # ── Sezione 4: Health check ───────────────────────────────────────────────
    print(f"\n─── Health Check ────────────────────────────────────────────────────\n")

    # Calcola bull/bear totali
    total_bull = sum(int(p.get("bull", 0) or 0) for p in pat["by_symbol"].values())
    total_bear = sum(int(p.get("bear", 0) or 0) for p in pat["by_symbol"].values())
    bull_ratio = total_bull / total_patterns if total_patterns > 0 else 0
    bear_ratio = total_bear / total_patterns if total_patterns > 0 else 0

    checks = [
        (
            len(symbols_warn) == 0,
            f"Tutti i simboli hanno pattern",
            f"{len(symbols_warn)} simboli senza pattern o bassa densità: {symbols_warn}",
        ),
        (
            total_patterns > 100_000,
            f"Volume pattern adeguato ({total_patterns:,} > 100.000)",
            f"Pattern totali scarsi: {total_patterns:,}",
        ),
        (
            0.35 <= bull_ratio <= 0.65,
            f"Bilanciamento bull/bear accettabile ({bull_ratio:.0%} bull / {bear_ratio:.0%} bear)",
            f"Bilanciamento sbilanciato ({bull_ratio:.0%} bull / {bear_ratio:.0%} bear)",
        ),
        (
            len(pat["by_name"]) >= 5,
            f"Diversità pattern sufficiente ({len(pat['by_name'])} tipi distinti)",
            f"Pochi tipi di pattern: {len(pat['by_name'])}",
        ),
    ]

    all_ok = True
    for ok, msg_ok, msg_fail in checks:
        status = "✓" if ok else "✗"
        msg = msg_ok if ok else msg_fail
        print(f"  [{status}] {msg}")
        if not ok:
            all_ok = False

    print(f"\n  Esito: {'VALIDAZIONE OK' if all_ok else 'ATTENZIONE — verificare i warning sopra'}")
    print(f"\n{sep}\n")
    print("  Prossimo step — Fase 3D: analisi scoring e backtest UK:")
    print("  docker compose exec backend python -m scripts.backtest_uk_patterns")
    print(f"\n{sep}\n")


# ── main ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validazione segnali UK storici (Fase 3C)")
    p.add_argument("--top-patterns", type=int, default=15, help="Top N pattern per frequenza")
    p.add_argument(
        "--min-strength",
        type=float,
        default=0.0,
        help="Forza minima pattern (default: 0 = tutti)",
    )
    return p.parse_args()


async def main() -> None:
    args = _parse_args()
    logger.info("Caricamento dati UK dal DB (exchange=%s, provider=%s, tf=%s)…", UK_EXCHANGE, UK_PROVIDER, _TF)

    pat, ctx = await asyncio.gather(
        _pattern_stats(args.min_strength),
        _context_stats(),
    )

    _print_report(pat, ctx, args.top_patterns, args.min_strength)


if __name__ == "__main__":
    asyncio.run(main())

"""
Calcolo indicatori tecnici rolling su candele storiche.

EMA: Exponential Moving Average (metodo classico con smoothing factor 2/(N+1)).
RSI: Relative Strength Index 14 periodi (metodo Wilder/EMA).
ATR: Average True Range 14 periodi.
volume_ratio_vs_ma20: volume corrente / media mobile semplice volume 20 barre.
price_vs_ema_pct: (close - ema) / ema * 100.

Nessuna dipendenza esterna (no pandas, no ta-lib): calcolo puro Python/Decimal
per compatibilità con l'ambiente Docker esistente.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candle import Candle
from app.models.candle_indicator import CandleIndicator
from app.schemas.indicators import IndicatorExtractRequest, IndicatorExtractResponse
from app.services.funding_rate_service import (
    assign_funding_to_candles,
    fetch_funding_rates,
    funding_bias_from_rate,
)

# Ora di apertura/chiusura sessione US (UTC)
_US_SESSION_OPEN_HOUR = 14  # 09:30 ET = 14:30 UTC (ora legale)
_US_SESSION_OPEN_MIN = 30
_US_SESSION_CLOSE_HOUR = 21  # 16:00 ET = 21:00 UTC
_OR_BARS_5M = 6  # Opening range = prime 6 barre da 5m = 30 minuti
_OR_BARS_1H = 1  # Opening range = prima barra da 1h = prima ora

_UPSERT_CHUNK_SIZE = 500
# Barre su ogni lato per swing high/low locale (5 → 5m ~25 min per lato, 1h ~5h per lato).
_SWING_WINDOW = 5


def _f(x: Any) -> float:
    if x is None:
        return 0.0
    if isinstance(x, Decimal):
        return float(x)
    return float(x)


def _calc_ema(closes: list[float], period: int) -> list[float | None]:
    """EMA con smoothing factor k = 2/(period+1)."""
    if len(closes) < period:
        return [None] * len(closes)
    k = 2.0 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    sma = sum(closes[:period]) / period
    result.append(sma)
    prev = sma
    for c in closes[period:]:
        ema = c * k + prev * (1 - k)
        result.append(ema)
        prev = ema
    return result


def _calc_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """RSI con smoothing Wilder."""
    n = len(closes)
    if n < period + 1:
        return [None] * n

    result: list[float | None] = [None] * n
    changes = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(0.0, c) for c in changes]
    losses = [max(0.0, -c) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi_from_avg(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    result[period] = _rsi_from_avg(avg_gain, avg_loss)

    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i + 1] = _rsi_from_avg(avg_gain, avg_loss)

    return result


def _calc_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    """ATR con smoothing Wilder."""
    n = len(closes)
    if n < period + 1:
        return [None] * n

    trs: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    result: list[float | None] = [None] * n
    avg = sum(trs[:period]) / period
    result[period - 1] = avg

    for i in range(period, n):
        avg = (avg * (period - 1) + trs[i]) / period
        result[i] = avg

    return result


def _calc_volume_ma(volumes: list[float], period: int = 20) -> list[float | None]:
    """SMA del volume su `period` barre."""
    n = len(volumes)
    result: list[float | None] = [None] * n
    for i in range(period - 1, n):
        result[i] = sum(volumes[i - period + 1 : i + 1]) / period
    return result


def _calc_swing_points(
    highs: list[float],
    lows: list[float],
    window: int = 5,
) -> tuple[list[bool], list[bool]]:
    """
    Rilevazione swing high/low locali con finestra simmetrica.

    Un punto è swing high se il suo high è il massimo
    nelle `window` barre a sinistra E a destra.
    Stesso criterio per swing low con i minimi.

    Le prime e ultime `window` barre non possono essere swing points
    (non hanno abbastanza barre su entrambi i lati).

    Ritorna (is_swing_high, is_swing_low) come liste bool.
    """
    n = len(highs)
    is_sh = [False] * n
    is_sl = [False] * n

    for i in range(window, n - window):
        left_h = highs[i - window : i]
        right_h = highs[i + 1 : i + window + 1]
        if highs[i] > max(left_h) and highs[i] > max(right_h):
            is_sh[i] = True

        left_l = lows[i - window : i]
        right_l = lows[i + 1 : i + window + 1]
        if lows[i] < min(left_l) and lows[i] < min(right_l):
            is_sl[i] = True

    return is_sh, is_sl


def _calc_structural_levels(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    is_swing_high: list[bool],
    is_swing_low: list[bool],
) -> tuple[
    list[float | None],
    list[float | None],
    list[float | None],
    list[float | None],
    list[float | None],
    list[float | None],
]:
    """
    Per ogni barra calcola:
    - ultimo swing high valido (il più recente prima o su questa barra)
    - ultimo swing low valido
    - distanza % del close corrente da questi livelli
    - range strutturale e posizione del prezzo nel range
    """
    n = len(closes)
    last_sh: list[float | None] = [None] * n
    last_sl: list[float | None] = [None] * n
    dist_sh: list[float | None] = [None] * n
    dist_sl: list[float | None] = [None] * n
    struct_range: list[float | None] = [None] * n
    price_pos: list[float | None] = [None] * n

    current_sh: float | None = None
    current_sl: float | None = None

    for i in range(n):
        if is_swing_high[i]:
            current_sh = highs[i]
        if is_swing_low[i]:
            current_sl = lows[i]

        last_sh[i] = current_sh
        last_sl[i] = current_sl

        cl = closes[i]

        if current_sh is not None and current_sh > 0:
            dist_sh[i] = (current_sh - cl) / cl * 100.0

        if current_sl is not None and current_sl > 0:
            dist_sl[i] = (cl - current_sl) / cl * 100.0

        if current_sh is not None and current_sl is not None:
            rng = current_sh - current_sl
            if rng > 0:
                struct_range[i] = rng / current_sl * 100.0
                pos = (cl - current_sl) / rng
                price_pos[i] = max(0.0, min(1.0, pos))

    return last_sh, last_sl, dist_sh, dist_sl, struct_range, price_pos


def _is_us_session(ts: datetime) -> bool:
    """True se il timestamp è nella sessione regolare US (14:30-21:00 UTC)."""
    h, m = ts.hour, ts.minute
    start = h * 60 + m
    open_min = _US_SESSION_OPEN_HOUR * 60 + _US_SESSION_OPEN_MIN
    close_min = _US_SESSION_CLOSE_HOUR * 60
    return open_min <= start < close_min


def _session_date(ts: datetime) -> str:
    """Data sessione US: prima delle 14:30 UTC = giorno precedente."""
    if ts.hour < _US_SESSION_OPEN_HOUR or (
        ts.hour == _US_SESSION_OPEN_HOUR and ts.minute < _US_SESSION_OPEN_MIN
    ):
        return (ts - timedelta(days=1)).strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d")


def _calc_vwap_and_session_levels(
    candles: list,
    provider: str,
    timeframe: str,
) -> tuple[
    list[float | None],  # vwap
    list[float | None],  # price_vs_vwap_pct
    list[float | None],  # session_high
    list[float | None],  # session_low
    list[float | None],  # opening_range_high
    list[float | None],  # opening_range_low
    list[float | None],  # price_vs_or_high_pct
    list[float | None],  # price_vs_or_low_pct
]:
    """
    Calcola VWAP, livelli di sessione e opening range.

    Per crypto (provider=binance): VWAP rolling 24h (nessuna sessione fissa).
    Per Yahoo (ETF/stock): VWAP per sessione US (reset ogni apertura 14:30 UTC).

    Opening range: prime _OR_BARS barre della sessione.
    """
    n = len(candles)
    vwap_out: list[float | None] = [None] * n
    pvwap_out: list[float | None] = [None] * n
    sh_out: list[float | None] = [None] * n
    sl_out: list[float | None] = [None] * n
    or_high_out: list[float | None] = [None] * n
    or_low_out: list[float | None] = [None] * n
    por_high_out: list[float | None] = [None] * n
    por_low_out: list[float | None] = [None] * n

    is_yahoo = provider == "yahoo_finance"
    window_max = 288 if timeframe == "5m" else 24

    # Stato per sessione corrente
    cum_pv = 0.0  # cumulative price*volume
    cum_v = 0.0  # cumulative volume
    current_session = ""
    session_h: float | None = None
    session_l: float | None = None
    or_h: float | None = None
    or_l: float | None = None
    or_bars_count = 0
    or_complete = False

    # Per crypto: finestra rolling 24h
    window_24h: list[tuple[float, float]] = []  # (typical_price, volume)

    for i, c in enumerate(candles):
        ts = c.timestamp
        cl = _f(c.close)
        hi = _f(c.high)
        lo = _f(c.low)
        vol = _f(c.volume)
        typical = (hi + lo + cl) / 3.0

        if is_yahoo:
            # Sessione US: reset a ogni apertura
            sess = _session_date(ts)
            in_session = _is_us_session(ts)

            if sess != current_session:
                # Nuova sessione: reset tutto
                current_session = sess
                cum_pv = 0.0
                cum_v = 0.0
                session_h = None
                session_l = None
                or_h = None
                or_l = None
                or_bars_count = 0
                or_complete = False

            if in_session:
                cum_pv += typical * vol
                cum_v += vol
                if cum_v > 0:
                    vwap_val = cum_pv / cum_v
                    vwap_out[i] = vwap_val
                    if cl > 0:
                        pvwap_out[i] = (cl - vwap_val) / cl * 100.0

                # Session high/low
                session_h = hi if session_h is None else max(session_h, hi)
                session_l = lo if session_l is None else min(session_l, lo)
                sh_out[i] = session_h
                sl_out[i] = session_l

                # Opening range
                or_bars = _OR_BARS_5M if timeframe == "5m" else _OR_BARS_1H
                if not or_complete:
                    or_bars_count += 1
                    or_h = hi if or_h is None else max(or_h, hi)
                    or_l = lo if or_l is None else min(or_l, lo)
                    if or_bars_count >= or_bars:
                        or_complete = True

                if or_h is not None and or_l is not None:
                    or_high_out[i] = or_h
                    or_low_out[i] = or_l
                    if cl > 0:
                        por_high_out[i] = (or_h - cl) / cl * 100.0
                        por_low_out[i] = (cl - or_l) / cl * 100.0

        else:
            # Crypto: VWAP rolling 24h (1440 minuti)
            # Approssimazione: finestra di 288 barre su 5m o 24 barre su 1h
            window_24h.append((typical, vol))
            if len(window_24h) > window_max:
                window_24h.pop(0)
            tot_pv = sum(p * v for p, v in window_24h)
            tot_v = sum(v for _, v in window_24h)
            if tot_v > 0:
                vwap_val = tot_pv / tot_v
                vwap_out[i] = vwap_val
                if cl > 0:
                    pvwap_out[i] = (cl - vwap_val) / cl * 100.0

    return (
        vwap_out,
        pvwap_out,
        sh_out,
        sl_out,
        or_high_out,
        or_low_out,
        por_high_out,
        por_low_out,
    )


def _calc_fibonacci_levels(
    closes: list[float],
    last_swing_highs: list[float | None],
    last_swing_lows: list[float | None],
) -> tuple[
    list[float | None],  # fib_382
    list[float | None],  # fib_500
    list[float | None],  # fib_618
    list[float | None],  # dist_to_fib_382_pct
    list[float | None],  # dist_to_fib_500_pct
    list[float | None],  # dist_to_fib_618_pct
]:
    """
    Calcola livelli Fibonacci di retracement dall'ultimo impulso.

    Impulso bullish: da last_swing_low a last_swing_high (se swing_high > swing_low).
    Impulso bearish: da last_swing_high a last_swing_low (se swing_low < swing_high).

    Fib levels calcolati sull'impulso più recente identificato dagli swing points.
    """
    n = len(closes)
    f382: list[float | None] = [None] * n
    f500: list[float | None] = [None] * n
    f618: list[float | None] = [None] * n
    d382: list[float | None] = [None] * n
    d500: list[float | None] = [None] * n
    d618: list[float | None] = [None] * n

    for i in range(n):
        sh = last_swing_highs[i]
        sl = last_swing_lows[i]
        if sh is None or sl is None:
            continue
        if sh <= sl:
            continue

        cl = closes[i]
        impulse = sh - sl

        # Fibonacci retracement dall'alto verso il basso
        # (retracement di un impulso bullish)
        r382 = sh - 0.382 * impulse
        r500 = sh - 0.500 * impulse
        r618 = sh - 0.618 * impulse

        f382[i] = r382
        f500[i] = r500
        f618[i] = r618

        if cl > 0:
            d382[i] = abs(cl - r382) / cl * 100.0
            d500[i] = abs(cl - r500) / cl * 100.0
            d618[i] = abs(cl - r618) / cl * 100.0

    return f382, f500, f618, d382, d500, d618


def _calc_cvd(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    vol_ma20: list[float | None],
    cvd_trend_window: int = 10,
) -> tuple[
    list[float],
    list[float],
    list[float | None],
    list[str],
    list[float],
]:
    """
    Calcola CVD (Cumulative Volume Delta) da dati OHLCV.

    Stima del delta per candela:
    - body_ratio = |close - open| / (high - low) se range > 0
    - doji (open ≈ close): volume_delta = 0
    - altrimenti volume_delta = volume × body_ratio × sign(close - open)

    CVD = cumsum(volume_delta) sulla serie estratta (reset per serie).
    """
    n = len(closes)
    vd: list[float] = []
    cvd_list: list[float] = []
    cvd_norm: list[float | None] = []
    cvd_trend: list[str] = []
    cvd_5_out: list[float] = []

    cum = 0.0
    eps = 1e-12

    for i in range(n):
        rng = highs[i] - lows[i]
        body = abs(closes[i] - opens[i])
        br = body / rng if rng > 0 else 0.0
        if abs(closes[i] - opens[i]) < eps:
            delta = 0.0
        else:
            direction = 1.0 if closes[i] > opens[i] else -1.0
            delta = volumes[i] * br * direction
        cum += delta

        vd.append(delta)
        cvd_list.append(cum)

        if vol_ma20[i] is not None and vol_ma20[i] > 0:
            cvd_norm.append(cum / vol_ma20[i])
        else:
            cvd_norm.append(None)

        if i >= cvd_trend_window:
            past_cvd = cvd_list[i - cvd_trend_window]
            diff = cum - past_cvd
            threshold = abs(past_cvd) * 0.02 if past_cvd != 0 else 1.0
            if diff > threshold:
                cvd_trend.append("bullish")
            elif diff < -threshold:
                cvd_trend.append("bearish")
            else:
                cvd_trend.append("neutral")
        else:
            cvd_trend.append("neutral")

        start_5 = max(0, i - 4)
        cvd_5_out.append(sum(vd[start_5 : i + 1]))

    return vd, cvd_list, cvd_norm, cvd_trend, cvd_5_out


async def _distinct_series(
    session: AsyncSession,
    *,
    exchange: str | None,
    provider: str | None,
    symbol: str | None,
    timeframe: str | None,
) -> list[tuple[str, str, str, str, str]]:
    """Ritorna (exchange, symbol, timeframe, provider, asset_type) distinct."""
    stmt = select(
        Candle.exchange,
        Candle.symbol,
        Candle.timeframe,
        Candle.provider,
        Candle.asset_type,
    ).distinct()
    conds = []
    if exchange is not None:
        conds.append(Candle.exchange == exchange)
    if provider is not None:
        conds.append(Candle.provider == provider)
    if symbol is not None:
        conds.append(Candle.symbol == symbol)
    if timeframe is not None:
        conds.append(Candle.timeframe == timeframe)
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(
        Candle.exchange,
        Candle.symbol,
        Candle.timeframe,
        Candle.provider,
    )
    result = await session.execute(stmt)
    return [(r[0], r[1], r[2], r[3], r[4]) for r in result.all()]


async def _chunked_upsert_indicators(
    session: AsyncSession,
    rows: list[dict[str, Any]],
) -> int:
    """Bulk upsert CandleIndicator in chunk da 500 righe."""
    if not rows:
        return 0
    total_rc = 0
    for i in range(0, len(rows), _UPSERT_CHUNK_SIZE):
        chunk = rows[i : i + _UPSERT_CHUNK_SIZE]
        stmt = insert(CandleIndicator).values(chunk)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            constraint="uq_candle_indicators_candle_id",
            set_={
                "asset_type": excluded.asset_type,
                "provider": excluded.provider,
                "symbol": excluded.symbol,
                "exchange": excluded.exchange,
                "timeframe": excluded.timeframe,
                "timestamp": excluded.timestamp,
                "ema_9": excluded.ema_9,
                "ema_20": excluded.ema_20,
                "ema_50": excluded.ema_50,
                "rsi_14": excluded.rsi_14,
                "atr_14": excluded.atr_14,
                "volume_ratio_vs_ma20": excluded.volume_ratio_vs_ma20,
                "price_vs_ema20_pct": excluded.price_vs_ema20_pct,
                "price_vs_ema50_pct": excluded.price_vs_ema50_pct,
                "is_swing_high": excluded.is_swing_high,
                "is_swing_low": excluded.is_swing_low,
                "last_swing_high": excluded.last_swing_high,
                "last_swing_low": excluded.last_swing_low,
                "dist_to_swing_high_pct": excluded.dist_to_swing_high_pct,
                "dist_to_swing_low_pct": excluded.dist_to_swing_low_pct,
                "structural_range_pct": excluded.structural_range_pct,
                "price_position_in_range": excluded.price_position_in_range,
                "vwap": excluded.vwap,
                "price_vs_vwap_pct": excluded.price_vs_vwap_pct,
                "session_high": excluded.session_high,
                "session_low": excluded.session_low,
                "opening_range_high": excluded.opening_range_high,
                "opening_range_low": excluded.opening_range_low,
                "price_vs_or_high_pct": excluded.price_vs_or_high_pct,
                "price_vs_or_low_pct": excluded.price_vs_or_low_pct,
                "fib_382": excluded.fib_382,
                "fib_500": excluded.fib_500,
                "fib_618": excluded.fib_618,
                "dist_to_fib_382_pct": excluded.dist_to_fib_382_pct,
                "dist_to_fib_500_pct": excluded.dist_to_fib_500_pct,
                "dist_to_fib_618_pct": excluded.dist_to_fib_618_pct,
                "funding_rate": excluded.funding_rate,
                "funding_rate_annualized_pct": excluded.funding_rate_annualized_pct,
                "funding_bias": excluded.funding_bias,
                "volume_delta": excluded.volume_delta,
                "cvd": excluded.cvd,
                "cvd_normalized": excluded.cvd_normalized,
                "cvd_trend": excluded.cvd_trend,
                "cvd_5": excluded.cvd_5,
            },
        )
        result = await session.execute(stmt)
        rc = result.rowcount
        if rc is not None and rc >= 0:
            total_rc += int(rc)
    await session.commit()
    return total_rc


async def extract_indicators(
    session: AsyncSession,
    request: IndicatorExtractRequest,
) -> IndicatorExtractResponse:
    """Calcola e persiste indicatori tecnici per ogni serie."""
    series = await _distinct_series(
        session,
        exchange=request.exchange,
        provider=request.provider,
        symbol=request.symbol,
        timeframe=request.timeframe,
    )

    rows_to_upsert: list[dict[str, Any]] = []
    candles_read = 0

    for ex, sym, tf, prov, at in series:
        stmt = (
            select(Candle)
            .where(
                Candle.exchange == ex,
                Candle.symbol == sym,
                Candle.timeframe == tf,
                Candle.provider == prov,
            )
            .order_by(Candle.timestamp.desc())
            .limit(request.limit)
        )
        result = await session.execute(stmt)
        candles = list(result.scalars().all())
        candles.reverse()
        if len(candles) < 2:
            continue
        candles_read += len(candles)

        opens_f = [_f(c.open) for c in candles]
        closes = [_f(c.close) for c in candles]
        highs = [_f(c.high) for c in candles]
        lows = [_f(c.low) for c in candles]
        volumes = [_f(c.volume) for c in candles]

        ema9 = _calc_ema(closes, 9)
        ema20 = _calc_ema(closes, 20)
        ema50 = _calc_ema(closes, 50)
        rsi14 = _calc_rsi(closes, 14)
        atr14 = _calc_atr(highs, lows, closes, 14)
        vol_ma20 = _calc_volume_ma(volumes, 20)

        swing_window = _SWING_WINDOW
        is_sh, is_sl = _calc_swing_points(highs, lows, window=swing_window)
        last_sh, last_sl, dist_sh, dist_sl, struct_range, price_pos = _calc_structural_levels(
            closes,
            highs,
            lows,
            is_sh,
            is_sl,
        )

        # VWAP, sessione, opening range
        (
            vwap_vals,
            pvwap_vals,
            sess_h,
            sess_l,
            or_h_vals,
            or_l_vals,
            por_h_vals,
            por_l_vals,
        ) = _calc_vwap_and_session_levels(candles, prov, tf)

        # Fibonacci
        fib_382, fib_500, fib_618, d_fib382, d_fib500, d_fib618 = _calc_fibonacci_levels(
            closes,
            last_sh,
            last_sl,
        )

        # Funding rate (solo Binance, simboli mappati in funding_rate_service)
        funding_rates_raw: list[float | None] = [None] * len(candles)
        if prov == "binance":
            first_ts = candles[0].timestamp
            last_ts = candles[-1].timestamp
            funding_data = await fetch_funding_rates(sym, first_ts, last_ts)
            candle_timestamps = [c.timestamp for c in candles]
            funding_rates_raw = assign_funding_to_candles(
                candle_timestamps,
                funding_data,
            )

        # CVD (tutti i provider/timeframe)
        vd_vals, cvd_vals, cvd_norm_vals, cvd_trend_vals, cvd5_vals = _calc_cvd(
            opens_f,
            highs,
            lows,
            closes,
            volumes,
            vol_ma20,
        )

        for i, candle in enumerate(candles):
            cl = closes[i]

            vol_ratio: Decimal | None = None
            if vol_ma20[i] is not None and vol_ma20[i] > 0:
                vol_ratio = Decimal(str(round(volumes[i] / vol_ma20[i], 8)))

            def _pct(price: float, ema: float | None) -> Decimal | None:
                if ema is None or ema == 0:
                    return None
                return Decimal(str(round((price - ema) / ema * 100, 8)))

            rows_to_upsert.append(
                {
                    "candle_id": candle.id,
                    "asset_type": at,
                    "provider": prov,
                    "symbol": sym,
                    "exchange": ex,
                    "timeframe": tf,
                    "timestamp": candle.timestamp,
                    "ema_9": Decimal(str(round(ema9[i], 12))) if ema9[i] is not None else None,
                    "ema_20": Decimal(str(round(ema20[i], 12))) if ema20[i] is not None else None,
                    "ema_50": Decimal(str(round(ema50[i], 12))) if ema50[i] is not None else None,
                    "rsi_14": Decimal(str(round(rsi14[i], 8))) if rsi14[i] is not None else None,
                    "atr_14": Decimal(str(round(atr14[i], 12))) if atr14[i] is not None else None,
                    "volume_ratio_vs_ma20": vol_ratio,
                    "price_vs_ema20_pct": _pct(cl, ema20[i]),
                    "price_vs_ema50_pct": _pct(cl, ema50[i]),
                    "is_swing_high": is_sh[i],
                    "is_swing_low": is_sl[i],
                    "last_swing_high": (
                        Decimal(str(round(last_sh[i], 12)))
                        if last_sh[i] is not None
                        else None
                    ),
                    "last_swing_low": (
                        Decimal(str(round(last_sl[i], 12)))
                        if last_sl[i] is not None
                        else None
                    ),
                    "dist_to_swing_high_pct": (
                        Decimal(str(round(dist_sh[i], 8)))
                        if dist_sh[i] is not None
                        else None
                    ),
                    "dist_to_swing_low_pct": (
                        Decimal(str(round(dist_sl[i], 8)))
                        if dist_sl[i] is not None
                        else None
                    ),
                    "structural_range_pct": (
                        Decimal(str(round(struct_range[i], 8)))
                        if struct_range[i] is not None
                        else None
                    ),
                    "price_position_in_range": (
                        Decimal(str(round(price_pos[i], 8)))
                        if price_pos[i] is not None
                        else None
                    ),
                    "vwap": (
                        Decimal(str(round(vwap_vals[i], 12)))
                        if vwap_vals[i] is not None
                        else None
                    ),
                    "price_vs_vwap_pct": (
                        Decimal(str(round(pvwap_vals[i], 8)))
                        if pvwap_vals[i] is not None
                        else None
                    ),
                    "session_high": (
                        Decimal(str(round(sess_h[i], 12)))
                        if sess_h[i] is not None
                        else None
                    ),
                    "session_low": (
                        Decimal(str(round(sess_l[i], 12)))
                        if sess_l[i] is not None
                        else None
                    ),
                    "opening_range_high": (
                        Decimal(str(round(or_h_vals[i], 12)))
                        if or_h_vals[i] is not None
                        else None
                    ),
                    "opening_range_low": (
                        Decimal(str(round(or_l_vals[i], 12)))
                        if or_l_vals[i] is not None
                        else None
                    ),
                    "price_vs_or_high_pct": (
                        Decimal(str(round(por_h_vals[i], 8)))
                        if por_h_vals[i] is not None
                        else None
                    ),
                    "price_vs_or_low_pct": (
                        Decimal(str(round(por_l_vals[i], 8)))
                        if por_l_vals[i] is not None
                        else None
                    ),
                    "fib_382": (
                        Decimal(str(round(fib_382[i], 12)))
                        if fib_382[i] is not None
                        else None
                    ),
                    "fib_500": (
                        Decimal(str(round(fib_500[i], 12)))
                        if fib_500[i] is not None
                        else None
                    ),
                    "fib_618": (
                        Decimal(str(round(fib_618[i], 12)))
                        if fib_618[i] is not None
                        else None
                    ),
                    "dist_to_fib_382_pct": (
                        Decimal(str(round(d_fib382[i], 8)))
                        if d_fib382[i] is not None
                        else None
                    ),
                    "dist_to_fib_500_pct": (
                        Decimal(str(round(d_fib500[i], 8)))
                        if d_fib500[i] is not None
                        else None
                    ),
                    "dist_to_fib_618_pct": (
                        Decimal(str(round(d_fib618[i], 8)))
                        if d_fib618[i] is not None
                        else None
                    ),
                    "funding_rate": (
                        Decimal(str(round(funding_rates_raw[i], 10)))
                        if funding_rates_raw[i] is not None
                        else None
                    ),
                    "funding_rate_annualized_pct": (
                        Decimal(
                            str(
                                round(
                                    funding_rates_raw[i] * 3 * 365 * 100,
                                    6,
                                ),
                            ),
                        )
                        if funding_rates_raw[i] is not None
                        else None
                    ),
                    "funding_bias": (
                        funding_bias_from_rate(funding_rates_raw[i])
                        if funding_rates_raw[i] is not None
                        else None
                    ),
                    "volume_delta": Decimal(str(round(vd_vals[i], 4))),
                    "cvd": Decimal(str(round(cvd_vals[i], 4))),
                    "cvd_normalized": (
                        Decimal(str(round(cvd_norm_vals[i], 6)))
                        if cvd_norm_vals[i] is not None
                        else None
                    ),
                    "cvd_trend": cvd_trend_vals[i],
                    "cvd_5": Decimal(str(round(cvd5_vals[i], 4))),
                }
            )

    indicators_upserted = await _chunked_upsert_indicators(session, rows_to_upsert)

    return IndicatorExtractResponse(
        series_processed=len(series),
        candles_read=candles_read,
        indicators_upserted=indicators_upserted,
    )

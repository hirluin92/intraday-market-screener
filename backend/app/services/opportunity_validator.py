"""
Sistema decisionale unico per le opportunità.

Produce operational_decision e decision_rationale basandosi su:
1. Timeframe operativo (1h, 5m)
2. Simbolo validato (universo esplicito)
3. Pattern validato (lista operativa)
4. Regime di mercato (solo Yahoo: SPY 1d EMA50 ±2%; crypto Binance senza filtro regime)

Questo è l'UNICO sistema che produce la decisione finale.
Non esiste altro sistema di scoring operativo.
"""

from __future__ import annotations

from datetime import UTC, datetime

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _TZ_ET = _ZoneInfo("America/New_York")
except Exception:
    _TZ_ET = None

from app.core.hour_filters import (
    EXCLUDED_HOURS_UTC_LSE,
    EXCLUDED_HOURS_UTC_US,
    hour_utc,
)
from app.models.candle_indicator import CandleIndicator
from app.core.trade_plan_variant_constants import (
    DATA_COLLECTION_SYMBOLS_UK,
    EXCLUDED_HOURS_ET_5M_END,
    MAX_RISK_PCT_LONG,
    MAX_RISK_PCT_SHORT,
    PATTERN_QUALITY_MIN_SAMPLE,
    PATTERNS_BEAR_REGIME_ONLY,
    PATTERNS_BLOCKED,
    SIGNAL_MIN_CONFLUENCE,
    SIGNAL_MIN_STRENGTH,
    STRADA_A_ENGULFING_MIN_FINAL_SCORE,
    SYMBOLS_BLOCKED_YAHOO_1H,
    VALIDATED_PATTERNS_1H,
    VALIDATED_PATTERNS_5M,
    VALIDATED_SYMBOLS_ALPACA_5M,
    VALIDATED_SYMBOLS_BINANCE,
    VALIDATED_SYMBOLS_UK,
    VALIDATED_SYMBOLS_YAHOO,
    VALIDATED_TIMEFRAMES,
)
from app.services.regime_filter_service import RegimeFilter


def validate_opportunity(
    *,
    symbol: str,
    timeframe: str,
    provider: str,
    pattern_name: str | None,
    direction: str | None,
    regime_filter: RegimeFilter | None,
    timestamp: datetime,
    exchange: str | None = None,
    pattern_strength: float | None = None,
    confluence_count: int = 1,
    min_confluence_patterns: int | None = None,
    final_score: float | None = None,
    screener_score: float | None = None,
    risk_pct: float | None = None,
    ind: CandleIndicator | None = None,
) -> tuple[str, list[str]]:
    """
    Ritorna (operational_decision, decision_rationale).

    execute = setup allineato a vincoli validati (pattern/universo/TF; filtro regime solo su Yahoo).
    monitor forzato = simboli UK in fase raccolta dati (DATA_COLLECTION_SYMBOLS_UK).
    """
    rationale: list[str] = []

    h = hour_utc(timestamp)
    # 1h yahoo_finance: nessun filtro orario (operativo tutto il giorno di trading).
    # Non-1h yahoo (es. 5m futuro): applica filtro after-hours / pausa pranzo.
    if provider == "yahoo_finance" and timeframe != "1h" and h in EXCLUDED_HOURS_UTC_US:
        return "discard", [
            f"Ora {h}:00 UTC non operativa (after hours o bassa liquidità sessione US).",
        ]
    if provider == "ibkr" and h in EXCLUDED_HOURS_UTC_LSE:
        return "discard", [
            f"Ora {h}:00 UTC fuori dalla sessione LSE (operativa 7-16 UTC).",
        ]

    if provider == "alpaca" and timeframe == "5m":
        ts_utc = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
        if _TZ_ET is not None:
            hour_et = ts_utc.astimezone(_TZ_ET).hour
        else:
            hour_et = (ts_utc.hour - 4) % 24

        # 5m TRIPLO config apr 2026 — tre fasce operative:
        # ① <11:00 ET : pre-market, nessun segnale operativo
        # ② 11-14 ET  : MIDDAY_F — solo se al estremo del giorno (price_position_in_range)
        #               avg+slip midday filtrato = +0.565R (n=714), OOS-stabile 2024-2026.
        #               Senza filtro: avg_r = +0.034R (rumore).
        # ③ 15-16 ET  : ALPHA — tutti i 6 pattern, avg+slip=+0.869R WR=61.8%
        if hour_et < EXCLUDED_HOURS_ET_5M_END:
            return "discard", [
                f"5m: fuori orario operativo (ora ET {hour_et:02d}:xx) — "
                "TRIPLO config apr 2026: operativo dalle 11:00 ET "
                "(midday 11-15 ET filtrato per estremo giorno; ALPHA 15-16 ET senza filtri).",
            ]

        if 11 <= hour_et <= 14:
            # 5m TRIPLO config apr 2026: midday 11-15 ET solo se price_position_in_range
            # al estremo del giorno (bullish: pos<=0.10, bearish: pos>=0.90).
            # avg_r+slip midday filtrato = +0.565R (n=714), stabile OOS 2024-2026
            # (+0.625/+0.551/+0.474R). Senza filtro: avg_r = +0.034R WR=33.7%.
            if ind is None or ind.price_position_in_range is None:
                return "discard", [
                    f"5m midday (ora ET {hour_et:02d}:xx): indicatore non disponibile per "
                    "filtro estremo giorno — segnale scartato per sicurezza (TRIPLO apr 2026).",
                ]
            pos = float(ind.price_position_in_range)
            _dir_local = (direction or "").strip().lower()
            is_at_extreme = (
                (_dir_local == "bullish" and pos <= 0.10) or
                (_dir_local == "bearish" and pos >= 0.90)
            )
            if not is_at_extreme:
                return "discard", [
                    f"5m midday (ora ET {hour_et:02d}:xx): prezzo non all'estremo del giorno "
                    f"(price_position_in_range={pos:.2f}, "
                    "richiesto <=0.10 bullish / >=0.90 bearish) — "
                    "TRIPLO config apr 2026: midday senza estremo avg_r=-0.157R (n=1490, OOS confermato).",
                ]

    # FIX 8 apr 2026: 1h IBKR/UK — apertura LSE (03:xx ET) debole.
    # avg_r=+0.111R vs +0.659R resto; OOS confermato (train +0.133R, test +0.029R).
    if provider == "ibkr" and timeframe == "1h":
        ts_utc = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
        hour_et = ts_utc.astimezone(_TZ_ET).hour if _TZ_ET is not None else (ts_utc.hour - 4) % 24
        if hour_et == 3:
            return "discard", [
                "1h: apertura UK (03:xx ET = 08:xx BST) non operativa — "
                "avg_r=+0.111R vs +0.659R resto della sessione, "
                "OOS confermato (train +0.133R, test +0.029R, apr 2026).",
            ]

    if timeframe not in VALIDATED_TIMEFRAMES:
        return "discard", [
            f"Timeframe {timeframe} non operativo — usare 1h o 5m.",
        ]

    if provider == "yahoo_finance":
        if symbol not in VALIDATED_SYMBOLS_YAHOO:
            in_blocked = symbol in SYMBOLS_BLOCKED_YAHOO_1H
            if in_blocked:
                return "discard", [
                    f"{symbol} bloccato dall'universo operativo "
                    "(ETF PRIIP/KID o dataset insufficiente — vedi SYMBOLS_BLOCKED_YAHOO_1H).",
                ]
            return "discard", [
                f"{symbol} non nell'universo validato — edge non confermato.",
            ]
    elif provider == "alpaca":
        if timeframe == "5m" and symbol not in VALIDATED_SYMBOLS_ALPACA_5M:
            return "discard", [
                f"{symbol} non nell'universo Alpaca 5m validato. "
                "WMT rimosso apr 2026: avg_r=-0.166R su n=268 (4 pattern validati, dataset deterministico).",
            ]
    elif provider == "binance":
        if symbol not in VALIDATED_SYMBOLS_BINANCE:
            return "discard", [
                f"{symbol} non nell'universo crypto validato.",
            ]
    elif provider == "ibkr":
        # UK/LSE: distingui simboli "raccolta dati" da simboli completamente fuori universo.
        if symbol in VALIDATED_SYMBOLS_UK:
            pass  # validato per auto-execute → procede normalmente
        elif symbol in DATA_COLLECTION_SYMBOLS_UK:
            pass  # raccolta dati → procede ma sarà forzato a "monitor" prima di "execute"
        else:
            return "discard", [
                f"{symbol} non nell'universo UK (LSE) configurato.",
            ]

    if not pattern_name or not str(pattern_name).strip():
        return "discard", [
            "Nessun pattern rilevato sull'ultima barra — niente segnale validato.",
        ]

    pn = str(pattern_name).strip()

    # Pattern con WR storico < 40% su campione ampio — bloccato esplicitamente.
    if pn in PATTERNS_BLOCKED:
        return "discard", [
            f"Pattern «{pn}» bloccato: WR storico < 40% su campione significativo.",
            "Tradare questo pattern produce aspettativa negativa nel backtest su 26k+ segnali.",
        ]

    if timeframe == "1h":
        validated_patterns = VALIDATED_PATTERNS_1H
    elif timeframe == "5m":
        validated_patterns = VALIDATED_PATTERNS_5M
    else:
        validated_patterns = frozenset()

    pattern_validated = pn in validated_patterns
    if not pattern_validated:
        return "discard", [
            f"Pattern «{pn}» su {timeframe} non nella lista operativa validata.",
            "Validati 1h: double_top, double_bottom, macd_divergence_bear/bull, "
            "rsi_divergence_bear/bull, engulfing_bullish. "
            "Su 5m (Alpaca): double_top/bottom, macd_divergence_bear/bull. "
            "compression_to_expansion_transition: BLOCCATO apr 2026 (avg_r=-0.114R su n=386).",
        ]

    dir_norm = (direction or "").strip().lower()
    if dir_norm not in ("bullish", "bearish"):
        return "discard", [
            "Direzione pattern assente o non direzionale — non classificabile per regime.",
        ]

    regime_label = "neutral"
    regime_ok = True
    if provider == "yahoo_finance":
        regime_ref = "SPY"
    elif provider == "alpaca":
        # Alpaca aggiunto al regime filter apr 2026: senza regime check, il 5m apriva
        # SHORT in mercato BULL → 9/9 trade perdenti il primo giorno operativo.
        # regime_filter passato da opportunities.py è già regime_filter_yahoo (SPY 1d).
        regime_ref = "SPY"
    elif provider == "binance":
        regime_ref = "BTC"
    elif provider == "ibkr":
        regime_ref = "^FTSE"  # regime anchor UK (Fase 4A)
    else:
        regime_ref = "n/a"

    if regime_filter is not None and provider in ("yahoo_finance", "alpaca", "binance", "ibkr"):
        allowed_directions = regime_filter.get_allowed_directions(timestamp)
        regime_label = regime_filter.get_regime_label(timestamp)

        if dir_norm not in allowed_directions:
            regime_ok = False
            rationale.append(
                f"Segnale {dir_norm} contro il regime {regime_ref} ({regime_label}) — "
                "probabilità di successo ridotta."
            )

    # Solo engulfing_bullish rimane BEAR-only (EV negativo in bull: -0.13R).
    # macd_divergence_bull e rsi_divergence_bull rimossi da BEAR_ONLY apr 2026:
    # dataset produzione mostra avg_r positivo in tutti i regimi (vedi constants).
    if pn in PATTERNS_BEAR_REGIME_ONLY and regime_label not in ("bear", "bearish"):
        rationale.append(
            f"Pattern «{pn}» ha edge confermato SOLO in regime bearish "
            f"(EV bear=+0.16R vs EV bull=-0.13R) — regime attuale: {regime_label}."
        )
        return "monitor", rationale

    if pattern_validated and regime_ok:
        # Filtro confluenza: richiede che almeno N pattern validati distinti siano
        # attivi contemporaneamente nella stessa barra per lo stesso simbolo.
        # Validato via OOS: min_confluence=2 → EV +0.478R (+95.3%), WR 58.4%,
        # PF 2.82, DD -19.8% rispetto a nessun filtro (apr 2026).
        _min_conf = min_confluence_patterns if min_confluence_patterns is not None else SIGNAL_MIN_CONFLUENCE
        if confluence_count < _min_conf:
            rationale.append(
                f"Confluenza insufficiente: {confluence_count} pattern validato/i attivo/i "
                f"(minimo richiesto: {_min_conf}) — attendere conferma multi-segnale."
            )
            return "monitor", rationale

        # FIX 6 apr 2026: su 1h, pattern_strength >= 0.80 → setup overstretched.
        # avg_r=-0.066R, WR=19.6% su n=189 (dataset deterministico 39k trade).
        # Relazione non monotona: strength 0.6-0.7 (+0.527R) > 0.7-0.8 (+0.471R) > 0.8-0.9 (-0.066R).
        if timeframe == "1h" and pattern_strength is not None and pattern_strength >= 0.80:
            rationale.append(
                f"1h pattern_strength {pattern_strength:.2f} >= 0.80: setup overstretched — "
                "avg_r=-0.066R, WR=19.6% su n=189 (dataset deterministico apr 2026)."
            )
            return "discard", rationale

        if pattern_strength is not None and pattern_strength < SIGNAL_MIN_STRENGTH:
            rationale.append(
                f"Pattern strength {pattern_strength:.2f} sotto la soglia operativa "
                f"({SIGNAL_MIN_STRENGTH:g}) — attendere conferma o setup più pulito."
            )
            return "monitor", rationale

        # FIX 12 apr 2026 (aggiornato): risk_pct differenziato per direzione.
        # LONG (direction=bullish): fascia 1.5-3% avg_r=+1.014R (macd_bull) / +0.897R (double_bottom).
        # SHORT (direction=bearish): fascia 1.5-3% avg_r=+0.391-0.473R — marginale.
        # Dataset produzione deterministico val_1h_production.csv (apr 2026).
        if timeframe == "1h" and risk_pct is not None:
            _is_long = direction == "bullish"
            _risk_limit_pct = MAX_RISK_PCT_LONG * 100 if _is_long else MAX_RISK_PCT_SHORT * 100
            if risk_pct > _risk_limit_pct:
                _dir_label = "LONG" if _is_long else "SHORT"
                rationale.append(
                    f"Stop troppo largo per pattern {_dir_label} "
                    f"(risk_pct={risk_pct:.2f}% > {_risk_limit_pct:.1f}%) — "
                    f"soglia differenziata: LONG <= {MAX_RISK_PCT_LONG*100:.0f}%, "
                    f"SHORT <= {MAX_RISK_PCT_SHORT*100:.0f}% (dataset produzione apr 2026)."
                )
                return "discard", rationale
            # Minimum floor 1h: stop < 0.30% indica compressione anomala o bar piatta.
            if risk_pct < 0.30:
                rationale.append(
                    f"1h stop troppo stretto (risk_pct={risk_pct:.3f}% < 0.30% floor) — "
                    "1h bar normalmente genera stop > 0.5%; un valore inferiore indica "
                    "ingresso in zona compressa o calcolo anomalo."
                )
                return "discard", rationale

        # SAFETY apr 2026: 5m stop floor — alzato da 0.30% a 0.50%.
        # ZS a 0.557% (sopra il vecchio floor) ha comunque perso -1.19R per slippage.
        # Esempio TGT: stop $0.12 (0.093%) → fill a $129.058 vs stop $129.00 = -1.48R.
        # A 0.50% floor: worst case $1k / ($206×0.005) = 971 shares × $206 = $200K (≈ MAX_NOTIONAL).
        # Il floor 0.50% coincide anche con il MAX_NOTIONAL=capital×2 per 1% risk su $100K.
        if timeframe == "5m" and risk_pct is not None and risk_pct < 0.50:
            rationale.append(
                f"5m stop troppo stretto (risk_pct={risk_pct:.3f}% < 0.50% floor) — "
                "slippage su stop stretti produce R effettivo >> 1.0R live vs backtest. "
                "Alzato da 0.30% a 0.50% apr 2026 (ZS 0.557% → -1.19R con slippage)."
            )
            return "discard", rationale
        # FIX apr 2026: 5m stop cap — risk_pct > 2.0% → stop troppo largo.
        # Analisi dataset: fascia 2.00-3.00% avg_r=-0.423R WR=6.7% (n=30), 3.00%+ avg_r=-0.048R WR=0%.
        # Stop > 2% su 5m indica barre anormalmente ampie (news, gap) dove il pattern non regge.
        if timeframe == "5m" and risk_pct is not None and risk_pct > 2.0:
            rationale.append(
                f"5m stop troppo largo (risk_pct={risk_pct:.3f}% > 2.0% cap) — "
                "fascia 2-3%: avg_r=-0.423R WR=6.7% (n=30) apr 2026. "
                "Stop ampio indica barre di news/gap dove i pattern 5m non reggono."
            )
            return "discard", rationale

        # ── Strada A: engulfing_bullish richiede ranking (AUC interna 0.63) ──
        # Gli altri pattern contro-trend hanno AUC interna ~0.44 (rumore):
        # il gate binario (= nessuna soglia score) è il loro optimum.
        if pn == "engulfing_bullish" and final_score is not None:
            if final_score < STRADA_A_ENGULFING_MIN_FINAL_SCORE:
                rationale.append(
                    f"Strada A: engulfing_bullish final_score {final_score:.1f} "
                    f"sotto soglia ranking ({STRADA_A_ENGULFING_MIN_FINAL_SCORE}) — "
                    "score nel pool engulfing non nel top ~20%, EV atteso non giustifica execute."
                )
                return "monitor", rationale

        rationale.append(
            "Pattern validato da backtest / validazione OOS (universo e TF operativi)."
        )
        if pn in PATTERNS_BEAR_REGIME_ONLY:
            rationale.append(
                f"Regime {regime_ref} bearish — {pn} attivato: WR 67% in mercato ribassista."
            )
        elif pn in ("rsi_divergence_bear", "macd_divergence_bear") and regime_label in ("bear", "bearish"):
            ev_map = {"rsi_divergence_bear": "+0.22R", "macd_divergence_bear": "+0.25R"}
            rationale.append(
                f"Regime {regime_ref} bearish — {pn} SHORT attivo: EV={ev_map.get(pn, '+0.22R')} "
                "confermato in bear (edge inferiore vs bull ma positivo)."
            )
        elif provider == "binance":
            rationale.append(
                "Crypto — regime filter non applicato (edge indipendente da BTC).",
            )
        elif regime_label != "neutral":
            rationale.append(
                f"Regime {regime_ref} {regime_label} — direzione {dir_norm} consentita dal filtro."
            )
        rationale.append(
            "Segnale operativo — gestire rischio (es. 1% per trade, max 3 simultanei)."
        )
        rationale.append(
            f"Pattern validato con edge statistico confermato su 38k+ segnali simulati "
            f"(WR >= 50%, campione >= {PATTERN_QUALITY_MIN_SAMPLE})."
        )
        # Nota HIGH_EDGE: non filtra, solo annota per paper trading tracking.
        # OOS apr 2026: screener_score 5-10 → avg_r=+1.37R vs score 10+ → +0.35R.
        if screener_score is not None and 5 <= screener_score < 10:
            rationale.append(
                f"[HIGH_EDGE] screener_score={screener_score:.1f} (fascia 5-10) — "
                "avg_r=+1.37R OOS confermato vs +0.35R per score 10+. "
                "Setup ad alto edge atteso."
            )
        return "execute", rationale

    if pattern_validated and not regime_ok:
        rationale.append(
            f"Pattern validato ma regime {regime_ref} non allineato — ridurre size o attendere conferma."
        )
        return "monitor", rationale

    return "monitor", rationale or [
        "Condizioni intermedie — valutare contesto prima dell'ingresso.",
    ]

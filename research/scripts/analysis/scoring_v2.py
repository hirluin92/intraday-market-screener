"""
scoring_v2.py — Formula di scoring con pesi per-pattern.

## Razionale

La sezione 5 di analyze_validation_dataset.py ha rivelato che su 1h (n=2095):
  - final_score v1 AUC = 0.451  (peggio di qualunque singolo componente)
  - pattern_strength AUC = 0.451 (invertita)
  - screener_score   AUC = 0.470 (invertita)
  - pattern_quality_score AUC = 0.525 (unico componente con AUC > 0.50)

La sezione 6 ha rivelato che l'inversione è CONDIZIONALE, non strutturale:
  - engulfing_bullish:  AUC(strength)=0.571 ★, AUC(screener)=0.614 ★
  - rsi_divergence_*:   AUC(strength)≈0.41 ▼, AUC(screener)≈0.44 ▼

Il problema: la formula lineare con pesi uniformi mescola pattern trend-following
(screener positivo) con pattern contro-trend (screener negativo) cancellando il segnale.

## Formula v2

  score_v2 = screener * 5 * w_scr(pattern)
           + alignment_bonus           (±10, invariato)
           + (pq_eff / 100) * 14       (pq sempre weight +1.0, è l'unico universalmente positivo)
           + strength * 8 * w_str(pattern)

  → clipped a [0, 100]

  dove pq_eff = pq se non-null, altrimenti PQ_FALLBACK (50 = neutro).

## Derivazione dei pesi

I segni derivano direttamente dall'AUC empirica:
  AUC > 0.52  → peso positivo (componente predice correttamente)
  AUC ≈ 0.50  → peso zero    (rumore neutro, non inquinare)
  AUC < 0.47  → peso negativo (componente predice al contrario, invertire è utile)

Le magnitudini sono proporzionali alla distanza da 0.50, scalate a [-1, +1]:
  AUC = 0.61 → distance 0.11 → peso ≈ +1.0 (massimo)
  AUC = 0.53 → distance 0.03 → peso ≈ +0.3
  AUC = 0.44 → distance 0.06 → peso ≈ -0.5

Pattern non ancora nel dataset di validazione (n<30) → "_default": replica v1 (w=+1.0)
per non modificare comportamento su pattern senza evidenza empirica.

## CHANGELOG (aggiornare ad ogni modifica empiricamente motivata)

  v2.0 — 2026-04-10
    Dataset: val_1h_large.csv (n=2095), sezione 6 di analyze_validation_dataset.py
    Prima versione con pesi per-pattern. Non ancora deployata in produzione.
    Baseline v1 AUC=0.451 (1h). Obiettivo: superare 0.525 (miglior componente).
"""

from __future__ import annotations

# Fallback pq quando None: 50 = "metà del range", neutro.
# Non imputare 0 (penalizzerebbe tutti i pattern senza storico 1h/1d)
# Non imputare 100 (gonfia artificialmente segnali senza backtest).
PQ_FALLBACK = 50.0

# ---------------------------------------------------------------------------
# Pesi per-pattern — derivati dalla sezione 6 di analyze_validation_dataset.py
# ---------------------------------------------------------------------------
# Struttura: { pattern_name: {"screener": w_scr, "strength": w_str} }
# pq è sempre +1.0 (unico componente con AUC > 0.50 su tutti i timeframe)
#
# Dati dataset 1h (n=2095, run 2026-04-10):
#   pattern_name                  n    AUC(str)  AUC(scr)   w_str  w_scr
#   rsi_divergence_bull          191   0.410▼    0.437▼     -0.50  -0.50
#   rsi_divergence_bear          211   0.442▼    0.436▼     -0.30  -0.50
#   double_bottom                114   0.466▼    0.479      -0.20  -0.20
#   macd_divergence_bear         279   0.485     0.435▼      0.00  -0.50
#   macd_divergence_bull         275   0.511     0.404▼     +0.30  -0.70
#   rsi_momentum_continuation    298   0.523     0.534      +0.50  +0.50
#   double_top                   136   0.548     0.447▼     +0.50  -0.30
#   compression_to_expansion     300   0.549     0.497       0.00   0.00
#   engulfing_bullish            291   0.571★    0.614★     +1.00  +1.00
PATTERN_WEIGHTS_V2: dict[str, dict[str, float]] = {
    # ── Pattern contro-trend / divergenza ────────────────────────────────
    # Screener forte = trend avverso al pattern → screener va invertito
    # Strength alta in divergenza = candle overestesa prima del rimbalzo
    "rsi_divergence_bull": {
        "screener": -0.50,
        "strength": -0.50,
    },
    "rsi_divergence_bear": {
        "screener": -0.50,
        "strength": -0.30,
    },
    "macd_divergence_bull": {
        "screener": -0.70,  # AUC(scr)=0.404 — fortemente invertita
        "strength": +0.30,  # AUC(str)=0.511 — lievemente positiva
    },
    "macd_divergence_bear": {
        "screener": -0.50,  # AUC(scr)=0.435
        "strength":  0.00,  # AUC(str)=0.485 — neutro
    },
    "double_top": {
        "screener": -0.30,  # AUC(scr)=0.447 — lievemente invertita
        "strength": +0.50,  # AUC(str)=0.548 — lievemente positiva
    },
    "double_bottom": {
        "screener": -0.20,  # AUC(scr)=0.479 — quasi neutro
        "strength": -0.20,  # AUC(str)=0.466 — quasi neutro
    },
    # ── Pattern quasi-neutri ─────────────────────────────────────────────
    "compression_to_expansion_transition": {
        "screener":  0.00,  # AUC(scr)=0.497 — neutro
        "strength":  0.00,  # AUC(str)=0.549 — lievemente positivo ma usiamo 0 (marginale)
    },
    "rsi_momentum_continuation": {
        "screener": +0.50,  # AUC(scr)=0.534
        "strength": +0.50,  # AUC(str)=0.523
    },
    # ── Pattern trend-following con entrambi positivi ────────────────────
    "engulfing_bullish": {
        "screener": +1.00,  # AUC(scr)=0.614 ★
        "strength": +1.00,  # AUC(str)=0.571 ★
    },
    # ── Pattern non ancora misurati nel dataset (n<30 su 1h) ─────────────
    # Per questi si usa _default (= comportamento v1) per non fare assunzioni
    # senza evidenza empirica. Da aggiornare man mano che il dataset cresce.
    #
    # Candidati da misurare (pattern presenti nel sistema ma assenti nel dataset 1h):
    #   breakout_with_retest, inside_bar_breakout_bull, opening_range_breakout_*,
    #   fvg_retest_*, ob_retest_*, vwap_bounce_*, liquidity_sweep_*,
    #   engulfing_bearish, impulsive_bullish_candle, impulsive_bearish_candle
}

# Pesi di fallback per pattern non ancora nel dataset (= comportamento v1 invariato)
_DEFAULT_WEIGHTS: dict[str, float] = {
    "screener": +1.00,
    "strength": +1.00,
}


def _alignment_bonus(alignment_str: str) -> float:
    """Bonus allineamento da stringa CSV (pre-calcolata da build_validation_dataset)."""
    if alignment_str == "aligned":
        return 10.0
    if alignment_str == "conflicting":
        return -10.0
    return 0.0


def compute_score_v2(
    *,
    pattern_name: str,
    screener_score: float,
    pattern_strength: float,
    pattern_quality_score: float | None,
    signal_alignment: str,
) -> float:
    """
    Calcola il final_score alternativo v2 per una riga del dataset.

    Args:
        pattern_name:          nome del pattern (key in PATTERN_WEIGHTS_V2)
        screener_score:        score grezzo (0–12) dallo screener strutturale
        pattern_strength:      forza del pattern (0–1)
        pattern_quality_score: score backtest 0–100, o None se non disponibile
        signal_alignment:      "aligned" | "mixed" | "conflicting"

    Returns:
        float: score v2 in [0, 100]
    """
    weights = PATTERN_WEIGHTS_V2.get(pattern_name, _DEFAULT_WEIGHTS)
    w_scr = weights["screener"]
    w_str = weights["strength"]

    pq_eff = pattern_quality_score if pattern_quality_score is not None else PQ_FALLBACK

    total = (
        screener_score * 5.0 * w_scr
        + _alignment_bonus(signal_alignment)
        + (pq_eff / 100.0) * 14.0           # pq sempre peso +1.0
        + pattern_strength * 8.0 * w_str
    )
    return round(max(0.0, min(100.0, total)), 2)

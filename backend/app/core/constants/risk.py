"""
Risk and sizing constants — thresholds for position sizing, slippage, and trailing stops.
"""

# Soglia minima pattern strength per execute (validator) e default operativo alert.
SIGNAL_MIN_STRENGTH: float = 0.60

# Numero minimo di pattern distinti VALIDATI per promuovere a "execute".
SIGNAL_MIN_CONFLUENCE: int = 1

# Soglia massima risk_pct per direzione del pattern.
MAX_RISK_PCT_LONG: float = 0.03   # 3.0% per pattern bullish
MAX_RISK_PCT_SHORT: float = 0.020  # 2.0% per pattern bearish

# Opportunità live: oltre questa distanza % dall'entry il segnale execute può essere declassato.
PRICE_STALENESS_THRESHOLD_PCT: float = 1.0

# Soglia slippage: se realized_R < questa costante, lo slippage è significativo.
_SLIPPAGE_R_THRESHOLD: float = -1.10

# Soglia minima di fill utile.
MIN_FILL_RATIO: float = 0.30

# Trailing stop Config D — trail progressivo step 0.5R.
# Calibrata su pool TRIPLO 5m OOS-confermata (n=243 trade 2026):
#   2024 +0.2517 / 2025 +0.2962 / 2026 OOS +0.2881  vs Config C.
# Cattura mfe alti che Config C bloccava a +0.5R lock fisso.
# Logica salto-step: se MFE arriva direttamente a +2.5R, lock+2.0R immediatamente
# (non step-by-step). Trovare lo step massimo raggiunto e applicarlo se non già fatto.
# Lista (mfe_trigger_R, dest_R): a MFE >= mfe_trigger, sposta lo stop a entry+dest_R.
TRAIL_STEPS: list[tuple[float, float]] = [
    (0.50, 0.00),   # +0.5R MFE → BE
    (1.00, 0.50),   # +1.0R MFE → +0.5R lock
    (1.50, 1.00),   # +1.5R MFE → +1.0R lock
    (2.00, 1.50),   # +2.0R MFE → +1.5R lock
    (2.50, 2.00),   # +2.5R MFE → +2.0R lock
]

# Risk size 5m differenziato per ora ET.
# OOS-confermato (243 trade 2026): hour 15 stabile +0.71R, hour 11 +0.59R, hour 12-14 marginali.
# Tier {0.30%, 0.50%, 0.75%}: incremento atteso MC mediana +63% vs flat 0.5%.
# Hour 15 ALPHA = 87% del volume del pool TRIPLO con edge massimo.
# Safety: notional max a 0.75% × stop 0.5% = 1.5× capital, dentro MAX_NOTIONAL=2× capital.
RISK_SIZE_5M_BY_HOUR_ET: dict[int, float] = {
    11: 0.0030,   # 0.30% — edge basso (+0.31R)
    12: 0.0050,   # 0.50% — standard
    13: 0.0050,   # 0.50% — standard
    14: 0.0050,   # 0.50% — standard
    15: 0.0075,   # 0.75% — ALPHA hour, edge massimo (+0.84R)
    16: 0.0030,   # 0.30% — edge basso
}

# Soglia score Strada A per engulfing_bullish.
STRADA_A_ENGULFING_MIN_FINAL_SCORE: float = 84.0

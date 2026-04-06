-- VWAP, sessione US, opening range, Fibonacci retracement (Prompt 3)
ALTER TABLE candle_indicators
    ADD COLUMN IF NOT EXISTS vwap NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS price_vs_vwap_pct NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS session_high NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS session_low NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS opening_range_high NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS opening_range_low NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS price_vs_or_high_pct NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS price_vs_or_low_pct NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS fib_382 NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS fib_500 NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS fib_618 NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS dist_to_fib_382_pct NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS dist_to_fib_500_pct NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS dist_to_fib_618_pct NUMERIC(12,8);

-- CVD (Cumulative Volume Delta) su candle_indicators
ALTER TABLE candle_indicators
    ADD COLUMN IF NOT EXISTS volume_delta NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS cvd NUMERIC(24,4),
    ADD COLUMN IF NOT EXISTS cvd_normalized NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS cvd_trend VARCHAR(16),
    ADD COLUMN IF NOT EXISTS cvd_5 NUMERIC(24,4);

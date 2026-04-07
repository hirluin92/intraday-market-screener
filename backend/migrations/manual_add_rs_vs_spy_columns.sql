-- Relative Strength vs SPY (rendimento simbolo - rendimento SPY sulla stessa barra)
ALTER TABLE candle_indicators
    ADD COLUMN IF NOT EXISTS rs_vs_spy NUMERIC(12, 6),
    ADD COLUMN IF NOT EXISTS rs_vs_spy_5 NUMERIC(12, 6),
    ADD COLUMN IF NOT EXISTS rs_signal VARCHAR(16);

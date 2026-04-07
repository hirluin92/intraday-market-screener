-- Fair Value Gaps (FVG) su candle_indicators
-- Eseguire: docker compose exec postgres psql -U postgres -d intraday_market_screener -f ...

ALTER TABLE candle_indicators
    ADD COLUMN IF NOT EXISTS in_fvg_bullish BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS in_fvg_bearish BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS fvg_high NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS fvg_low NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS dist_to_fvg_pct NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS fvg_direction VARCHAR(16),
    ADD COLUMN IF NOT EXISTS fvg_filled BOOLEAN NOT NULL DEFAULT FALSE;

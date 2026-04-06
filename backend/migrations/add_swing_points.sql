-- Aggiunge swing points e livelli strutturali a candle_indicators (DB già creato con create_all).
-- Eseguire manualmente o via: psql ... -f backend/migrations/add_swing_points.sql

ALTER TABLE candle_indicators
    ADD COLUMN IF NOT EXISTS is_swing_high BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_swing_low BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS last_swing_high NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS last_swing_low NUMERIC(24,12),
    ADD COLUMN IF NOT EXISTS dist_to_swing_high_pct NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS dist_to_swing_low_pct NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS structural_range_pct NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS price_position_in_range NUMERIC(12,8);

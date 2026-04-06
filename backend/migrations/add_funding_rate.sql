-- Funding rate Binance Futures (perpetui) su candle_indicators
ALTER TABLE candle_indicators
    ADD COLUMN IF NOT EXISTS funding_rate NUMERIC(16,10),
    ADD COLUMN IF NOT EXISTS funding_rate_annualized_pct NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS funding_bias VARCHAR(16);

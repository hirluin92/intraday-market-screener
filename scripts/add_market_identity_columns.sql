-- Aggiunge colonne identità mercato a DB esistenti (create_all non altera tabelle già create).
-- PostgreSQL: eseguire una volta prima di avviare il backend aggiornato.

ALTER TABLE candles ADD COLUMN IF NOT EXISTS asset_type VARCHAR(16) NOT NULL DEFAULT 'crypto';
ALTER TABLE candles ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'binance';
ALTER TABLE candles ADD COLUMN IF NOT EXISTS market_metadata JSONB NULL;

ALTER TABLE candle_features ADD COLUMN IF NOT EXISTS asset_type VARCHAR(16) NOT NULL DEFAULT 'crypto';
ALTER TABLE candle_features ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'binance';
ALTER TABLE candle_features ADD COLUMN IF NOT EXISTS market_metadata JSONB NULL;

ALTER TABLE candle_contexts ADD COLUMN IF NOT EXISTS asset_type VARCHAR(16) NOT NULL DEFAULT 'crypto';
ALTER TABLE candle_contexts ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'binance';
ALTER TABLE candle_contexts ADD COLUMN IF NOT EXISTS market_metadata JSONB NULL;

ALTER TABLE candle_patterns ADD COLUMN IF NOT EXISTS asset_type VARCHAR(16) NOT NULL DEFAULT 'crypto';
ALTER TABLE candle_patterns ADD COLUMN IF NOT EXISTS provider VARCHAR(32) NOT NULL DEFAULT 'binance';
ALTER TABLE candle_patterns ADD COLUMN IF NOT EXISTS market_metadata JSONB NULL;

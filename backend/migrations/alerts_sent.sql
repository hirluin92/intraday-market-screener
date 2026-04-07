-- Dedupe persistente per alert_service (opzionale: create_all crea già la tabella da ORM).
CREATE TABLE IF NOT EXISTS alerts_sent (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    pattern_name VARCHAR(64) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    bar_hour_utc VARCHAR(16) NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    telegram_ok BOOLEAN DEFAULT FALSE NOT NULL,
    discord_ok BOOLEAN DEFAULT FALSE NOT NULL,
    CONSTRAINT uq_alert_sent_dedup UNIQUE (
        symbol, timeframe, provider, pattern_name, direction, bar_hour_utc
    )
);

CREATE INDEX IF NOT EXISTS idx_alerts_sent_sent_at ON alerts_sent (sent_at);

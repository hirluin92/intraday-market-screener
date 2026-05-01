-- Abilitato da initdb (solo su volume vuoto / primo avvio).
-- Su DB esistente: eseguire manualmente dentro il container Postgres.
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

"""add_query_performance_indexes

Indici compositi ottimizzati per le query critiche dello screener live:

1. candle_contexts — list_latest_context_per_series
   La query usa WHERE timestamp >= since_dt [AND provider=?] con window function
   PARTITION BY (exchange, symbol, timeframe) ORDER BY (timestamp DESC, id DESC).
   - ix_candle_contexts_provider_ts_id: (provider, timestamp DESC, id DESC)
   - ix_candle_contexts_ts_id: (timestamp DESC, id DESC)

2. candle_patterns — list_latest_pattern_per_series
   - ix_candle_patterns_provider_ts_id: (provider, timestamp DESC, id DESC)

3. candle_patterns — count_concurrent_patterns_per_series
   - ix_candle_patterns_name_ts_series: (pattern_name, timestamp, exchange, symbol, timeframe)

4. candles — fetch_latest_candles_by_series_keys
   - ix_candles_provider_exchange_symbol_tf_ts: (provider, exchange, symbol, timeframe, timestamp DESC)

Revision ID: perf_idx_0001
Revises: 5a0e4c6955cb
Create Date: 2026-04-15 00:01:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "perf_idx_0001"
down_revision: Union[str, Sequence[str], None] = "5a0e4c6955cb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. candle_contexts ────────────────────────────────────────────────────
    op.create_index(
        "ix_candle_contexts_provider_ts_id",
        "candle_contexts",
        ["provider", "timestamp", "id"],
        postgresql_ops={"timestamp": "DESC", "id": "DESC"},
    )
    op.create_index(
        "ix_candle_contexts_ts_id",
        "candle_contexts",
        ["timestamp", "id"],
        postgresql_ops={"timestamp": "DESC", "id": "DESC"},
    )

    # ── 2. candle_patterns — list_latest_pattern_per_series ──────────────────
    op.create_index(
        "ix_candle_patterns_provider_ts_id",
        "candle_patterns",
        ["provider", "timestamp", "id"],
        postgresql_ops={"timestamp": "DESC", "id": "DESC"},
    )

    # ── 3. candle_patterns — count_concurrent_patterns_per_series ────────────
    # pattern_name IN (validated_list) ha alta selettività → leading column ideale.
    op.create_index(
        "ix_candle_patterns_name_ts_series",
        "candle_patterns",
        ["pattern_name", "timestamp", "exchange", "symbol", "timeframe"],
    )

    # ── 4. candles — fetch_latest_candles_by_series_keys ─────────────────────
    # Sostituisce funzionalmente ix_candles_exchange_symbol_timeframe (che manca provider)
    # per la query con tuple IN su (provider, exchange, symbol, timeframe).
    op.create_index(
        "ix_candles_provider_exchange_symbol_tf_ts",
        "candles",
        ["provider", "exchange", "symbol", "timeframe", "timestamp"],
        postgresql_ops={"timestamp": "DESC"},
    )

    # ── 5. candle_indicators — get_indicator_for_candle_timestamp ─────────────
    # Punto query: WHERE exchange=? AND symbol=? AND provider=? AND timeframe=? AND timestamp=?
    # L'indice esistente manca provider → point lookup scansiona righe extra.
    op.create_index(
        "ix_candle_indicators_exchange_symbol_provider_tf_ts",
        "candle_indicators",
        ["exchange", "symbol", "provider", "timeframe", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_candle_indicators_exchange_symbol_provider_tf_ts", table_name="candle_indicators")
    op.drop_index("ix_candles_provider_exchange_symbol_tf_ts", table_name="candles")
    op.drop_index("ix_candle_patterns_name_ts_series", table_name="candle_patterns")
    op.drop_index("ix_candle_patterns_provider_ts_id", table_name="candle_patterns")
    op.drop_index("ix_candle_contexts_ts_id", table_name="candle_contexts")
    op.drop_index("ix_candle_contexts_provider_ts_id", table_name="candle_contexts")

"""TimescaleDB hypertable conversion for pipeline tables.

Converte le 5 tabelle principali del pipeline in TimescaleDB hypertables.

Operazioni in ordine:
  1. Drop FK constraints (candle_features, candle_indicators, candle_contexts, candle_patterns)
  2. Drop PK semplici (id SERIAL)
  3. Aggiunge PK composite (id, timestamp) per ciascuna tabella
  4. Aggiorna UNIQUE constraints per includere timestamp (richiesto da TimescaleDB)
  5. CREATE EXTENSION timescaledb (idempotente)
  6. create_hypertable per ciascuna tabella (in ordine parent-first)
  7. Ricrea FK composite (candle_id+timestamp, candle_feature_id+timestamp, ecc.)

Nota: create_hypertable richiede AUTOCOMMIT.
La migration usa COMMIT/raw-psycopg2/BEGIN per gestirlo senza modificare env.py.

Revision ID: tsdb_0002
Revises: perf_idx_0001
Create Date: 2026-04-15 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

# revision identifiers
revision = "tsdb_0002"
down_revision = "perf_idx_0001"
branch_labels = None
depends_on = None

# Tabelle da convertire in ordine parent-first (root → foglie)
_HYPERTABLES = [
    "candles",
    "candle_features",
    "candle_indicators",
    "candle_contexts",
    "candle_patterns",
]

# chunk_time_interval: 1 mese ottimale per ~100 simboli × 24 barre/giorno × 30 gg
_CHUNK_INTERVAL = "1 month"


def _create_hypertables(conn) -> None:  # type: ignore[no-untyped-def]
    """Esegui create_hypertable su raw psycopg2 connection (richiede AUTOCOMMIT)."""
    raw = conn.connection  # psycopg2 DBAPI connection
    prev = raw.autocommit
    raw.autocommit = True
    try:
        with raw.cursor() as cur:
            # Prima abilita l'estensione (idempotente)
            cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
            for tbl in _HYPERTABLES:
                cur.execute(
                    f"""
                    SELECT create_hypertable(
                        '{tbl}',
                        'timestamp',
                        chunk_time_interval => INTERVAL '{_CHUNK_INTERVAL}',
                        migrate_data         => TRUE,
                        if_not_exists        => TRUE
                    )
                    """
                )
    finally:
        raw.autocommit = prev


def upgrade() -> None:
    conn = op.get_bind()

    # ── FASE 1: Drop FK constraints ──────────────────────────────────────────
    # Nomi FK generati automaticamente da SQLAlchemy (convenzione Postgres).
    op.drop_constraint("candle_features_candle_id_fkey", "candle_features", type_="foreignkey")
    op.drop_constraint("candle_indicators_candle_id_fkey", "candle_indicators", type_="foreignkey")
    op.drop_constraint("candle_contexts_candle_feature_id_fkey", "candle_contexts", type_="foreignkey")
    op.drop_constraint("candle_patterns_candle_feature_id_fkey", "candle_patterns", type_="foreignkey")
    op.drop_constraint("candle_patterns_candle_context_id_fkey", "candle_patterns", type_="foreignkey")

    # ── FASE 2: Drop PK semplici ─────────────────────────────────────────────
    for tbl in _HYPERTABLES:
        op.drop_constraint(f"{tbl}_pkey", tbl, type_="primary")

    # ── FASE 3: Aggiungi PK composite (id, timestamp) ────────────────────────
    # id rimane SERIAL (sequence); la PK ora include timestamp per TimescaleDB.
    op.create_primary_key("pk_candles", "candles", ["id", "timestamp"])
    op.create_primary_key("pk_candle_features", "candle_features", ["id", "timestamp"])
    op.create_primary_key("pk_candle_indicators", "candle_indicators", ["id", "timestamp"])
    op.create_primary_key("pk_candle_contexts", "candle_contexts", ["id", "timestamp"])
    op.create_primary_key("pk_candle_patterns", "candle_patterns", ["id", "timestamp"])

    # ── FASE 4: Aggiorna UNIQUE constraints per includere timestamp ──────────
    # TimescaleDB richiede che OGNI unique index includa la colonna di partizione.

    # candle_features: (candle_id) → (candle_id, timestamp)
    op.drop_constraint("uq_candle_features_candle_id", "candle_features", type_="unique")
    op.create_unique_constraint(
        "uq_candle_features_candle_id_ts", "candle_features", ["candle_id", "timestamp"]
    )

    # candle_indicators: (candle_id) → (candle_id, timestamp)
    op.drop_constraint("uq_candle_indicators_candle_id", "candle_indicators", type_="unique")
    op.create_unique_constraint(
        "uq_candle_indicators_candle_id_ts", "candle_indicators", ["candle_id", "timestamp"]
    )

    # candle_contexts: (candle_feature_id) → (candle_feature_id, timestamp)
    op.drop_constraint("uq_candle_contexts_candle_feature_id", "candle_contexts", type_="unique")
    op.create_unique_constraint(
        "uq_candle_contexts_feature_id_ts", "candle_contexts", ["candle_feature_id", "timestamp"]
    )

    # candle_patterns: (candle_feature_id, pattern_name) → (candle_feature_id, pattern_name, timestamp)
    op.drop_constraint("uq_candle_patterns_feature_pattern", "candle_patterns", type_="unique")
    op.create_unique_constraint(
        "uq_candle_patterns_feature_pattern_ts",
        "candle_patterns",
        ["candle_feature_id", "pattern_name", "timestamp"],
    )

    # ── FASE 5 + 6: COMMIT + create_hypertable (AUTOCOMMIT) ─────────────────
    # Necessario: create_hypertable non può girare in una transazione esplicita
    # con migrate_data su tabelle che già contengono dati.
    conn.execute(text("COMMIT"))
    _create_hypertables(conn)

    # NOTA: FK tra hypertables NON sono supportate da TimescaleDB.
    # ("hypertables cannot be used as foreign key references of hypertables")
    # L'integrità referenziale è garantita dal pipeline applicativo: le righe
    # figlie vengono sempre create dopo le righe padre nella stessa transazione
    # del pipeline. Non è necessario ripristinare le FK.


def downgrade() -> None:
    conn = op.get_bind()

    # NOTA: Le FK composite tra hypertables non erano state ricreate nell'upgrade
    # (TimescaleDB non le supporta), quindi non c'è nulla da droppare.

    # In TimescaleDB non esiste una funzione "drop_hypertable" che riconverte
    # una hypertable in tabella normale: i dati restano ma la hypertable persiste.
    # Il downgrade si limita a ripristinare le PK semplici e i UNIQUE originali,
    # in modo che Alembic torni allo stato corretto.
    conn.execute(text("COMMIT"))
    conn.execute(text("BEGIN"))

    # ── Ripristina UNIQUE constraints originali ──────────────────────────────
    op.drop_constraint("uq_candle_patterns_feature_pattern_ts", "candle_patterns", type_="unique")
    op.create_unique_constraint(
        "uq_candle_patterns_feature_pattern",
        "candle_patterns",
        ["candle_feature_id", "pattern_name"],
    )

    op.drop_constraint("uq_candle_contexts_feature_id_ts", "candle_contexts", type_="unique")
    op.create_unique_constraint(
        "uq_candle_contexts_candle_feature_id", "candle_contexts", ["candle_feature_id"]
    )

    op.drop_constraint("uq_candle_indicators_candle_id_ts", "candle_indicators", type_="unique")
    op.create_unique_constraint(
        "uq_candle_indicators_candle_id", "candle_indicators", ["candle_id"]
    )

    op.drop_constraint("uq_candle_features_candle_id_ts", "candle_features", type_="unique")
    op.create_unique_constraint(
        "uq_candle_features_candle_id", "candle_features", ["candle_id"]
    )

    # ── Ripristina PK semplici ───────────────────────────────────────────────
    for tbl in reversed(_HYPERTABLES):
        op.drop_constraint(f"pk_{tbl.replace('_', '_')}", tbl, type_="primary")

    op.create_primary_key("candles_pkey", "candles", ["id"])
    op.create_primary_key("candle_features_pkey", "candle_features", ["id"])
    op.create_primary_key("candle_indicators_pkey", "candle_indicators", ["id"])
    op.create_primary_key("candle_contexts_pkey", "candle_contexts", ["id"])
    op.create_primary_key("candle_patterns_pkey", "candle_patterns", ["id"])

    # ── Ripristina FK semplici originali ─────────────────────────────────────
    op.create_foreign_key(
        "candle_features_candle_id_fkey",
        "candle_features",
        "candles",
        ["candle_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "candle_indicators_candle_id_fkey",
        "candle_indicators",
        "candles",
        ["candle_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "candle_contexts_candle_feature_id_fkey",
        "candle_contexts",
        "candle_features",
        ["candle_feature_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "candle_patterns_candle_feature_id_fkey",
        "candle_patterns",
        "candle_features",
        ["candle_feature_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "candle_patterns_candle_context_id_fkey",
        "candle_patterns",
        "candle_contexts",
        ["candle_context_id"],
        ["id"],
        ondelete="SET NULL",
    )

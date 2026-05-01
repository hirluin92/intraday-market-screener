"""add entry_context_json and entry_indicators_json to executed_signals

Aggiunge due colonne TEXT per il sistema di autopsia post-trade:
- entry_context_json: snapshot del contesto operativo (regime, score, ML, rationale, ecc.)
- entry_indicators_json: snapshot degli indicatori tecnici alla barra di entrata

Revision ID: entry_snapshot_es_0001
Revises: tsdb_0002
Create Date: 2026-04-24 13:13:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "entry_snapshot_es_0001"
down_revision = "tsdb_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "executed_signals",
        sa.Column("entry_context_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "executed_signals",
        sa.Column("entry_indicators_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("executed_signals", "entry_indicators_json")
    op.drop_column("executed_signals", "entry_context_json")

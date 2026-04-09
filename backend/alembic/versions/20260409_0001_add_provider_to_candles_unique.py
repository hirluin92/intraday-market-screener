"""add_provider_to_candles_unique_constraint

Bug A3: il vincolo unico sulla tabella candles non includeva la colonna `provider`,
rendendo possibile la sovrascrittura silenziosa di candele di un provider con
quelle di un altro (es. yahoo_finance sovrascrive binance se symbol/timeframe/ts
coincidono). La colonna `provider` è già presente e valorizzata nella tabella —
basta aggiungerla al constraint.

Revision ID: a3b4c5d6e7f8
Revises: 57ae0facc0b4
Create Date: 2026-04-09 00:01:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "57ae0facc0b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rimuove il vecchio vincolo senza `provider`
    op.drop_constraint(
        "uq_candles_exchange_symbol_timeframe_timestamp",
        "candles",
        type_="unique",
    )
    # Ricrea con `provider` come prima colonna
    op.create_unique_constraint(
        "uq_candles_provider_exchange_symbol_timeframe_timestamp",
        "candles",
        ["provider", "exchange", "symbol", "timeframe", "timestamp"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_candles_provider_exchange_symbol_timeframe_timestamp",
        "candles",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_candles_exchange_symbol_timeframe_timestamp",
        "candles",
        ["exchange", "symbol", "timeframe", "timestamp"],
    )

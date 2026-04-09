"""
Alembic env.py — intraday-market-screener.

Supporta sia offline che online (asyncpg).
L'URL viene prelevato da DATABASE_URL (env) oppure da settings.database_url_effective;
asyncpg viene convertito in psycopg2-style per le migrazioni sincrone di Alembic.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy import engine_from_config

# --------------------------------------------------------------------------- #
# Aggiungi il backend alla sys.path in modo che i model siano importabili.
# --------------------------------------------------------------------------- #
_backend_dir = Path(__file__).resolve().parents[1]
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

# --------------------------------------------------------------------------- #
# Import metadata dei modelli per autogenerate.
# --------------------------------------------------------------------------- #
import app.models  # noqa: F401 — registra tutti i modelli su Base.metadata
from app.db.base import Base  # noqa: E402

# --------------------------------------------------------------------------- #
# Alembic config
# --------------------------------------------------------------------------- #
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_sync_url() -> str:
    """
    Ritorna l'URL sincronico per Alembic.
    asyncpg -> psycopg2 (necessario per l'esecuzione sincrona di Alembic).
    Se presente DATABASE_URL come env var, usa quello; altrimenti config.ini.
    """
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url", "")
    # asyncpg non funziona con engine_from_config sincrono di Alembic.
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    url = url.replace("postgresql+psycopg://", "postgresql+psycopg2://")
    return url


def run_migrations_offline() -> None:
    """Genera SQL senza connessione DB (utile per review/deploy)."""
    url = _get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Applica le migrazioni direttamente al DB."""
    cfg_section = config.get_section(config.config_ini_section, {})
    cfg_section["sqlalchemy.url"] = _get_sync_url()

    connectable = engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Filtri orari UTC (sessioni US / liquidità) — Yahoo Finance; crypto 24/7 senza esclusioni."""

from __future__ import annotations

from datetime import datetime, timezone

# Default: pranzo NY (~17 UTC) e after hours (~21 UTC) su barre 1h US.
EXCLUDED_HOURS_UTC_YAHOO: frozenset[int] = frozenset({17, 21})


def hour_utc(dt: datetime) -> int:
    """Ora 0–23 in UTC (timestamp naive → interpretato come UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).hour
    return dt.astimezone(timezone.utc).hour
